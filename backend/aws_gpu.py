"""AWS EC2 GPU host for the Frasberg Serverless GPU Gateway.

With AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY set, the app runs the same Frasberg GPU worker as the Kaggle notebook
on a dedicated NVIDIA A10G (g5.xlarge, 24GB) in the owner's AWS account. Priority order for video is
AWS GPU -> free Kaggle T4 -> Frasberg Lite (CPU).

Mode (admin switch on /status, stored in db.aws_gpu_settings; AWS_GPU_MODE env is only the default):
  always_on  - a background reconciler keeps exactly one instance running 24/7 (restarts it if stopped, relaunches
               it if terminated).
  on_demand  - "Cost saver": a video request starts the instance; the backend stops it (stop, not terminate - disk
               and downloaded weights are kept) after `idle_min` minutes without GPU jobs, so it only bills while in use.
  off        - disabled.
The worker itself is mode-agnostic (systemd Restart=always, never idles out); the backend decides when the box runs,
so switching modes takes effect immediately without touching the instance.

The instance has no inbound ports (security group without ingress) and only calls out to the gateway over HTTPS.
One instance per gateway host (tag FrasbergGatewayHost), so preview and production never share/steal a worker.
"""
import asyncio
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse

import frasberg_gpu

log = logging.getLogger("luchii.aws")

db = None
_lock = asyncio.Lock()
_cache: dict = {}
STATUS_CACHE_S = 20
BOOT_WINDOW_S = 35 * 60      # a fresh launch/start counts as "booting" this long while no worker is online
RECONCILE_EVERY_S = 300     # always_on: make sure the box is running
IDLE_CHECK_EVERY_S = 60     # on_demand: look for an idle box to stop
IDLE_CHOICES = (10, 20, 30, 60, 120)
QUOTA_CODE = "L-DB2E81BA"    # Running On-Demand G and VT instances (vCPUs)
VCPUS = {"g5.xlarge": 4, "g5.2xlarge": 8, "g6.xlarge": 4, "g6e.xlarge": 4, "g5.4xlarge": 16}
AMI_NAME = "Deep Learning OSS Nvidia Driver AMI GPU PyTorch * (Ubuntu 24.04) *"
SG_NAME = "frasberg-gpu-worker"
EBS_GB_MONTH_USD = 0.08      # gp3 us-east-1, billed while the volume exists (also when the box is stopped)
HOURLY_USD = {"g5.xlarge": 1.006, "g5.2xlarge": 1.212, "g6.xlarge": 0.805, "g6e.xlarge": 1.861, "g5.4xlarge": 1.624}
AUTH_ERRORS = ("AuthFailure", "InvalidClientTokenId", "UnrecognizedClientException", "SignatureDoesNotMatch")
AUTH_BACKOFF_S = 15 * 60
_auth_fail_until = 0.0


_settings: dict = {}


def init(database):
    global db
    db = database


async def load_settings():
    doc = await db.aws_gpu_settings.find_one({"id": "aws"}, {"_id": 0}) or {}
    _settings.clear()
    _settings.update(doc)


async def set_settings(mode_: Optional[str] = None, idle_min: Optional[int] = None, by: str = "") -> dict:
    upd = {"updated_at": _now(), "updated_by": by}
    if mode_ is not None:
        if mode_ not in ("always_on", "on_demand"):
            raise ValueError("mode must be always_on or on_demand")
        upd["mode"] = mode_
    if idle_min is not None:
        if idle_min not in IDLE_CHOICES:
            raise ValueError(f"idle_min must be one of {IDLE_CHOICES}")
        upd["idle_min"] = idle_min
    await db.aws_gpu_settings.update_one({"id": "aws"}, {"$set": upd}, upsert=True)
    await load_settings()
    return {"mode": mode(), "idle_min": idle_min_()}


def _env(k: str, d: str = "") -> str:
    return os.environ.get(k, d).strip()


def enabled() -> bool:
    return bool(_env("AWS_ACCESS_KEY_ID") and _env("AWS_SECRET_ACCESS_KEY")) and mode() != "off"


def mode() -> str:
    if _env("AWS_GPU_MODE").lower() == "off":
        return "off"
    m = _settings.get("mode") or _env("AWS_GPU_MODE", "on_demand").lower()
    return m if m in ("always_on", "on_demand") else "on_demand"


