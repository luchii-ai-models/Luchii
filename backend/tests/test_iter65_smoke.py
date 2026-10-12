"""Iteration 65 smoke/regression: auth, admin GPU admin endpoints, AWS auth-error handling, async T2I job."""
import os
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://luchii-media.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin.tester@luchiiapp.com"
ADMIN_PASS = "AdminTest123!"
USER_EMAIL = "test@luchii.ai"
USER_PASS = "Test1234!"


def _login(email, password):
    # try login first, if 401 then register
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code == 200:
        return r.json()["token"]
    r = requests.post(f"{BASE}/api/auth/register", json={"email": email, "password": password}, timeout=20)
    if r.status_code in (200, 201):
        return r.json().get("token") or requests.post(
            f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=20
        ).json()["token"]
    pytest.skip(f"Cannot log in {email}: {r.status_code} {r.text[:200]}")


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASS)


# ----- auth smoke -----
def test_auth_me_admin(admin_token):
    r = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data.get("email") == ADMIN_EMAIL


def test_auth_me_user(user_token):
    r = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {user_token}"}, timeout=15)
    assert r.status_code == 200
    assert r.json().get("email") == USER_EMAIL


# ----- admin endpoints: 200 for admin, 403 for user -----
@pytest.mark.parametrize("path", ["/api/engines/status", "/api/gpu-admin/overview", "/api/gpu-admin/aws"])
def test_admin_endpoints_admin_ok(path, admin_token):
    r = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
    # must not 500 even if AWS creds invalid
    assert isinstance(r.json(), (dict, list))


@pytest.mark.parametrize("path", ["/api/engines/status", "/api/gpu-admin/overview", "/api/gpu-admin/aws"])
def test_admin_endpoints_user_forbidden(path, user_token):
    r = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {user_token}"}, timeout=15)
    assert r.status_code == 403, f"{path} -> {r.status_code} {r.text[:200]}"


# ----- AWS auth-error short-circuit -----
def test_gpu_admin_aws_reports_auth_rejection(admin_token):
    # overview must not 500 (even with invalid creds the auth-error pause keeps it clean)
    r = requests.get(f"{BASE}/api/gpu-admin/aws", headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200, f"overview 500? {r.status_code} {r.text[:200]}"
    assert r.json().get("configured") is True

    # ensure() path (via /aws/start) must return a controlled reason, not 500
    s = requests.post(f"{BASE}/api/gpu-admin/aws/start", headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert s.status_code == 200, f"aws/start crashed: {s.status_code} {s.text[:300]}"
    sb = s.json()
    reason = (sb.get("reason") or "").lower()
    assert "rejected the access key" in reason, f"expected auth-rejection reason, got: {sb}"
    assert sb.get("ok") is False


# ----- async text-to-image job (draft) -----
def test_t2i_job_draft_completes(user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    payload = {"prompt": "a tiny red cube on a white background, product photo", "quality": "draft",
               "model": "Luchii Nova-Muse"}
    r = requests.post(f"{BASE}/api/generate/jobs", json=payload, headers=headers, timeout=30)
    assert r.status_code in (200, 201), f"create job: {r.status_code} {r.text[:200]}"
    job = r.json()
    job_id = job.get("id") or job.get("job_id") or job.get("_id")
    assert job_id, f"no job id in response: {job}"

    deadline = time.time() + 120  # pod CPU typically 30-70s
    status = None
    last = None
    while time.time() < deadline:
        p = requests.get(f"{BASE}/api/image-jobs/{job_id}", headers=headers, timeout=20)
        assert p.status_code == 200, f"poll: {p.status_code} {p.text[:200]}"
        last = p.json()
        status = last.get("status")
        if status in ("completed", "failed", "error"):
            break
        time.sleep(3)
    assert status == "completed", f"job did not complete: final={last}"
    # image_base64 either at top level or nested in result
    img = last.get("image_base64") or (last.get("result") or {}).get("image_base64")
    assert img and len(img) > 500, f"missing/short image_base64: len={len(img) if img else 0}"
