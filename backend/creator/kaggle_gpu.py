"""Free Kaggle GPU launcher for the Frasberg Serverless GPU Gateway.

With KAGGLE_API_TOKEN (+ KAGGLE_USERNAME) set, the app pushes a private notebook to the owner's Kaggle account that
runs on a free T4 with internet on, bootstraps the Frasberg GPU worker (frasberg_gpu.build_notebook) and serves
Frasberg Motion Free jobs. The worker exits by itself after a stretch without jobs, so the weekly free GPU hours
are only spent while people are making videos; the next video request launches it again.
"""
import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse

import frasberg_gpu

log = logging.getLogger("luchii.kaggle")

MACHINE = "NvidiaTeslaT4"
RELAUNCH_GUARD_S = 240      # a fresh push needs a moment before Kaggle reports the new session
BOOT_WINDOW_S = 25 * 60     # a launch younger than this counts as "booting" when no worker is online yet
MAX_IDLE_S = 20 * 60        # worker exits after this many idle seconds
STATUS_CACHE_S = 20

db = None
_lock = asyncio.Lock()
_status_cache: dict = {}


def init(database):
    global db
    db = database


def token() -> str:
    return os.environ.get("KAGGLE_API_TOKEN", "").strip()


def username() -> str:
    return os.environ.get("KAGGLE_USERNAME", "").strip()


def enabled() -> bool:
    return bool(token() and username())


def slug_for(gateway: str) -> str:
    """One kernel per app host, so preview and production never steal each other's worker."""
    host = urlparse(gateway).hostname or "app"
    return f"frasberg-gpu-worker-{hashlib.sha1(host.encode()).hexdigest()[:6]}"


def kernel_url(slug: str) -> str:
    return f"https://www.kaggle.com/code/{username()}/{slug}"


def _client():
    from kagglesdk import KaggleClient
    return KaggleClient(api_token=token())


def _push_sync(slug: str, notebook: dict) -> dict:
    from kagglesdk.kernels.types.kernels_api_service import ApiSaveKernelRequest
    req = ApiSaveKernelRequest()
    req.slug = f"{username()}/{slug}"
    req.new_title = slug
    req.text = json.dumps(notebook)
    req.language = "python"
    req.kernel_type = "notebook"
    req.is_private = True
    req.enable_gpu = True
    req.enable_tpu = False
    req.enable_internet = True
    req.machine_shape = MACHINE
    req.dataset_data_sources = []
    req.competition_data_sources = []
    req.kernel_data_sources = []
    req.model_data_sources = []
    req.category_ids = []
    with _client() as k:
        r = k.kernels.kernels_api_client.save_kernel(req)
    return {"url": r.url, "version": r.version_number, "error": r.error or None}


def _status_sync(slug: str) -> dict:
    from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelSessionStatusRequest
    req = ApiGetKernelSessionStatusRequest()
    req.user_name = username()
    req.kernel_slug = slug
    try:
        with _client() as k:
            r = k.kernels.kernels_api_client.get_kernel_session_status(req)
    except Exception as e:  # noqa: BLE001 - 403/404 = never pushed yet
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (403, 404):
            return {"status": "none", "message": ""}
        raise
    return {"status": r.status.name.lower(), "message": r.failure_message or ""}


async def session_status(slug: str, fresh: bool = False) -> dict:
    hit = _status_cache.get(slug)
    if hit and not fresh and time.monotonic() - hit[0] < STATUS_CACHE_S:
        return hit[1]
    try:
        st = await asyncio.to_thread(_status_sync, slug)
    except Exception as e:  # noqa: BLE001
        log.warning("Kaggle status failed: %s", e)
        st = {"status": "unknown", "message": e.__class__.__name__}
    _status_cache[slug] = (time.monotonic(), st)
    return st


async def last_launch(slug: str) -> Optional[dict]:
    return await db.kaggle_launches.find_one({"slug": slug}, {"_id": 0}, sort=[("at", -1)])


def _age_s(iso: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()


async def launch(gateway: str, secret: str, reason: str, models: str = "frasberg-motion-free",
                 force: bool = False) -> dict:
    """Push + run the worker notebook unless a session is already queued/running or was just launched."""
    if not enabled():
        return {"launched": False, "reason": "Kaggle is not configured"}
    slug = slug_for(gateway)
    async with _lock:
        if not force:
            if await frasberg_gpu.is_online(models.split(",")[0]):
                return {"launched": False, "reason": "A GPU worker is already online", "slug": slug}
            last = await last_launch(slug)
            if last and _age_s(last["at"]) < RELAUNCH_GUARD_S:
                return {"launched": False, "reason": "Launched moments ago", "slug": slug, "last": last}
            st = await session_status(slug, fresh=True)
            if st["status"] in ("queued", "running", "new_script"):
                return {"launched": False, "reason": f"Kaggle session already {st['status']}", "slug": slug}
        wid = f"kaggle-{slug[-6:]}-{os.urandom(3).hex()}"
        nb = frasberg_gpu.build_notebook(gateway, secret, models, worker_id=wid, max_idle_s=MAX_IDLE_S)
        try:
            res = await asyncio.to_thread(_push_sync, slug, nb)
        except Exception as e:  # noqa: BLE001
            log.exception("Kaggle push failed")
            return {"launched": False, "reason": f"Kaggle push failed: {e.__class__.__name__}: {str(e)[:200]}", "slug": slug}
        if res.get("error"):
            return {"launched": False, "reason": f"Kaggle refused the notebook: {res['error']}", "slug": slug}
        doc = {"slug": slug, "worker_id": wid, "version": res.get("version"), "url": res.get("url") or kernel_url(slug),
               "reason": reason, "models": models, "gateway": gateway, "at": datetime.now(timezone.utc).isoformat()}
        await db.kaggle_launches.insert_one(doc.copy())
        _status_cache.pop(slug, None)
        log.info("Kaggle GPU worker launched (%s) v%s: %s", reason, res.get("version"), doc["url"])
        return {"launched": True, "slug": slug, **doc}


async def booting(gateway: str) -> Optional[dict]:
    """The launch that is still cold-starting (no worker online yet), or None when nothing is on its way."""
    if not enabled():
        return None
    slug = slug_for(gateway)
    last = await last_launch(slug)
    if not last or _age_s(last["at"]) > BOOT_WINDOW_S:
        return None
    st = await session_status(slug)
    if st["status"] in ("error", "cancel_requested", "cancel_acknowledged"):
        return None
    if st["status"] == "complete" and _age_s(last["at"]) > RELAUNCH_GUARD_S:
        return None
    boot = await db.gpu_boot.find_one({"worker_id": last["worker_id"]}, {"_id": 0, "log": 0})
    if boot and boot.get("stage") in ("failed", "stopped"):
        return None
    return {**last, "kaggle_status": st["status"], "boot": boot}


async def overview(gateway: str) -> dict:
    if not enabled():
        return {"configured": False}
    slug = slug_for(gateway)
    last = await last_launch(slug)
    st = await session_status(slug)
    boot = await db.gpu_boot.find_one({"worker_id": last["worker_id"]}, {"_id": 0}) if last else None
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    return {"configured": True, "gateway": gateway, "username": username(), "slug": slug, "url": kernel_url(slug), "machine": MACHINE,
            "status": st["status"], "message": st["message"], "last_launch": last, "boot": boot,
            "launches_7d": await db.kaggle_launches.count_documents({"slug": slug, "at": {"$gte": week}}),
            "max_idle_min": MAX_IDLE_S // 60}