def idle_min_() -> int:
    v = _settings.get("idle_min") or int(_env("AWS_GPU_MAX_IDLE_S", "1200")) // 60
    return int(v)


def region() -> str:
    return _env("AWS_REGION") or _env("AWS_DEFAULT_REGION") or "us-east-1"


def instance_type() -> str:
    return _env("AWS_GPU_INSTANCE_TYPE", "g5.xlarge")


def models() -> list:
    raw = _env("AWS_GPU_MODELS", "frasberg-motion-fast,frasberg-motion-free")
    return [m for m in raw.split(",") if m in frasberg_gpu.MODELS] or ["frasberg-motion-free"]


def host_of(gateway: str) -> str:
    return urlparse(gateway).hostname or "app"


def name_for(gateway: str) -> str:
    return f"frasberg-gpu-{hashlib.sha1(host_of(gateway).encode()).hexdigest()[:6]}"


def _session():
    import boto3
    return boto3.Session(aws_access_key_id=_env("AWS_ACCESS_KEY_ID"),
                         aws_secret_access_key=_env("AWS_SECRET_ACCESS_KEY"), region_name=region())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_s(iso: Optional[str]) -> float:
    if not iso:
        return 1e9
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()


# ---------- user-data ----------
def user_data(gateway: str, secret: str, worker_id: str) -> str:
    mods = ",".join(models())
    return f"""#!/bin/bash
set -uo pipefail
exec > >(tee -a /var/log/frasberg-gpu-bootstrap.log) 2>&1
GW='{gateway}'
SECRET='{secret}'
WID='{worker_id}'
boot() {{ curl -s -m 30 -X POST "$GW/worker/boot" -H "X-Frasberg-Worker-Secret: $SECRET" -H 'Content-Type: application/json' \\
  -d "{{\\"worker_id\\": \\"$WID\\", \\"stage\\": \\"$1\\", \\"detail\\": \\"${{2:-}}\\"}}" >/dev/null || true; }}
boot session-started "$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1) (AWS {instance_type()})"
mkdir -p /opt/frasberg /opt/frasberg/hf
cd /opt/frasberg
PY=/opt/pytorch/bin/python
[ -x "$PY" ] || PY=$(command -v python3)
if [ ! -f /opt/frasberg/.installed ]; then
  boot installing
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q ffmpeg >/dev/null 2>&1 || true
  $PY -m pip install -q "diffusers>=0.32" "transformers>=4.46" "accelerate>=1.2" sentencepiece protobuf ftfy \\
     "imageio[ffmpeg]" imageio-ffmpeg hf_transfer requests || {{ boot failed "pip install failed"; exit 1; }}
  touch /opt/frasberg/.installed
fi
for f in worker.py engines.py prefetch.py; do
  curl -sf -m 60 -H "X-Frasberg-Worker-Secret: $SECRET" "$GW/worker/files/$f" -o /opt/frasberg/$f || {{ boot failed "fetch $f"; exit 1; }}
done
cat >/etc/frasberg-worker.env <<EOF
FRASBERG_GATEWAY_URL=$GW
FRASBERG_WORKER_SECRET=$SECRET
FRASBERG_WORKER_MODELS={mods}
FRASBERG_WORKER_ID=$WID
FRASBERG_IDLE_UNLOAD_S=0
FRASBERG_WORKER_MAX_IDLE_S=0
FRASBERG_PRELOAD=1
HF_HOME=/opt/frasberg/hf
HF_HUB_ENABLE_HF_TRANSFER=1
HF_XET_HIGH_PERFORMANCE=1
EOF
chmod 600 /etc/frasberg-worker.env
boot downloading "{mods}"
set -a; . /etc/frasberg-worker.env; set +a
$PY prefetch.py {mods.replace(",", " ")} || {{ boot failed "model download failed"; exit 1; }}
cat >/etc/systemd/system/frasberg-worker.service <<UNIT
[Unit]
Description=Frasberg GPU worker
After=network-online.target
Wants=network-online.target
[Service]
WorkingDirectory=/opt/frasberg
EnvironmentFile=/etc/frasberg-worker.env
ExecStart=$PY /opt/frasberg/worker.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable frasberg-worker
systemctl restart frasberg-worker
"""


