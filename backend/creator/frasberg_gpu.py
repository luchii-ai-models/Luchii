"""Frasberg Serverless GPU Gateway.

Frasberg's own serverless GPU platform (in the style of fal.ai / Modal / RunPod / Replicate):
  * Client API, frasberg.com-compatible, authenticated with the exact `frb_live_*` keys in FRASBERG_API_KEYS:
      GET  /api/creator/gpu/v1/engines              list Frasberg engines + live worker capacity (public)
      POST /api/creator/gpu/generate/video          text-to-video / image-to-video -> task
      POST /api/creator/gpu/generate/image          text-to-image (waits up to `wait_seconds`) -> image or task
      GET  /api/creator/gpu/jobs/{task_id}          task status (+ video_url / image_url when done)
      GET  /api/creator/gpu/files/{task_id}         rendered output bytes
  * Worker API (GPU nodes anywhere pull work over HTTPS; header X-Frasberg-Worker-Secret):
      POST /api/creator/gpu/worker/heartbeat        register capacity (models, GPU, VRAM, warm model)
      POST /api/creator/gpu/worker/claim            atomically claim the next job (warm model first)
      POST /api/creator/gpu/worker/jobs/{id}/progress
      PUT  /api/creator/gpu/worker/jobs/{id}/chunk/{n}   chunked output upload (raw body)
      POST /api/creator/gpu/worker/jobs/{id}/complete
      POST /api/creator/gpu/worker/jobs/{id}/fail
Jobs live in Mongo (`gpu_jobs`), outputs in GridFS (`gpu_outputs`), workers in `gpu_workers`.
"""
import base64
import os
from pathlib import Path
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

import media_store
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/creator/gpu")

# Public Frasberg engine catalogue. `built_on` is kept for licence attribution (see worker NOTICE.md).
MODELS = {
    "frasberg-motion-free": {
        "name": "Frasberg Motion Free", "kind": "video", "tier": "free", "modes": ["text-to-video", "image-to-video"],
        "durations": [3, 4, 6, 8], "resolution": "480p · 24fps", "eta_seconds": 150, "min_vram_gb": 14,
        "eta_by_duration": {"3": 120, "4": 150, "6": 270, "8": 330},
        "built_on": "LTX-Video 2B (Lightricks)",
        "blurb": "Real AI motion on free GPUs (Kaggle / Colab T4). Zero cost; 6-8s clips are two renders stitched seamlessly.",
    },
    "frasberg-motion-fast": {
        "name": "Frasberg Motion Fast", "kind": "video", "tier": "fast", "modes": ["text-to-video", "image-to-video"],
        "durations": [3, 5, 8], "resolution": "768p", "eta_seconds": 45, "min_vram_gb": 24,
        "built_on": "LTX-Video 0.9.7 distilled (Lightricks)",
        "blurb": "Seconds-fast motion for drafts, social clips and quick iterations.",
    },
    "frasberg-motion-pro": {
        "name": "Frasberg Motion Pro", "kind": "video", "tier": "quality", "modes": ["text-to-video", "image-to-video"],
        "durations": [3, 5], "resolution": "720p · 24fps", "eta_seconds": 300, "min_vram_gb": 24,
        "built_on": "Wan 2.2 TI2V-5B (Wan-AI, Apache-2.0)",
        "blurb": "Cinematic, physically coherent motion with strong prompt following.",
    },
    "frasberg-motion-ultra": {
        "name": "Frasberg Motion Ultra", "kind": "video", "tier": "ultra", "modes": ["text-to-video", "image-to-video"],
        "durations": [3, 5], "resolution": "720p", "eta_seconds": 720, "min_vram_gb": 80,
        "built_on": "HunyuanVideo 13B (Tencent Hunyuan Community Licence)",
        "blurb": "Flagship fidelity for hero shots. Needs an 80GB-class GPU.",
    },
    "frasberg-image": {
        "name": "Frasberg Image", "kind": "image", "tier": "fast", "modes": ["text-to-image"],
        "durations": [], "resolution": "1MP", "eta_seconds": 6, "min_vram_gb": 16,
        "built_on": "FLUX.1-schnell (Black Forest Labs, Apache-2.0)",
        "blurb": "Sharp 4-step images with excellent text rendering.",
    },
    "frasberg-image-xl": {
        "name": "Frasberg Image XL", "kind": "image", "tier": "quality", "modes": ["text-to-image"],
        "durations": [], "resolution": "1MP (1024² · 1344×768)", "eta_seconds": 30, "min_vram_gb": 10,
        "built_on": "Juggernaut XL v9 (SDXL, RunDiffusion)",
        "blurb": "High-precision photoreal and art images that follow long prompts closely. Runs on a free T4.",
    },
    # Hidden protocol self-test engine (never shown in product UI, never used as a fallback).
    "frasberg-dev-test": {
        "name": "Frasberg Dev Test", "kind": "video", "tier": "dev", "modes": ["text-to-video", "image-to-video"],
        "durations": [1, 2], "resolution": "256p", "eta_seconds": 5, "min_vram_gb": 0, "hidden": True,
        "built_on": "procedural test pattern", "blurb": "Worker protocol self-test.",
    },
}
ASPECTS = {"16:9", "9:16", "1:1"}
ON_DEMAND: set = set()   # engines a free GPU can be started for on request (Kaggle), shown as "on demand"
WORKER_TTL = 45          # seconds without a heartbeat before a worker counts as offline
JOB_LEASE = 180          # seconds without progress before a running job is re-queued
MAX_ATTEMPTS = 3
QUEUE_TTL = 1800       # seconds a queued job may wait for a worker
MAX_CHUNK = 4 * 1024 * 1024

