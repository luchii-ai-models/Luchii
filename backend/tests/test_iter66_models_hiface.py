"""
Iteration 66 tests:
- Full-quality Nova-Muse portrait completes with hi-res face pass (~60-150s)
- Draft render completes quickly
- Painter-X edit works on a Models page jpg
- Admin gallery contains Models page generations (manifest.json ids resolvable via /api/share/{id})
- /models manifest.json has 57 entries each with a generation_id
- Normal user not blocked by engine rules
"""
import base64
import json
import os
import time
from pathlib import Path

import pytest
import requests

PUBLIC_URL = "https://luchii-media.preview.emergentagent.com"
LOCAL_URL = "http://localhost:8001"

ADMIN = {"email": "admin.tester@luchiiapp.com", "password": "AdminTest123!"}
USER = {"email": "test@luchii.ai", "password": "Test1234!"}

MANIFEST = Path("/app/frontend/public/models/manifest.json")
NOVA_JPG = Path("/app/frontend/public/models/luchii-nova-muse.jpg")


def _login(base, creds):
    r = requests.post(f"{base}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_token():
    return _login(PUBLIC_URL, ADMIN)


@pytest.fixture(scope="session")
def user_token():
    return _login(PUBLIC_URL, USER)


# ---- 1. Manifest sanity ----
def test_manifest_has_57_entries_with_generation_ids():
    data = json.loads(MANIFEST.read_text())
    assert isinstance(data, dict)
    assert len(data) == 57, f"expected 57 entries, got {len(data)}"
    missing = [k for k, v in data.items() if not v.get("generation_id")]
    assert not missing, f"entries missing generation_id: {missing[:5]}"


# ---- 2. Share endpoint resolves manifest generation ids ----
def test_manifest_generation_ids_resolve_via_share():
    data = json.loads(MANIFEST.read_text())
    gen_ids = [v["generation_id"] for v in data.values()]
    # Sample first 5, middle 5, last 5
    sample = gen_ids[:5] + gen_ids[len(gen_ids) // 2 : len(gen_ids) // 2 + 5] + gen_ids[-5:]
    failed = []
    for gid in sample:
        r = requests.get(f"{PUBLIC_URL}/api/share/{gid}", timeout=30)
        if r.status_code != 200:
            failed.append((gid, r.status_code))
            continue
        body = r.json()
        if not body.get("image_base64") and not body.get("image_url"):
            failed.append((gid, "no image in payload"))
    assert not failed, f"share resolution failures: {failed}"


# ---- 3. Admin gallery contains Models page generations ----
def test_admin_gallery_contains_models_generations(admin_token):
    r = requests.get(
        f"{PUBLIC_URL}/api/my/generations",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=60,
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    gens = r.json()
    if isinstance(gens, dict):
        gens = gens.get("items") or gens.get("generations") or []
    gen_ids_in_gallery = {g.get("id") or g.get("generation_id") for g in gens}
    manifest = json.loads(MANIFEST.read_text())
    manifest_ids = {v["generation_id"] for v in manifest.values()}
    overlap = manifest_ids & gen_ids_in_gallery
    # Expect at least a solid majority of models generations present
    assert len(overlap) >= 40, (
        f"admin gallery only contains {len(overlap)}/57 models generations"
    )


# ---- 4. Draft render completes quickly for admin ----
def _poll_job(base, token, job_id, deadline_s):
    headers = {"Authorization": f"Bearer {token}"}
    t0 = time.time()
    last = None
    while time.time() - t0 < deadline_s:
        r = requests.get(f"{base}/api/image-jobs/{job_id}", headers=headers, timeout=30)
        if r.status_code == 200:
            last = r.json()
            status = last.get("status")
            if status in ("completed", "failed", "error"):
                return last, time.time() - t0
        time.sleep(3)
    return last, time.time() - t0


def _submit_job(base, token, payload, retries=3):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for i in range(retries):
        r = requests.post(f"{base}/api/generate/jobs", headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(10 + i * 10)
            continue
        pytest.fail(f"submit job {r.status_code}: {r.text[:300]}")
    pytest.fail("submit job: repeatedly 429 busy")


def test_draft_nova_muse_completes(user_token):
    base = LOCAL_URL  # use local to avoid Cloudflare 403 on heavy POST
    job = _submit_job(
        base,
        user_token,
        {
            "prompt": "portrait photo of a smiling woman, natural light",
            "model": "Luchii Nova-Muse",
            "quality": "draft",
            "aspect_ratio": "1:1",
        },
    )
    jid = job.get("id") or job.get("job_id")
    assert jid, f"no job id in {job}"
    final, elapsed = _poll_job(base, user_token, jid, deadline_s=180)
    assert final and final.get("status") == "completed", (
        f"draft job did not complete in {elapsed:.1f}s: {final}"
    )
    # image_base64 may be on job or embedded
    img = final.get("image_base64") or (final.get("result") or {}).get("image_base64")
    assert img and len(img) > 1000, "draft job returned no image_base64"
    print(f"draft completed in {elapsed:.1f}s, b64 size={len(img)}")


# ---- 5. Full-quality Nova-Muse portrait with hi-res face pass ----
@pytest.mark.timeout(300)
def test_full_quality_nova_muse_hires_face(admin_token):
    base = LOCAL_URL
    # Wait a little in case previous test still has GPU/CPU pod warm/busy
    time.sleep(5)
    job = _submit_job(
        base,
        admin_token,
        {
            "prompt": "portrait photo of a smiling man with a beard, natural light",
            "model": "Luchii Nova-Muse",
            "quality": "full",
            "aspect_ratio": "1:1",
        },
    )
    jid = job.get("id") or job.get("job_id")
    assert jid
    final, elapsed = _poll_job(base, admin_token, jid, deadline_s=240)
    assert final and final.get("status") == "completed", (
        f"full job did not complete in {elapsed:.1f}s: status={final and final.get('status')} err={final and final.get('error')}"
    )
    img = final.get("image_base64") or (final.get("result") or {}).get("image_base64")
    assert img and len(img) > 10_000, "full job returned no (or tiny) image_base64"
    # Decode and check it's a reasonable size (hi-res pass should be around 2048px)
    raw = base64.b64decode(img)
    assert len(raw) > 50_000, f"image bytes too small ({len(raw)}), likely not hi-res"
    print(f"full completed in {elapsed:.1f}s, bytes={len(raw)}")


# ---- 6. Painter-X edit on Nova-Muse jpg ----
@pytest.mark.timeout(300)
def test_painter_x_edit_blue_hair(admin_token):
    base = LOCAL_URL
    assert NOVA_JPG.exists(), f"missing {NOVA_JPG}"
    b64 = base64.b64encode(NOVA_JPG.read_bytes()).decode()
    data_url = f"data:image/jpeg;base64,{b64}"
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    # Retry on 429
    r = None
    for i in range(3):
        r = requests.post(
            f"{base}/api/edit/jobs",
            headers=headers,
            json={"prompt": "give her blue hair", "image_base64": data_url},
            timeout=60,
        )
        if r.status_code == 200:
            break
        if r.status_code == 429:
            time.sleep(10 + i * 10)
            continue
        pytest.fail(f"edit submit {r.status_code}: {r.text[:300]}")
    job = r.json()
    jid = job.get("id") or job.get("job_id")
    assert jid, f"no job id {job}"
    final, elapsed = _poll_job(base, admin_token, jid, deadline_s=240)
    assert final and final.get("status") == "completed", (
        f"edit job did not complete in {elapsed:.1f}s: {final}"
    )
    img = final.get("image_base64") or (final.get("result") or {}).get("image_base64")
    assert img and len(img) > 5_000, "edit returned no image"
    print(f"edit completed in {elapsed:.1f}s")


# ---- 7. Normal user not blocked ----
def test_normal_user_not_blocked_by_engine_rules(user_token):
    # Already covered by draft test above but we re-assert the endpoint
    # doesn't return 403 for the engine/model combo.
    headers = {"Authorization": f"Bearer {user_token}", "Content-Type": "application/json"}
    r = requests.post(
        f"{LOCAL_URL}/api/generate/jobs",
        headers=headers,
        json={
            "prompt": "a cat sitting on a chair",
            "model": "Luchii Nova-Muse",
            "quality": "draft",
            "aspect_ratio": "1:1",
        },
        timeout=60,
    )
    assert r.status_code in (200, 429), f"normal user blocked: {r.status_code} {r.text[:200]}"