# ---------- sync boto3 helpers (run in a thread) ----------
def _find_sync(name: str) -> Optional[dict]:
    ec2 = _session().client("ec2")
    r = ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": [name]},
                                        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}])
    rows = [i for res in r["Reservations"] for i in res["Instances"]]
    return max(rows, key=lambda i: i["LaunchTime"]) if rows else None


def _quota_sync() -> Optional[float]:
    try:
        q = _session().client("service-quotas").get_service_quota(ServiceCode="ec2", QuotaCode=QUOTA_CODE)
        return float(q["Quota"]["Value"])
    except Exception as e:  # noqa: BLE001 - missing permission: don't block, let run_instances decide
        log.info("AWS quota check unavailable: %s", e.__class__.__name__)
        return None


def _quota_request_sync() -> Optional[dict]:
    try:
        h = _session().client("service-quotas").list_requested_service_quota_change_history_by_quota(
            ServiceCode="ec2", QuotaCode=QUOTA_CODE)["RequestedQuotas"]
        if not h:
            return None
        last = max(h, key=lambda r: r["Created"])
        return {"id": last["Id"], "status": last["Status"], "desired": last["DesiredValue"], "case_id": last.get("CaseId"),
                "created": last["Created"].isoformat()}
    except Exception:  # noqa: BLE001
        return None


def _ami_sync() -> str:
    pinned = _env("AWS_GPU_AMI_ID")
    if pinned:
        return pinned
    imgs = _session().client("ec2").describe_images(Owners=["amazon"], Filters=[
        {"Name": "name", "Values": [AMI_NAME]}, {"Name": "architecture", "Values": ["x86_64"]},
        {"Name": "state", "Values": ["available"]}])["Images"]
    if not imgs:
        raise RuntimeError("No AWS Deep Learning GPU AMI found")
    return max(imgs, key=lambda i: i["CreationDate"])["ImageId"]


def _sg_sync() -> str:
    ec2 = _session().client("ec2")
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise RuntimeError("The AWS region has no default VPC")
    vpc = vpcs[0]["VpcId"]
    found = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [SG_NAME]},
                                                  {"Name": "vpc-id", "Values": [vpc]}])["SecurityGroups"]
    if found:
        return found[0]["GroupId"]
    sg = ec2.create_security_group(GroupName=SG_NAME, VpcId=vpc,
                                   Description="Frasberg GPU worker - no inbound, HTTPS egress only")
    return sg["GroupId"]


def _launch_sync(gateway: str, secret: str, worker_id: str) -> dict:
    ec2 = _session().client("ec2")
    name = name_for(gateway)
    tags = [{"Key": "Name", "Value": name}, {"Key": "FrasbergGatewayHost", "Value": host_of(gateway)},
            {"Key": "FrasbergWorkerId", "Value": worker_id}, {"Key": "ManagedBy", "Value": "frasberg-creator"}]
    i = ec2.run_instances(
        ImageId=_ami_sync(), InstanceType=instance_type(), MinCount=1, MaxCount=1,
        SecurityGroupIds=[_sg_sync()], UserData=user_data(gateway, secret, worker_id),
        ClientToken=f"{name}-{uuid.uuid4().hex[:12]}",
        TagSpecifications=[{"ResourceType": "instance", "Tags": tags}, {"ResourceType": "volume", "Tags": tags}],
        BlockDeviceMappings=[{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": int(_env("AWS_GPU_VOLUME_GB", "200")),
                                                                  "VolumeType": "gp3", "Encrypted": True,
                                                                  "DeleteOnTermination": True}}],
        MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled"},
        InstanceInitiatedShutdownBehavior="stop")["Instances"][0]
    return {"instance_id": i["InstanceId"], "state": i["State"]["Name"]}


def _start_sync(instance_id: str):
    _session().client("ec2").start_instances(InstanceIds=[instance_id])


def _stop_sync(instance_id: str):
    _session().client("ec2").stop_instances(InstanceIds=[instance_id])


def _terminate_sync(instance_id: str):
    _session().client("ec2").terminate_instances(InstanceIds=[instance_id])