db = None
outputs_fs = None


def init(database):
    global db, outputs_fs
    db = database
    outputs_fs = media_store.Bucket(AsyncIOMotorGridFSBucket(database, bucket_name="gpu_outputs"), "gpu_outputs")


async def ensure_indexes():
    await db.gpu_jobs.create_index("id", unique=True)
    await db.gpu_jobs.create_index([("status", 1), ("model", 1), ("created_at", 1)])
    await db.gpu_workers.create_index("worker_id", unique=True)
    await db.gpu_chunks.create_index([("job_id", 1), ("n", 1)], unique=True)


def _now():
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _keys() -> set:
    return {k.strip() for k in os.environ.get("FRASBERG_API_KEYS", "").split(",") if k.strip()}


async def client_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else request.query_params.get("key", "")
    if not key or key not in _keys():
        raise HTTPException(status_code=401, detail={"error": "key_not_found", "code": "FK-001",
                                                     "message": "Invalid Frasberg API key"})
    return key


async def worker_auth(request: Request):
    secret = os.environ.get("FRASBERG_WORKER_SECRET", "")
    got = request.headers.get("X-Frasberg-Worker-Secret", "")
    if not secret or not secrets.compare_digest(secret, got):
        raise HTTPException(status_code=401, detail="Invalid worker secret")


# ---------- capacity ----------
async def online_workers(model: Optional[str] = None) -> list:
    q = {"last_seen": {"$gte": _iso(_now() - timedelta(seconds=WORKER_TTL))}}
    if model:
        q["models"] = model
    return await db.gpu_workers.find(q, {"_id": 0}).to_list(200)


async def is_online(model: str) -> bool:
    return bool(await online_workers(model))


async def _queue_depth(model: str) -> int:
    return await db.gpu_jobs.count_documents({"model": model, "status": "queued"})


async def _requeue_stale():
    """Re-queue running jobs whose worker vanished (lease expired); fail after MAX_ATTEMPTS.
    Queued jobs nobody picked up within QUEUE_TTL expire so a worker coming online later never renders stale work."""
    await db.gpu_jobs.update_many(
        {"status": "queued", "created_at": {"$lt": _iso(_now() - timedelta(seconds=QUEUE_TTL))}},
        {"$set": {"status": "failed", "error": "No Frasberg GPU worker picked this job up in time",
                  "finished_at": _iso(_now())}})
    cutoff = _iso(_now() - timedelta(seconds=JOB_LEASE))
    async for j in db.gpu_jobs.find({"status": "running", "lease_at": {"$lt": cutoff}}, {"_id": 0}):
        if j.get("attempts", 0) >= MAX_ATTEMPTS:
            await db.gpu_jobs.update_one({"id": j["id"], "status": "running"},
                                         {"$set": {"status": "failed", "error": "GPU worker lost the job repeatedly",
                                                   "finished_at": _iso(_now())}})
        else:
            await db.gpu_jobs.update_one({"id": j["id"], "status": "running"},
                                         {"$set": {"status": "queued", "worker_id": None}})


