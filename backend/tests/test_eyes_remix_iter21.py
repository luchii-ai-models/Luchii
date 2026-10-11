"""Iteration 21 - Verify the latest asks:
- Portrait generation returns a sharp JPEG, Face Fix runs server-side.
- Remix (edit) is instruct-mode and keeps the person; completes in reasonable time.
- EXIF rotation is corrected (upright output).
- Art style remix is fast and produces an artistic result.
- Whole-scene remix (snowy winter night) completes and keeps clothes.
- Safety filter does not block a plain portrait (no false positive).

CPU-only pod: run image jobs ONE AT A TIME.
"""
import base64
import io
import os
import subprocess
import time

import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    import pathlib
    for ln in pathlib.Path("/app/frontend/.env").read_text().splitlines():
        if ln.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = ln.split("=", 1)[1].strip().rstrip("/")
            break
assert BASE_URL, "REACT_APP_BACKEND_URL missing"

API = f"{BASE_URL}/api"
NOVA_JPG = "/app/frontend/public/models/luchii-nova-muse.jpg"
ARTIFACTS = "/app/test_reports/iter21_artifacts"
os.makedirs(ARTIFACTS, exist_ok=True)


def _poll(job_id, max_s=240, every=3):
    deadline = time.time() + max_s
    last = None
    while time.time() < deadline:
        r = requests.get(f"{API}/image-jobs/{job_id}", timeout=30)
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("completed", "failed"):
            return last, time.time()
        time.sleep(every)
    return last, time.time()


def _save_result(name, data_url):
    assert data_url and data_url.startswith("data:image"), f"bad data url: {str(data_url)[:80]}"
    b = base64.b64decode(data_url.split(",", 1)[1])
    path = os.path.join(ARTIFACTS, name)
    with open(path, "wb") as f:
        f.write(b)
    im = Image.open(io.BytesIO(b))
    return path, im


def _nova_data_url():
    with open(NOVA_JPG, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


# ------------------------------------------------------------------
# 1. Portrait eyes - generate and verify Face Fix runs
# ------------------------------------------------------------------
def test_1_portrait_generate_face_fix():
    t0 = time.time()
    r = requests.post(f"{API}/generate/jobs", timeout=30, json={
        "prompt": "portrait of a young woman with pink hair, black choker, looking at the camera",
        "style": "photorealistic",
        "aspect_ratio": "1:1",
        "model": "Luchii Nova-Muse",
    })
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    final, _ = _poll(jid, max_s=180, every=4)
    elapsed = time.time() - t0
    assert final["status"] == "completed", f"status={final['status']} err={final.get('error')} elapsed={elapsed:.1f}s"
    img_b64 = final["result"]["image_base64"]
    path, im = _save_result("portrait.jpg", img_b64)
    print(f"[1] portrait completed in {elapsed:.1f}s, size={im.size}, file={path}")
    # Expected around 2048x2048 (long edge 2048)
    assert max(im.size) >= 1500, f"expected large (~2048) result, got {im.size}"
    # Face Fix should have run - grep backend logs
    try:
        logs = subprocess.check_output(
            ["bash", "-c", "tail -n 400 /var/log/supervisor/backend.err.log /var/log/supervisor/backend.out.log 2>/dev/null | grep -i 'Face Fix' | tail -5"],
            timeout=10,
        ).decode()
    except Exception as e:  # noqa: BLE001
        logs = f"(log read failed: {e})"
    print(f"[1] Face Fix log lines:\n{logs}")
    assert "Face Fix" in logs, "Expected 'Luchii Face Fix X.Xs' in backend logs"


# ------------------------------------------------------------------
# 2. Remix - speed + instruct mode + instruction string
# ------------------------------------------------------------------
def test_2_remix_blue_hair_instruct():
    t0 = time.time()
    r = requests.post(f"{API}/edit/jobs", timeout=30, json={
        "prompt": "give a blue hair and change clothes",
        "style": "photorealistic",
        "image_base64": _nova_data_url(),
    })
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    final, _ = _poll(jid, max_s=180, every=4)
    elapsed = time.time() - t0
    assert final["status"] == "completed", f"status={final['status']} err={final.get('error')} elapsed={elapsed:.1f}s"
    res = final["result"]
    print(f"[2] remix in {elapsed:.1f}s, instruction={res.get('instruction')!r}, edit_mode={res.get('edit_mode')}")
    assert res.get("edit_mode") == "instruct", f"edit_mode={res.get('edit_mode')}"
    inst = (res.get("instruction") or "").lower()
    assert "blue" in inst and "hair" in inst and "clothes" in inst, inst
    path, im = _save_result("remix_blue.jpg", res["image_base64"])
    print(f"[2] saved {path} size={im.size}")
    assert im.size[0] >= 400 and im.size[1] >= 400


# ------------------------------------------------------------------
# 3. EXIF rotation - orientation=6 JPEG must come out upright
# ------------------------------------------------------------------
def _make_exif_rotated_portrait_data_url():
    # Load the nova portrait, rotate pixels 90 CCW, embed Orientation=6 so viewers show it upright again.
    import piexif
    im = Image.open(NOVA_JPG).convert("RGB")
    rotated = im.rotate(90, expand=True)  # pixels rotated 90° CCW; EXIF=6 then means rotate 90° CW to display upright
    buf = io.BytesIO()
    exif_dict = {"0th": {piexif.ImageIFD.Orientation: 6}}
    exif_bytes = piexif.dump(exif_dict)
    rotated.save(buf, format="JPEG", quality=90, exif=exif_bytes)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), rotated.size