def _short(e: Exception) -> str:
    code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
    msg = str(e)
    if code in ("VcpuLimitExceeded", "InstanceLimitExceeded"):
        return "AWS GPU quota is too low (Running On-Demand G and VT instances). Waiting for the quota increase."
    if code in ("InsufficientInstanceCapacity",):
        return "AWS has no free g5 capacity in this region right now; retrying later."
    if code in AUTH_ERRORS:
        return "AWS rejected the access key; update AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY"
    return f"{code or e.__class__.__name__}: {msg[:220]}"


# ---------- async API ----------
async def _state(gateway: str) -> dict:
    return await db.aws_gpu.find_one({"name": name_for(gateway)}, {"_id": 0}) or {}


async def _save(gateway: str, **fields):
    await db.aws_gpu.update_one({"name": name_for(gateway)}, {"$set": {**fields, "name": name_for(gateway),
                                                                      "updated_at": _now()}}, upsert=True)


async def instance(gateway: str, fresh: bool = False) -> Optional[dict]:
    name = name_for(gateway)
    hit = _cache.get(name)
    global _auth_fail_until
    if hit and not fresh and time.monotonic() - hit[0] < STATUS_CACHE_S:
        return hit[1]
    if time.monotonic() < _auth_fail_until:
        return hit[1] if hit else None
    try:
        i = await asyncio.to_thread(_find_sync, name)
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
        if code in AUTH_ERRORS:
            _auth_fail_until = time.monotonic() + AUTH_BACKOFF_S
            log.warning("AWS credentials rejected (%s); pausing AWS calls for %ds", code, AUTH_BACKOFF_S)
        else:
            log.warning("AWS describe failed: %s", e)
        return hit[1] if hit else None
    info = None
    if i:
        tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
        info = {"instance_id": i["InstanceId"], "state": i["State"]["Name"], "type": i["InstanceType"],
                "az": i.get("Placement", {}).get("AvailabilityZone"), "launched": i["LaunchTime"].isoformat(),
                "worker_id": tags.get("FrasbergWorkerId")}
    _cache[name] = (time.monotonic(), info)
    return info


async def ensure(gateway: str, secret: str, reason: str) -> dict:
    """Make sure the GPU box exists and is running. Returns {"ok": bool, "action": ..., "reason": ...}."""
    if not enabled():
        return {"ok": False, "reason": "AWS GPU is not configured"}
    if time.monotonic() < _auth_fail_until:
        return {"ok": False, "reason": "AWS rejected the access key; update AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY"}
    async with _lock:
        cur = await instance(gateway, fresh=True)
        try:
            if cur and cur["state"] in ("pending", "running"):
                return {"ok": True, "action": "none", **cur}
            if cur and cur["state"] == "stopped":
                await asyncio.to_thread(_start_sync, cur["instance_id"])
                await _save(gateway, last_action="start", last_action_at=_now(), reason=reason, error=None,
                            worker_id=cur.get("worker_id"))
                _cache.pop(name_for(gateway), None)
                log.info("AWS GPU %s started (%s)", cur["instance_id"], reason)
                return {"ok": True, "action": "start", **cur}
            if cur and cur["state"] == "stopping":
                return {"ok": False, "reason": "The AWS GPU is stopping; it will be started again shortly"}
            need = VCPUS.get(instance_type(), 4)
            quota = await asyncio.to_thread(_quota_sync)
            if quota is not None and quota < need:
                req = await asyncio.to_thread(_quota_request_sync)
                msg = (f"AWS GPU quota is {quota:g} vCPU (needs {need}). "
                       + (f"Quota increase request is {req['status']}." if req else "Request a quota increase."))
                await _save(gateway, error=msg, error_at=_now(), quota=quota, quota_request=req)
                return {"ok": False, "reason": msg}
            wid = f"aws-{name_for(gateway)[-6:]}-{os.urandom(3).hex()}"
            res = await asyncio.to_thread(_launch_sync, gateway, secret, wid)
            await _save(gateway, last_action="launch", last_action_at=_now(), reason=reason, error=None,
                        worker_id=wid, instance_id=res["instance_id"], quota=quota)
            _cache.pop(name_for(gateway), None)
            log.info("AWS GPU %s launched (%s)", res["instance_id"], reason)
            return {"ok": True, "action": "launch", **res, "worker_id": wid}
        except Exception as e:  # noqa: BLE001
            msg = _short(e)
            log.warning("AWS GPU ensure failed: %s", msg)
            await _save(gateway, error=msg, error_at=_now())
            return {"ok": False, "reason": msg}