# ---------- job helpers (also used in-process by the Luchii backend) ----------
async def submit(kind: str, model: str, prompt: str, *, duration: int = 5, aspect_ratio: str = "16:9",
                 image_base64: Optional[str] = None, negative_prompt: Optional[str] = None,
                 seed: Optional[int] = None, owner: str = "luchii") -> dict:
    spec = MODELS.get(model)
    if not spec or spec["kind"] != kind:
        raise HTTPException(status_code=422, detail=f"Unknown Frasberg {kind} engine '{model}'")
    if image_base64 and "image-to-video" not in spec["modes"]:
        raise HTTPException(status_code=422, detail=f"{spec['name']} does not accept a start image")
    durations = spec["durations"] or [0]
    dur = min(durations, key=lambda d: abs(d - duration)) if spec["durations"] else 0
    job = {
        "id": f"gtask_{_now().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:10]}", "kind": kind, "model": model,
        "status": "queued", "prompt": prompt.strip(), "negative_prompt": negative_prompt, "seed": seed,
        "duration": dur, "aspect_ratio": aspect_ratio if aspect_ratio in ASPECTS else "16:9",
        "image_base64": image_base64.split(",", 1)[-1] if image_base64 else None,
        "mode": "image-to-video" if image_base64 else ("text-to-image" if kind == "image" else "text-to-video"),
        "progress": 0.0, "attempts": 0, "owner": owner, "error": None, "created_at": _iso(_now()),
    }
    await db.gpu_jobs.insert_one(job.copy())
    return job


async def get_job(task_id: str) -> Optional[dict]:
    return await db.gpu_jobs.find_one({"id": task_id}, {"_id": 0, "image_base64": 0})


async def output_bytes(job: dict) -> bytes:
    stream = await outputs_fs.open_download_stream(job["file_id"])
    return await stream.read()


async def job_view(job: dict) -> dict:
    spec = MODELS.get(job["model"], {})
    out = {"task_id": job["id"], "job_id": job["id"], "status": job["status"], "model": job["model"],
           "engine": spec.get("name"), "mode": job.get("mode"), "progress": round(job.get("progress") or 0, 3),
           "duration": job.get("duration"), "aspect_ratio": job.get("aspect_ratio"), "error": job.get("error"),
           "eta_seconds": spec.get("eta_seconds"), "created_at": job.get("created_at")}
    if job["status"] == "queued":
        out["queue_position"] = await db.gpu_jobs.count_documents(
            {"model": job["model"], "status": "queued", "created_at": {"$lt": job["created_at"]}}) + 1
        out["workers_online"] = len(await online_workers(job["model"]))
    if job["status"] == "completed":
        url = f"/api/creator/gpu/files/{job['id']}"
        out["result"] = {"url": url, "mime": job.get("mime"), "render_seconds": job.get("render_seconds")}
        out["video_url" if job["kind"] == "video" else "image_url"] = url
    return out


# ---------- client API ----------
class VideoIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    model: str = "frasberg-motion-fast"
    duration: int = 5
    aspect_ratio: str = "16:9"
    image_base64: Optional[str] = None
    negative_prompt: Optional[str] = None
    seed: Optional[int] = None


class ImageIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    model: str = "frasberg-image"
    aspect_ratio: str = "1:1"
    seed: Optional[int] = None
    wait_seconds: int = 0


