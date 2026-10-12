"""Smoke tests for freshly-imported Frasberg Creator (branch conflict_111026_2245).
Covers: auth, image generation (CPU SD-Turbo fallback), listings, showcase, admin engine status.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://frasberg-secure-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin.tester@luchiiapp.com"
ADMIN_PASS = "AdminTest123!"
ADMIN2_EMAIL = "test@luchii.ai"
ADMIN2_PASS = "Test1234!"


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    if r.status_code != 200:
        # Try to register (fresh DB)
        rr = requests.post(f"{API}/auth/register", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS, "display_name": "Admin Tester"}, timeout=20)
        assert rr.status_code in (200, 201), f"register failed: {rr.status_code} {rr.text}"
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"no token in response: {data}"
    return token


@pytest.fixture(scope="session")
def admin2_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN2_EMAIL, "password": ADMIN2_PASS}, timeout=20)
    if r.status_code != 200:
        rr = requests.post(f"{API}/auth/register", json={"email": ADMIN2_EMAIL, "password": ADMIN2_PASS, "display_name": "Test Admin"}, timeout=20)
        assert rr.status_code in (200, 201), f"register failed: {rr.status_code} {rr.text}"
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN2_EMAIL, "password": ADMIN2_PASS}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


def test_showcase_public():
    r = requests.get(f"{API}/showcase", timeout=15)
    assert r.status_code == 200
    data = r.json()
    # Could be list or dict with items
    assert isinstance(data, (list, dict))


def test_generations_public():
    # Endpoint is session-scoped; requires session_id query param
    r = requests.get(f"{API}/generations", params={"session_id": "test-session", "limit": 4}, timeout=15)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), (list, dict))


def test_auth_me_admin(admin_token):
    r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me.get("email") == ADMIN_EMAIL
    # NOTE: /auth/me does NOT expose is_admin flag — admin privs enforced server-side only.
    # Verified below via /engines/status 200 for admin, 401 for anon.


def test_auth_me_admin2(admin2_token):
    r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {admin2_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me.get("email") == ADMIN2_EMAIL


def test_engines_status_requires_admin():
    r = requests.get(f"{API}/engines/status", timeout=15)
    assert r.status_code in (401, 403), f"expected 401/403 without token, got {r.status_code}"


def test_engines_status_admin(admin_token):
    r = requests.get(f"{API}/engines/status", headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), (list, dict))


def test_image_generation_draft(admin_token):
    """Allow long timeout — first generation loads SD-Turbo model."""
    payload = {
        "prompt": "a serene mountain lake at sunset, cinematic",
        "quality": "draft",
        "type": "image",
    }
    r = requests.post(
        f"{API}/generate",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=300,
    )
    assert r.status_code in (200, 201, 202), f"{r.status_code} {r.text[:500]}"
    data = r.json()
    gen_id = data.get("id") or data.get("_id") or data.get("generation_id")
    # Accept async job pattern
    if not gen_id and "job_id" in data:
        gen_id = data["job_id"]
    assert gen_id, f"no id in response: {list(data.keys())}"

    # Check for image content (b64 or url). If async job, poll.
    has_image = any(k in data for k in ("image", "image_base64", "b64", "url", "image_url", "output", "result"))
    if not has_image and "status" in data:
        # poll /api/generations for the item
        deadline = time.time() + 180
        while time.time() < deadline:
            time.sleep(5)
            rr = requests.get(f"{API}/my/generations", headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
            if rr.status_code == 200:
                items = rr.json() if isinstance(rr.json(), list) else rr.json().get("items", [])
                for it in items:
                    if (it.get("id") == gen_id or it.get("_id") == gen_id) and (it.get("status") in ("complete", "done", "success") or it.get("image") or it.get("url") or it.get("image_url")):
                        return
        pytest.fail("image job did not complete in time")


def test_my_generations_auth(admin_token):
    r = requests.get(f"{API}/my/generations", headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
    assert r.status_code == 200, r.text
    items = r.json()
    if isinstance(items, dict):
        items = items.get("items", [])
    assert isinstance(items, list)


def test_my_generations_requires_auth():
    r = requests.get(f"{API}/my/generations", timeout=15)
    assert r.status_code in (401, 403)