async def booting(gateway: str) -> Optional[dict]:
    """The AWS box that is still coming up (no worker online yet), or None when nothing is on its way."""
    if not enabled():
        return None
    cur = await instance(gateway)
    if not cur or cur["state"] not in ("pending", "running"):
        return None
    st = await _state(gateway)
    wid = st.get("worker_id") or cur.get("worker_id")
    boot = await db.gpu_boot.find_one({"worker_id": wid}, {"_id": 0, "log": 0}) if wid else None
    if boot and boot.get("stage") in ("failed", "stopped"):
        return None
    since = st.get("last_action_at") or cur.get("launched")
    if _age_s(since) > BOOT_WINDOW_S and not (boot and boot.get("stage") in ("installing", "downloading", "loading")):
        return None
    return {"instance": cur, "boot": boot, "worker_id": wid}


async def stop(gateway: str) -> dict:
    cur = await instance(gateway, fresh=True)
    if not cur or cur["state"] not in ("pending", "running"):
        return {"stopped": False, "reason": "No running AWS GPU"}
    await asyncio.to_thread(_stop_sync, cur["instance_id"])
    await _save(gateway, last_action="stop", last_action_at=_now(), paused=True)
    _cache.pop(name_for(gateway), None)
    return {"stopped": True, "instance_id": cur["instance_id"]}


async def terminate(gateway: str) -> dict:
    cur = await instance(gateway, fresh=True)
    if not cur:
        return {"terminated": False, "reason": "No AWS GPU instance"}
    await asyncio.to_thread(_terminate_sync, cur["instance_id"])
    await _save(gateway, last_action="terminate", last_action_at=_now(), paused=True)
    _cache.pop(name_for(gateway), None)
    return {"terminated": True, "instance_id": cur["instance_id"]}


async def resume(gateway: str, secret: str) -> dict:
    await _save(gateway, paused=False)
    return await ensure(gateway, secret, reason="admin start")


QUOTA_CHECK_EVERY_S = 300


async def check_quota(gateway: str) -> dict:
    """Refresh the G/VT quota; stamp quota_approved_at the first time it reaches what the instance needs."""
    st = await _state(gateway)
    need = VCPUS.get(instance_type(), 4)
    q = await asyncio.to_thread(_quota_sync)
    if q is None:
        return st
    fields = {"quota": q, "quota_checked_at": _now()}
    if q < need:
        fields["quota_request"] = await asyncio.to_thread(_quota_request_sync)
        fields["quota_approved_at"] = None
    elif not st.get("quota_approved_at"):
        fields["quota_approved_at"] = _now()
        fields["quota_alert_dismissed"] = False
        log.info("AWS GPU quota approved: %s vCPU (needs %s)", q, need)
    await _save(gateway, **fields)
    st.update(fields)
    return st


async def dismiss_quota_alert(gateway: str) -> dict:
    await _save(gateway, quota_alert_dismissed=True)
    return {"dismissed": True}


async def overview(gateway: str) -> dict:
    if not enabled():
        return {"configured": False}
    cur = await instance(gateway)
    st = await _state(gateway)
    wid = st.get("worker_id") or (cur or {}).get("worker_id")
    boot = await db.gpu_boot.find_one({"worker_id": wid}, {"_id": 0}) if wid else None
    if st.get("quota") is None or (st.get("quota") or 0) < VCPUS.get(instance_type(), 4):
        st = await check_quota(gateway)
    idle = await idle_info(gateway, cur) if cur and cur["state"] == "running" else None
    return {"configured": True, "mode": mode(), "idle_min": idle_min_(), "idle_choices": list(IDLE_CHOICES),
            "idle": idle, "hourly_usd": HOURLY_USD.get(instance_type()), "region": region(), "instance_type": instance_type(),
            "models": models(), "name": name_for(gateway), "gateway": gateway, "instance": cur, "boot": boot,
            "worker_id": wid, "quota": st.get("quota"), "quota_needed": VCPUS.get(instance_type(), 4),
            "quota_request": st.get("quota_request"), "quota_approved_at": st.get("quota_approved_at"),
            "quota_alert": bool(st.get("quota_approved_at")) and not st.get("quota_alert_dismissed") and mode() != "always_on",
            "error": st.get("error"), "paused": bool(st.get("paused")),
            "last_action": st.get("last_action"), "last_action_at": st.get("last_action_at")}