@router.get("/v1/engines")
async def engines(include_hidden: bool = False):
    await _requeue_stale()
    data = []
    for mid, spec in MODELS.items():
        if spec.get("hidden") and not include_hidden:
            continue
        workers = await online_workers(mid)
        data.append({"id": mid, **{k: v for k, v in spec.items() if k != "hidden"},
                     "workers_online": len(workers), "warm": any(w.get("loaded_model") == mid for w in workers),
                     "queue_depth": await _queue_depth(mid), "on_demand": mid in ON_DEMAND,
                     "status": "online" if workers else ("on-demand" if mid in ON_DEMAND else "offline")})
    return {"object": "list", "provider": "frasberg", "data": data}


@router.post("/generate/video")
async def generate_video(body: VideoIn, key: str = Depends(client_key)):
    job = await submit("video", body.model, body.prompt, duration=body.duration, aspect_ratio=body.aspect_ratio,
                       image_base64=body.image_base64, negative_prompt=body.negative_prompt, seed=body.seed,
                       owner=key[:17])
    return await job_view(job)


@router.post("/generate/image")
async def generate_image(body: ImageIn, key: str = Depends(client_key)):
    import asyncio
    job = await submit("image", body.model, body.prompt, aspect_ratio=body.aspect_ratio, seed=body.seed,
                       owner=key[:17])
    for _ in range(max(0, min(body.wait_seconds, 120))):
        await asyncio.sleep(1)
        cur = await get_job(job["id"])
        if cur["status"] == "completed":
            return {**await job_view(cur), "image_base64": base64.b64encode(await output_bytes(cur)).decode(),
                    "mime": cur.get("mime")}
        if cur["status"] == "failed":
            raise HTTPException(status_code=424, detail=cur.get("error") or "Render failed")
    return await job_view(await get_job(job["id"]))


@router.get("/jobs/{task_id}")
async def job_status(task_id: str, _: str = Depends(client_key)):
    await _requeue_stale()
    job = await get_job(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="Task not found")
    return await job_view(job)


@router.get("/files/{task_id}")
async def job_file(task_id: str, _: str = Depends(client_key)):
    job = await get_job(task_id)
    if not job or job["status"] != "completed":
        raise HTTPException(status_code=404, detail="Not ready")
    return Response(content=await output_bytes(job), media_type=job.get("mime") or "application/octet-stream")


# ---------- worker API ----------
class HeartbeatIn(BaseModel):
    worker_id: str
    models: list
    gpu: Optional[str] = None
    vram_gb: Optional[float] = None
    loaded_model: Optional[str] = None
    busy: bool = False
    version: Optional[str] = None


class ClaimIn(BaseModel):
    worker_id: str
    models: list
    loaded_model: Optional[str] = None


class ProgressIn(BaseModel):
    worker_id: str
    progress: float = 0.0


class CompleteIn(BaseModel):
    worker_id: str
    chunks: int
    mime: str
    render_seconds: Optional[float] = None


class FailIn(BaseModel):
    worker_id: str
    error: str
    retryable: bool = False


WORKER_DIR = Path(__file__).parent / "frasberg_gpu_worker"
WORKER_FILES = {"worker.py", "engines.py", "prefetch.py", "requirements-gpu.txt", "README.md", "NOTICE.md", "Dockerfile"}


@router.get("/worker/files/{name}", dependencies=[Depends(worker_auth)])
async def worker_file(name: str):
    """Serve the worker source so a fresh GPU box (e.g. a free Kaggle/Colab notebook) can bootstrap itself."""
    if name not in WORKER_FILES or not (WORKER_DIR / name).is_file():
        raise HTTPException(status_code=404, detail="Unknown worker file")
    return Response(content=(WORKER_DIR / name).read_bytes(), media_type="text/plain; charset=utf-8")


