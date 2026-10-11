"""AWS EC2 GPU host for the Frasberg Serverless GPU Gateway.

With AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY set, the app runs the same Frasberg GPU worker as the Kaggle notebook
on a dedicated NVIDIA A10G (g5.xlarge, 24GB) in the owner's AWS account. Priority order for video is
AWS GPU -> free Kaggle T4 -> Frasberg Lite (CPU).

AWS_GPU_MODE:
  always_on  - a background reconciler keeps exactly one instance running 24/7 (restarts it if stopped, relaunches
               it if terminated). The worker never idles out (systemd Restart=always).
  on_demand  - a video request starts the instance; the worker exits after AWS_GPU_MAX_IDLE_S without jobs and the
               box powers itself off (stop, not terminate), so it only bills while in use.
  off        - disabled.

The instance has no inbound ports (security group without ingress) and only calls out to the gateway over HTTPS.
One instance per gateway host (tag FrasbergGatewayHost), so preview and production never share/steal a worker.
"""
import asyncio
import base64
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import frasberg_gpu

log = logging.getLogger("luchii.aws")

db = None
_lock = asyncio.Lock()
_cache: dict = {}
STATUS_CACHE_S = 20
BOOT_WINDOW_S = 35 * 60      # a fresh launch/start counts as "booting" this long while no worker is online
RECONCILE_EVERY_S = 300
QUOTA_CODE = "L-DB2E81BA"    # Running On-Demand G and VT instances (vCPUs)
VCPUS = {"g5.xlarge": 4, "g5.2xlarge": 8, "g6.xlarge": 4, "g6e.xlarge": 4, "g5.4xlarge": 16}
AMI_NAME = "Deep Learning OSS Nvidia Driver AMI GPU PyTorch * (Ubuntu 24.04) *"
SG_NAME = "frasberg-gpu-worker"


def init(database):
    global db
    db = database


def _env(k: str, d: str = "") -> str:
    return os.environ.get(k, d).strip()


def enabled() -> bool:
    return bool(_env("AWS_ACCESS_KEY_ID") and _env("AWS_SECRET_ACCESS_KEY")) and mode() != "off"


def mode() -> str:
    m = _env("AWS_GPU_MODE", "on_demand").lower()
    return m if m in ("always_on", "on_demand", "off") else "on_demand"


def region() -> str:
    return _env("AWS_REGION") or _env("AWS_DEFAULT_REGION") or "us-east-1"


def instance_type() -> str:
    return _env("AWS_GPU_INSTANCE_TYPE", "g5.xlarge")


def models() -> list:
    raw = _env("AWS_GPU_MODELS", "frasberg-motion-fast,frasberg-motion-free")
    return [m for m in raw.split(",") if m in frasberg_gpu.MODELS] or ["frasberg-motion-free"]


def max_idle_s() -> int:
    return 0 if mode() == "always_on" else int(_env("AWS_GPU_MAX_IDLE_S", "1200"))


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
    restart = "always" if mode() == "always_on" else "no"
    after_exit = "" if mode() == "always_on" else "ExecStopPost=/usr/bin/systemctl poweroff\n"
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
FRASBERG_WORKER_MAX_IDLE_S={max_idle_s()}
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
Restart={restart}
RestartSec=10
{after_exit}[Install]
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
    if code == "InsufficientInstanceCapacity":
        return "AWS has no free g5 capacity in this region right now; retrying later."
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
    if hit and not fresh and time.monotonic() - hit[0] < STATUS_CACHE_S:
        return hit[1]
    try:
        i = await asyncio.to_thread(_find_sync, name)
    except Exception as e:  # noqa: BLE001
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


async def overview(gateway: str) -> dict:
    if not enabled():
        return {"configured": False}
    cur = await instance(gateway)
    st = await _state(gateway)
    wid = st.get("worker_id") or (cur or {}).get("worker_id")
    boot = await db.gpu_boot.find_one({"worker_id": wid}, {"_id": 0}) if wid else None
    if st.get("quota") is None or (st.get("quota") or 0) < VCPUS.get(instance_type(), 4):
        q = await asyncio.to_thread(_quota_sync)
        if q is not None:
            req = await asyncio.to_thread(_quota_request_sync)
            await _save(gateway, quota=q, quota_request=req)
            st.update(quota=q, quota_request=req)
    return {"configured": True, "mode": mode(), "region": region(), "instance_type": instance_type(),
            "models": models(), "name": name_for(gateway), "gateway": gateway, "instance": cur, "boot": boot,
            "worker_id": wid, "quota": st.get("quota"), "quota_needed": VCPUS.get(instance_type(), 4),
            "quota_request": st.get("quota_request"), "error": st.get("error"), "paused": bool(st.get("paused")),
            "last_action": st.get("last_action"), "last_action_at": st.get("last_action_at")}


async def reconcile_loop(gateway: str, secret: str):
    """always_on: keep one GPU box running. Admin Stop pauses it until Start is pressed."""
    await asyncio.sleep(20)
    while True:
        try:
            if enabled() and mode() == "always_on" and not (await _state(gateway)).get("paused"):
                res = await ensure(gateway, secret, reason="always-on")
                if res.get("action") not in (None, "none"):
                    log.info("AWS always-on reconcile: %s", res)
        except Exception:  # noqa: BLE001
            log.exception("AWS reconcile error")
        await asyncio.sleep(RECONCILE_EVERY_S)