async def last_activity(gateway: str, cur: Optional[dict]) -> Optional[str]:
    """Most recent sign of GPU use: a GPU job created/finished, or the box being started/launched."""
    if await db.gpu_jobs.count_documents({"status": {"$in": ["queued", "running"]}, "model": {"$in": models()}}):
        return _now()
    times = []
    for f in ("created_at", "finished_at"):
        j = await db.gpu_jobs.find_one({"model": {"$in": models()}, f: {"$ne": None}}, {"_id": 0, f: 1}, sort=[(f, -1)])
        if j and j.get(f):
            times.append(j[f])
    st = await _state(gateway)
    for t in (st.get("last_action_at"), (cur or {}).get("launched")):
        if t:
            times.append(t)
    return max(times, key=lambda t: datetime.fromisoformat(t)) if times else None


async def idle_info(gateway: str, cur: Optional[dict]) -> dict:
    last = await last_activity(gateway, cur)
    idle_s = int(_age_s(last)) if last else 0
    left = max(0, idle_min_() * 60 - idle_s)
    return {"last_activity": last, "idle_s": idle_s, "stops_in_s": left if mode() == "on_demand" else None}


async def _idle_stop(gateway: str):
    cur = await instance(gateway, fresh=True)
    if not cur or cur["state"] != "running":
        return
    if await booting(gateway):  # still installing / downloading weights: never cut a cold start short
        return
    info = await idle_info(gateway, cur)
    if info["idle_s"] >= idle_min_() * 60:
        await asyncio.to_thread(_stop_sync, cur["instance_id"])
        await _save(gateway, last_action="idle-stop", last_action_at=_now())
        _cache.pop(name_for(gateway), None)
        log.info("AWS GPU %s stopped after %s idle min (cost saver)", cur["instance_id"], idle_min_())


# ---------- spend tracker ----------
def _month_bounds(month: Optional[str] = None):
    now = datetime.now(timezone.utc)
    if month:
        y, m = (int(x) for x in month.split("-"))
    else:
        y, m = now.year, now.month
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
    return start, end


async def record_usage(gateway: str):
    """Called every minute by the loop: extends the open run session while the box is running, closes it otherwise.
    A gap while the same instance stays running (backend restart) counts as running time."""
    cur = await instance(gateway, fresh=True)
    name = name_for(gateway)
    now = _now()
    open_s = await db.aws_gpu_usage.find_one({"name": name, "end": None}, {"_id": 0}, sort=[("start", -1)])
    running = bool(cur and cur["state"] == "running")
    if open_s and (not running or open_s["instance_id"] != cur["instance_id"]):
        await db.aws_gpu_usage.update_one({"id": open_s["id"]}, {"$set": {"end": open_s["last_seen"]}})
        open_s = None
    if running:
        if open_s:
            await db.aws_gpu_usage.update_one({"id": open_s["id"]}, {"$set": {"last_seen": now}})
        else:
            launched = cur.get("launched") or now
            start = launched if _age_s(launched) < 120 else now
            await db.aws_gpu_usage.insert_one({"id": uuid.uuid4().hex, "name": name, "instance_id": cur["instance_id"],
                                               "type": cur.get("type") or instance_type(), "start": start,
                                               "last_seen": now, "end": None})
    if cur:
        await db.aws_gpu.update_one({"name": name}, {"$set": {"volume_seen_at": now},
                                                      "$min": {"volume_since": now}}, upsert=True)