@router.post("/worker/heartbeat", dependencies=[Depends(worker_auth)])
async def heartbeat(body: HeartbeatIn, request: Request):
    models = [m for m in body.models if m in MODELS]
    await db.gpu_workers.update_one(
        {"worker_id": body.worker_id},
        {"$set": {"worker_id": body.worker_id, "models": models, "gpu": body.gpu, "vram_gb": body.vram_gb,
                  "loaded_model": body.loaded_model, "busy": body.busy, "version": body.version,
                  "last_seen": _iso(_now()), "ip": request.client.host if request.client else None},
         "$setOnInsert": {"first_seen": _iso(_now())}}, upsert=True)
    w = await db.gpu_workers.find_one({"worker_id": body.worker_id}, {"_id": 0, "stop_requested": 1})
    return {"ok": True, "accepted_models": models, "stop": bool((w or {}).get("stop_requested"))}


class BootIn(BaseModel):
    worker_id: str
    stage: str = Field(max_length=40)
    detail: str = Field(default="", max_length=300)


BOOT_STAGES = {"session-started": "GPU session started", "installing": "Installing the render engine",
               "downloading": "Downloading model weights", "loading": "Loading the model onto the GPU",
               "ready": "GPU worker online", "stopped": "GPU worker stopped", "failed": "GPU session failed"}


@router.post("/worker/boot", dependencies=[Depends(worker_auth)])
async def boot(body: BootIn):
    """Lifecycle beacons from a (free) GPU session, so the app can say what a cold-starting worker is doing."""
    now = _iso(_now())
    await db.gpu_boot.update_one(
        {"worker_id": body.worker_id},
        {"$set": {"worker_id": body.worker_id, "stage": body.stage, "label": BOOT_STAGES.get(body.stage, body.stage),
                  "detail": body.detail, "at": now},
         "$setOnInsert": {"started_at": now},
         "$push": {"log": {"$each": [{"stage": body.stage, "detail": body.detail, "at": now}], "$slice": -20}}},
        upsert=True)
    return {"ok": True}


class OfflineIn(BaseModel):
    worker_id: str


@router.post("/worker/offline", dependencies=[Depends(worker_auth)])
async def offline(body: OfflineIn):
    await db.gpu_workers.update_one({"worker_id": body.worker_id},
                                    {"$set": {"last_seen": _iso(_now() - timedelta(seconds=WORKER_TTL * 10)), "busy": False}})
    return {"ok": True}


async def latest_boot(minutes: int = 40) -> Optional[dict]:
    since = _iso(_now() - timedelta(minutes=minutes))
    return await db.gpu_boot.find_one({"at": {"$gte": since}}, {"_id": 0, "log": 0}, sort=[("at", -1)])


async def request_stop() -> int:
    """Ask every online worker to finish its current job and exit (frees a free Kaggle/Colab GPU session)."""
    since = _iso(_now() - timedelta(seconds=WORKER_TTL))
    res = await db.gpu_workers.update_many({"last_seen": {"$gte": since}}, {"$set": {"stop_requested": True}})
    return res.modified_count


@router.post("/worker/claim", dependencies=[Depends(worker_auth)])
async def claim(body: ClaimIn):
    await _requeue_stale()
    models = [m for m in body.models if m in MODELS]
    order = ([body.loaded_model] if body.loaded_model in models else []) + [m for m in models if m != body.loaded_model]
    now = _iso(_now())
    for m in order:  # warm model first -> no cold start
        job = await db.gpu_jobs.find_one_and_update(
            {"status": "queued", "model": m},
            {"$set": {"status": "running", "worker_id": body.worker_id, "started_at": now, "lease_at": now},
             "$inc": {"attempts": 1}},
            sort=[("created_at", 1)], projection={"_id": 0}, return_document=True)
        if job:
            await db.gpu_chunks.delete_many({"job_id": job["id"]})
            return {"job": job}
    return {"job": None}


async def _owned(job_id: str, worker_id: str) -> dict:
    job = await db.gpu_jobs.find_one({"id": job_id}, {"_id": 0, "image_base64": 0})
    if not job or job.get("status") != "running" or job.get("worker_id") != worker_id:
        raise HTTPException(status_code=409, detail="Job is not leased to this worker")
    return job


@router.post("/worker/jobs/{job_id}/progress", dependencies=[Depends(worker_auth)])
async def progress(job_id: str, body: ProgressIn):
    await _owned(job_id, body.worker_id)
    await db.gpu_jobs.update_one({"id": job_id}, {"$set": {"progress": max(0.0, min(1.0, body.progress)),
                                                           "lease_at": _iso(_now())}})
    return {"ok": True}