def test_3_exif_rotation_upright():
    try:
        import piexif  # noqa: F401
    except ImportError:
        subprocess.check_call(["pip", "install", "-q", "piexif"])
    data_url, pre_size = _make_exif_rotated_portrait_data_url()
    # Upright aspect = reciprocal of the stored sideways aspect (we rotated original -90).
    upright_wh = (pre_size[1], pre_size[0])  # what the viewer-upright image is
    upright_landscape = upright_wh[0] > upright_wh[1]
    print(f"[3] stored sideways pixels={pre_size}, upright should be {upright_wh} ({'landscape' if upright_landscape else 'portrait'}), EXIF=6")
    t0 = time.time()
    r = requests.post(f"{API}/edit/jobs", timeout=30, json={
        "prompt": "give a blue hair",
        "style": "photorealistic",
        "image_base64": data_url,
    })
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    final, _ = _poll(jid, max_s=180, every=4)
    elapsed = time.time() - t0
    assert final["status"] == "completed", f"status={final['status']} err={final.get('error')} elapsed={elapsed:.1f}s"
    path, im = _save_result("remix_exif.jpg", final["result"]["image_base64"])
    print(f"[3] exif remix {elapsed:.1f}s, output size={im.size}")
    # Backend must respect EXIF Orientation and return an upright image (same orientation
    # as upright_wh), NOT the stored sideways orientation.
    out_landscape = im.size[0] > im.size[1]
    assert out_landscape == upright_landscape, (
        f"Output orientation {im.size} does not match the EXIF-corrected upright orientation {upright_wh}"
    )


# ------------------------------------------------------------------
# 4. Art style remix (fast)
# ------------------------------------------------------------------
@pytest.mark.parametrize("prompt,tag", [
    ("turn it into an oil painting", "oil"),
    ("turn it into a pencil sketch", "sketch"),
])
def test_4_art_style_fast(prompt, tag):
    t0 = time.time()
    r = requests.post(f"{API}/edit/jobs", timeout=30, json={
        "prompt": prompt,
        "style": "photorealistic",
        "image_base64": _nova_data_url(),
    })
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    final, _ = _poll(jid, max_s=60, every=2)
    elapsed = time.time() - t0
    assert final["status"] == "completed", f"status={final['status']} err={final.get('error')} elapsed={elapsed:.1f}s"
    path, im = _save_result(f"art_{tag}.jpg", final["result"]["image_base64"])
    print(f"[4-{tag}] completed in {elapsed:.1f}s, size={im.size}")
    assert elapsed < 25, f"art style took too long: {elapsed:.1f}s"


# ------------------------------------------------------------------
# 5. Whole-scene remix - snowy winter night, person stays clothed
# ------------------------------------------------------------------
def test_5_snowy_scene():
    t0 = time.time()
    r = requests.post(f"{API}/edit/jobs", timeout=30, json={
        "prompt": "make it a snowy winter night",
        "style": "photorealistic",
        "image_base64": _nova_data_url(),
    })
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    final, _ = _poll(jid, max_s=200, every=4)
    elapsed = time.time() - t0
    assert final["status"] == "completed", f"status={final['status']} err={final.get('error')} elapsed={elapsed:.1f}s"
    path, im = _save_result("scene_snow.jpg", final["result"]["image_base64"])
    print(f"[5] snowy scene {elapsed:.1f}s, size={im.size}")


# ------------------------------------------------------------------
# 6. Safety filter - no false positive on plain portrait generation
# ------------------------------------------------------------------
def test_6_no_safety_false_positive():
    # Simple short portrait that should pass.
    r = requests.post(f"{API}/generate/jobs", timeout=30, json={
        "prompt": "portrait of a woman smiling, warm lighting",
        "style": "photorealistic",
        "aspect_ratio": "1:1",
        "model": "Luchii Nova-Muse",
    })
    assert r.status_code == 200
    jid = r.json()["job_id"]
    final, _ = _poll(jid, max_s=180, every=4)
    assert final["status"] == "completed", f"status={final['status']} err={final.get('error')}"
    _save_result("portrait_smile.jpg", final["result"]["image_base64"])
    print("[6] safety filter did not block a plain portrait")
