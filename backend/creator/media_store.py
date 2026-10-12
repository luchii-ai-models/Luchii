"""S3 media storage for generated images, video, music, voice and 3D files.

Active once AWS accepts the key and the bucket exists (checked at boot and every 15 min until then).
Stored file ids look like "s3:<key>"; older GridFS ObjectIds keep working, and migrate() moves them over.
"""
import asyncio
import base64
import logging
import os
import re
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from bson import ObjectId

log = logging.getLogger("luchii.s3")

RETRY_S = int(os.environ.get("S3_RETRY_S", 15 * 60))
PREFIX = "s3:"
state = {"ready": False, "error": None, "bucket": None, "migrated": None}
db = None
_client = None


def bucket() -> str:
    return os.environ.get("S3_MEDIA_BUCKET", "").strip()


def configured() -> bool:
    return bool(bucket() and os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))


def ready() -> bool:
    return state["ready"]


def _s3():
    global _client
    if _client is None:
        _client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _client


def _verify_sync():
    s3, name = _s3(), bucket()
    try:
        s3.head_bucket(Bucket=name)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
            raise
        region = os.environ.get("AWS_REGION", "us-east-1")
        kw = {} if region == "us-east-1" else {"CreateBucketConfiguration": {"LocationConstraint": region}}
        s3.create_bucket(Bucket=name, **kw)
        s3.put_public_access_block(Bucket=name, PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
        log.info("Created private S3 media bucket %s", name)


def is_s3(fid) -> bool:
    return isinstance(fid, str) and fid.startswith(PREFIX)


def put_sync(key: str, data: bytes, ctype: str = "application/octet-stream") -> str:
    _s3().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=ctype)
    return PREFIX + key


async def put(key: str, data: bytes, ctype: str = "application/octet-stream") -> str:
    return await asyncio.to_thread(put_sync, key, data, ctype)


async def get(fid: str) -> bytes:
    r = await asyncio.to_thread(_s3().get_object, Bucket=bucket(), Key=fid[len(PREFIX):])
    return await asyncio.to_thread(r["Body"].read)


async def delete(fid: str):
    await asyncio.to_thread(_s3().delete_object, Bucket=bucket(), Key=fid[len(PREFIX):])


class _Blob:
    def __init__(self, data: bytes):
        self._data = data

    async def read(self) -> bytes:
        return self._data


class Bucket:
    """GridFS-compatible bucket: writes to S3 when ready, reads from S3 or GridFS by id."""

    def __init__(self, fs, prefix: str):
        self.fs, self.prefix = fs, prefix

    async def upload_from_stream(self, filename: str, data: bytes, metadata: Optional[dict] = None):
        if ready():
            ctype = (metadata or {}).get("mime") or (metadata or {}).get("content_type") or "application/octet-stream"
            return await put(f"{self.prefix}/{filename}", data, ctype)
        return await self.fs.upload_from_stream(filename, data, metadata=metadata)

    async def open_download_stream(self, fid):
        if is_s3(fid):
            return _Blob(await get(fid))
        return await self.fs.open_download_stream(fid)

    async def delete(self, fid):
        if is_s3(fid):
            return await delete(fid)
        return await self.fs.delete(fid)


# ---------- images (generations) ----------
_DATA_URL = re.compile(r"^data:(image/[\w.+-]+);base64,")


def _decode(b64: str):
    m = _DATA_URL.match(b64)
    ctype = m.group(1) if m else "image/png"
    raw = base64.b64decode(b64[m.end():] if m else b64)
    return raw, ctype


async def put_image(gen_id: str, b64: str) -> str:
    raw, ctype = _decode(b64)
    ext = ctype.split("/")[1].replace("jpeg", "jpg")
    return await put(f"images/{gen_id}.{ext}", raw, ctype)


async def image_b64(fid: str) -> str:
    raw = await get(fid)
    ext = fid.rsplit(".", 1)[-1]
    ctype = "image/jpeg" if ext == "jpg" else f"image/{ext}"
    return f"data:{ctype};base64," + base64.b64encode(raw).decode()


async def full_image(doc: Optional[dict]) -> Optional[str]:
    """The full-size image of a generation doc (fetched from S3 when it was moved there)."""
    if not doc:
        return None
    if doc.get("s3_key"):
        return await image_b64(doc["s3_key"])
    return doc.get("image_base64")


# ---------- migration ----------
FILE_FIELDS = [("jobs", "file_id", "media"), ("jobs", "marked_file_id", "media"), ("voice_takes", "file_id", "voice_takes"),
               ("models3d", "file_id", "models3d"), ("gpu_jobs", "file_id", "gpu_outputs"), ("users", "voice_clone.file_id", "voice_samples")]


async def migrate(preview_fn) -> dict:
    """Move existing GridFS files and Mongo-stored images to S3 (idempotent)."""
    from motor.motor_asyncio import AsyncIOMotorGridFSBucket
    moved = {"files": 0, "images": 0, "errors": 0}
    for coll, field, bucket_name in FILE_FIELDS:
        fs = AsyncIOMotorGridFSBucket(db, bucket_name=bucket_name)
        async for d in db[coll].find({field: {"$type": "objectId"}}, {"_id": 1, field: 1}):
            fid = d
            for part in field.split("."):
                fid = fid[part]
            try:
                stream = await fs.open_download_stream(ObjectId(fid))
                data = await stream.read()
                meta = stream.metadata or {}
                key = await put(f"{bucket_name}/{stream.filename}", data, meta.get("mime") or meta.get("content_type") or "application/octet-stream")
                await db[coll].update_one({"_id": d["_id"]}, {"$set": {field: key}})
                await fs.delete(ObjectId(fid))
                moved["files"] += 1
            except Exception:  # noqa: BLE001
                moved["errors"] += 1
                log.exception("S3 migrate %s.%s failed", coll, field)
    async for g in db.generations.find({"s3_key": None, "image_base64": {"$ne": None}}, {"_id": 0, "id": 1, "image_base64": 1, "thumb_base64": 1}):
        try:
            key = await put_image(g["id"], g["image_base64"])
            thumb = g.get("thumb_base64") or await asyncio.to_thread(preview_fn, g["image_base64"])
            await db.generations.update_one({"id": g["id"]}, {"$set": {"s3_key": key, "image_base64": thumb, "thumb_base64": thumb}})
            moved["images"] += 1
        except Exception:  # noqa: BLE001
            moved["errors"] += 1
            log.exception("S3 migrate image %s failed", g["id"])
    log.info("S3 migration done: %s", moved)
    return moved


async def activate_loop(database, preview_fn):
    global db
    db = database
    if not configured():
        state["error"] = "S3_MEDIA_BUCKET or AWS keys are not set"
        return
    state["bucket"] = bucket()
    while not state["ready"]:
        try:
            await asyncio.to_thread(_verify_sync)
            state.update(ready=True, error=None)
            log.info("S3 media storage active (bucket %s)", bucket())
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
            state["error"] = f"{code or e.__class__.__name__}: {str(e)[:200]}"
            log.warning("S3 media storage not active yet (%s); retrying in %ds", state["error"], RETRY_S)
            await asyncio.sleep(RETRY_S)
    state["migrated"] = await migrate(preview_fn)