@router.put("/worker/jobs/{job_id}/chunk/{n}", dependencies=[Depends(worker_auth)])
async def upload_chunk(job_id: str, n: int, request: Request):
    await _owned(job_id, request.headers.get("X-Frasberg-Worker-Id", ""))
    data = await request.body()
    if not data or len(data) > MAX_CHUNK:
        raise HTTPException(status_code=413, detail=f"Chunk must be 1..{MAX_CHUNK} bytes")
    await db.gpu_chunks.update_one({"job_id": job_id, "n": n}, {"$set": {"data": data}}, upsert=True)
    await db.gpu_jobs.update_one({"id": job_id}, {"$set": {"lease_at": _iso(_now())}})
    return {"ok": True, "n": n, "bytes": len(data)}


@router.post("/worker/jobs/{job_id}/complete", dependencies=[Depends(worker_auth)])
async def complete(job_id: str, body: CompleteIn):
    job = await _owned(job_id, body.worker_id)
    parts = await db.gpu_chunks.find({"job_id": job_id}).sort("n", 1).to_list(10000)
    if len(parts) != body.chunks or [p["n"] for p in parts] != list(range(body.chunks)):
        raise HTTPException(status_code=400, detail=f"Expected {body.chunks} chunks, got {len(parts)}")
    data = b"".join(p["data"] for p in parts)
    file_id = await outputs_fs.upload_from_stream(f"{job['kind']}/{job_id}", data,
                                                  metadata={"mime": body.mime, "model": job["model"]})
    await db.gpu_jobs.update_one({"id": job_id}, {"$set": {
        "status": "completed", "file_id": file_id, "mime": body.mime, "bytes": len(data), "progress": 1.0,
        "render_seconds": body.render_seconds, "finished_at": _iso(_now())}, "$unset": {"image_base64": ""}})
    await db.gpu_chunks.delete_many({"job_id": job_id})
    return {"ok": True, "bytes": len(data)}


@router.post("/worker/jobs/{job_id}/fail", dependencies=[Depends(worker_auth)])
async def fail(job_id: str, body: FailIn):
    job = await _owned(job_id, body.worker_id)
    retry = body.retryable and job.get("attempts", 0) < MAX_ATTEMPTS
    await db.gpu_jobs.update_one({"id": job_id}, {"$set": (
        {"status": "queued", "worker_id": None} if retry else
        {"status": "failed", "error": body.error[:500], "finished_at": _iso(_now())})})
    await db.gpu_chunks.delete_many({"job_id": job_id})
    return {"ok": True, "requeued": retry}