async def usage(gateway: str, month: Optional[str] = None) -> dict:
    start, end = _month_bounds(month)
    now = datetime.now(timezone.utc)
    name = name_for(gateway)
    rows = await db.aws_gpu_usage.find({"name": name, "start": {"$lt": end.isoformat()},
                                        "$or": [{"end": None}, {"end": {"$gte": start.isoformat()}}]},
                                       {"_id": 0}).sort("start", -1).to_list(2000)
    hours = 0.0
    compute = 0.0
    daily: dict = {}
    sessions = []
    for r in rows:
        a = max(datetime.fromisoformat(r["start"]), start)
        b = min(datetime.fromisoformat(r["end"] or r["last_seen"]), end)
        if b <= a:
            continue
        h = (b - a).total_seconds() / 3600
        rate = HOURLY_USD.get(r.get("type") or "", HOURLY_USD.get(instance_type(), 1.0))
        hours += h
        compute += h * rate
        t = a
        while t < b:  # split across UTC days for the daily chart
            day_end = datetime(t.year, t.month, t.day, tzinfo=timezone.utc) + timedelta(days=1)
            seg = min(day_end, b)
            k = t.date().isoformat()
            daily[k] = daily.get(k, 0.0) + (seg - t).total_seconds() / 3600
            t = seg
        if len(sessions) < 10:
            sessions.append({"instance_id": r["instance_id"], "start": r["start"], "end": r["end"],
                             "running": r["end"] is None, "hours": round(h, 2)})
    st = await _state(gateway)
    vol_since = st.get("volume_since")
    gb = int(_env("AWS_GPU_VOLUME_GB", "200"))
    storage = 0.0
    month_s = (end - start).total_seconds()
    if vol_since:
        vs = max(datetime.fromisoformat(vol_since), start)
        ve = min(datetime.fromisoformat(st.get("volume_seen_at") or vol_since), end)
        if st.get("last_action") != "terminate":
            ve = min(now, end)
        if ve > vs:
            storage = gb * EBS_GB_MONTH_USD * (ve - vs).total_seconds() / month_s
    is_current = start <= now < end
    projected = None
    if is_current:
        left_h = (end - now).total_seconds() / 3600
        rate = HOURLY_USD.get(instance_type(), 1.0)
        elapsed_h = max((now - start).total_seconds() / 3600, 1)
        if mode() == "always_on":
            future_compute = left_h * rate
        else:  # cost saver: keep the month's usage pace so far
            future_compute = hours / elapsed_h * left_h * rate
        future_storage = gb * EBS_GB_MONTH_USD * (end - now).total_seconds() / month_s if vol_since else 0.0
        projected = round(compute + storage + future_compute + future_storage, 2)
    days = []
    d = start
    last = min(end, now + timedelta(days=1)) if is_current else end
    while d < last:
        k = d.date().isoformat()
        days.append({"day": k, "hours": round(daily.get(k, 0.0), 2)})
        d += timedelta(days=1)
    return {"month": start.strftime("%Y-%m"), "hours": round(hours, 2), "compute_usd": round(compute, 2),
            "storage_usd": round(storage, 2), "total_usd": round(compute + storage, 2), "projected_usd": projected,
            "hourly_usd": HOURLY_USD.get(instance_type()), "volume_gb": gb, "mode": mode(), "daily": days,
            "sessions": sessions, "estimate": True}


async def reconcile_loop(gateway: str, secret: str):
    """always_on: keep one GPU box running (admin Stop pauses it until Start).
    on_demand (cost saver): stop the box once it has been idle for idle_min minutes."""
    await asyncio.sleep(20)
    last_ensure = 0.0
    last_quota = 0.0
    while True:
        try:
            st = await _state(gateway) if enabled() else {}
            if enabled() and not st.get("quota_approved_at") and time.monotonic() - last_quota >= QUOTA_CHECK_EVERY_S:
                last_quota = time.monotonic()
                await check_quota(gateway)
        except Exception:  # noqa: BLE001
            log.exception("AWS quota check error")
        try:
            if enabled() and mode() == "always_on":
                if time.monotonic() - last_ensure >= RECONCILE_EVERY_S and not (await _state(gateway)).get("paused"):
                    last_ensure = time.monotonic()
                    res = await ensure(gateway, secret, reason="always-on")
                    if res.get("action") not in (None, "none"):
                        log.info("AWS always-on reconcile: %s", res)
            elif enabled() and mode() == "on_demand":
                last_ensure = 0.0
                await _idle_stop(gateway)
        except Exception:  # noqa: BLE001
            log.exception("AWS reconcile error")
        try:
            if enabled():
                await record_usage(gateway)
        except Exception:  # noqa: BLE001
            log.exception("AWS usage tracking error")
        await asyncio.sleep(IDLE_CHECK_EVERY_S)