# ---------- free GPU bootstrap (Kaggle / Colab notebook) ----------
def _cell(kind: str, src: str) -> dict:
    c = {"cell_type": kind, "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)}
    if kind == "code":
        c.update(execution_count=None, outputs=[])
    return c


def build_notebook(gateway: str, secret: str, models: str = "frasberg-motion-free", worker_id: Optional[str] = None,
                   max_idle_s: int = 1200) -> dict:
    """A ready-to-run notebook that turns a free Kaggle/Colab T4 into a Frasberg GPU worker.

    It runs unattended (Kaggle "Save & Run All" / API push): every step reports a boot stage to the gateway, the
    weights are prefetched, the engine is preloaded, and the worker exits after `max_idle_s` without jobs so an idle
    session stops spending the weekly free GPU hours."""
    wid = worker_id or f"freegpu-{uuid.uuid4().hex[:8]}"
    cells = [
        _cell("markdown", f"""
# Frasberg GPU Worker - free T4 (Kaggle / Colab)
This notebook turns a free GPU into a **Frasberg Motion Free** render node for your Frasberg Creator app.

**Kaggle:** Settings → Accelerator **GPU T4**, Internet **On**, then *Run All* (30 free GPU-hours a week).
**Colab:** Runtime → Change runtime type → **T4 GPU**, then *Run all*.

While the last cell runs, **Frasberg Motion Free** shows **online** in the Video Creator. The worker shuts itself
down after {max_idle_s // 60} idle minutes to save GPU hours; the app starts it again on the next video.
Gateway: `{gateway}` · engines: `{models}`
"""),
        _cell("code", f"""
import os, sys, subprocess, requests
os.environ["FRASBERG_GATEWAY_URL"] = "{gateway}"
os.environ["FRASBERG_WORKER_SECRET"] = "{secret}"  # keep this notebook private
os.environ["FRASBERG_WORKER_MODELS"] = "{models}"
os.environ["FRASBERG_WORKER_ID"] = "{wid}"
os.environ["FRASBERG_IDLE_UNLOAD_S"] = "1800"
os.environ["FRASBERG_WORKER_MAX_IDLE_S"] = "{max_idle_s}"
os.environ["FRASBERG_PRELOAD"] = "1"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
os.environ["HF_XET_HIGH_PERFORMANCE"] = "1"
os.environ.setdefault("HF_HOME", "/tmp/hf")
WORKDIR = "/kaggle/working/frasberg" if os.path.isdir("/kaggle") else "/content/frasberg"
os.makedirs(WORKDIR, exist_ok=True)
H = {{"X-Frasberg-Worker-Secret": os.environ["FRASBERG_WORKER_SECRET"]}}
GW = os.environ["FRASBERG_GATEWAY_URL"]

def boot(stage, detail=""):
    try:
        requests.post(f"{{GW}}/worker/boot", headers=H, timeout=30,
                      json={{"worker_id": os.environ["FRASBERG_WORKER_ID"], "stage": stage, "detail": str(detail)[:300]}})
    except Exception as e:
        print("boot beacon failed:", e)

def sh(cmd, stage):
    print("$", cmd, flush=True)
    p = subprocess.Popen(cmd, shell=True, cwd=WORKDIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in p.stdout:
        print(line, end="", flush=True)
        tail = (tail + [line.strip()])[-3:]
    if p.wait() != 0:
        boot("failed", f"{{stage}}: {{' | '.join(tail)}}")
        raise SystemExit(f"{{stage}} failed")

gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
print(gpu)
boot("session-started", gpu or "no GPU detected")
"""),
        _cell("code", """
boot("installing")
sh(f'{sys.executable} -m pip install -q "diffusers>=0.32" "transformers>=4.46" "accelerate>=1.2" sentencepiece protobuf ftfy "imageio[ffmpeg]" imageio-ffmpeg hf_transfer', "install")
for name in ["worker.py", "engines.py", "prefetch.py"]:
    r = requests.get(f"{GW}/worker/files/{name}", headers=H, timeout=60)
    r.raise_for_status()
    open(f"{WORKDIR}/{name}", "w").write(r.text)
    print("fetched", name, len(r.text), "bytes")
"""),
        _cell("code", """
boot("downloading", os.environ["FRASBERG_WORKER_MODELS"])
sh(f'{sys.executable} prefetch.py {os.environ["FRASBERG_WORKER_MODELS"].replace(",", " ")}', "download")
"""),
        _cell("code", """
# Runs until idle: claims Frasberg jobs, renders on this GPU, uploads results. Stop it with the Stop button.
sh(f"{sys.executable} worker.py", "worker")
"""),
    ]
    return {"cells": cells, "metadata": {"accelerator": "GPU", "kernelspec": {"name": "python3", "display_name": "Python 3"},
                                         "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}


async def recent_workers(minutes: int = 60) -> list:
    since = _iso(_now() - timedelta(minutes=minutes))
    rows = await db.gpu_workers.find({"last_seen": {"$gte": since}}, {"_id": 0}).sort("last_seen", -1).to_list(100)
    cutoff = _iso(_now() - timedelta(seconds=WORKER_TTL))
    for w in rows:
        w["online"] = w["last_seen"] >= cutoff
    return rows


async def job_stats() -> dict:
    out = {}
    for st in ("queued", "running", "completed", "failed"):
        out[st] = await db.gpu_jobs.count_documents({"status": st})
    return out
