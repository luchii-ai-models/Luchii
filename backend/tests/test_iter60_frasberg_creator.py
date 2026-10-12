"""Iter60 — Frasberg Creator backend regression tests."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://luchii-import.preview.emergentagent.com").rstrip("/")

USER_EMAIL = "localtest@frasberg.com"
USER_PASS = "LocalTest!2026x"
ADMIN_EMAIL = "admin@frasberg.com"
# Admin password from backend/.env
ADMIN_PASS = "wFDbM063P_ck8jdeLMQ"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text[:200]}"
    return s


@pytest.fixture(scope="module")
def user_session():
    return _login(USER_EMAIL, USER_PASS)


@pytest.fixture(scope="module")
def admin_session():
    return _login(ADMIN_EMAIL, ADMIN_PASS)


# ----------------- Creator root / health -----------------
def test_creator_root():
    r = requests.get(f"{BASE_URL}/api/creator/", timeout=20)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert "Frasberg Creator" in str(data.get("message", "")), data


# ----------------- Shared auth -----------------
def test_creator_auth_me_unauth():
    r = requests.get(f"{BASE_URL}/api/creator/auth/me", timeout=20)
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]}"


def test_creator_auth_me_authed(user_session):
    r = user_session.get(f"{BASE_URL}/api/creator/auth/me", timeout=20)
    assert r.status_code == 200, r.text[:200]
    me = r.json()
    assert me.get("email") == USER_EMAIL, me


def test_creator_separate_register_removed():
    r = requests.post(f"{BASE_URL}/api/creator/auth/register",
                      json={"email": f"x{uuid.uuid4().hex[:6]}@t.com", "password": "whatever"}, timeout=20)
    assert r.status_code in (404, 405), f"expected removed, got {r.status_code}"


def test_creator_separate_login_removed():
    r = requests.post(f"{BASE_URL}/api/creator/auth/login",
                      json={"email": USER_EMAIL, "password": USER_PASS}, timeout=20)
    assert r.status_code in (404, 405), f"expected removed, got {r.status_code}"


# ----------------- Authenticated CRUD / lists -----------------
def test_creator_my_generations(user_session):
    r = user_session.get(f"{BASE_URL}/api/creator/my/generations", timeout=20)
    assert r.status_code == 200, r.text[:200]
    assert isinstance(r.json(), list)


def test_creator_voice_takes(user_session):
    r = user_session.get(f"{BASE_URL}/api/creator/voice/takes", timeout=20)
    assert r.status_code == 200, r.text[:200]
    assert isinstance(r.json(), list)


def test_creator_spaces_crud(user_session):
    # list
    r = user_session.get(f"{BASE_URL}/api/creator/spaces", timeout=20)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    # create
    name = f"TEST_space_{uuid.uuid4().hex[:6]}"
    r = user_session.post(f"{BASE_URL}/api/creator/spaces", json={"name": name}, timeout=20)
    assert r.status_code in (200, 201), r.text[:200]
    sp = r.json()
    sid = sp.get("id") or sp.get("_id") or sp.get("space_id")
    assert sid, f"no id in response: {sp}"
    # fetch
    r = user_session.get(f"{BASE_URL}/api/creator/spaces/{sid}", timeout=20)
    assert r.status_code == 200, r.text[:200]
    # delete
    r = user_session.delete(f"{BASE_URL}/api/creator/spaces/{sid}", timeout=20)
    assert r.status_code in (200, 204), r.text[:200]


# ----------------- Public listings -----------------
def test_creator_showcase():
    r = requests.get(f"{BASE_URL}/api/creator/showcase", timeout=20)
    assert r.status_code == 200, r.text[:200]


def test_creator_chat_models():
    r = requests.get(f"{BASE_URL}/api/creator/chat/models", timeout=20)
    assert r.status_code == 200, r.text[:200]


def test_creator_gpu_engines():
    r = requests.get(f"{BASE_URL}/api/creator/gpu/v1/engines", timeout=20)
    assert r.status_code == 200, r.text[:200]


# ----------------- Admin-only endpoints -----------------
def test_engines_status_non_admin_forbidden(user_session):
    r = user_session.get(f"{BASE_URL}/api/creator/engines/status", timeout=30)
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"


def test_gpu_admin_overview_non_admin_forbidden(user_session):
    r = user_session.get(f"{BASE_URL}/api/creator/gpu-admin/overview", timeout=30)
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"


def test_engines_status_admin_ok(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/creator/engines/status", timeout=60)
    assert r.status_code == 200, r.text[:200]


def test_gpu_admin_overview_admin_ok(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/creator/gpu-admin/overview", timeout=60)
    assert r.status_code == 200, r.text[:200]


# ----------------- Platform regression -----------------
def test_platform_auth_me(user_session):
    r = user_session.get(f"{BASE_URL}/api/auth/me", timeout=20)
    assert r.status_code == 200, r.text[:200]
    assert r.json().get("email") == USER_EMAIL


def test_platform_permission_matrix(user_session):
    # Create video-only key -> cannot image_generation
    r = user_session.post(f"{BASE_URL}/api/keys",
                          json={"name": f"TEST_video_{uuid.uuid4().hex[:5]}",
                                "permissions": {"video_generation": "access"}}, timeout=30)
    assert r.status_code in (200, 201), r.text[:300]
    kv = r.json()
    video_key = kv.get("key") or kv.get("api_key") or kv.get("secret") or kv.get("plaintext")
    assert video_key, f"no plaintext key returned: {kv}"

    # Create image-only key
    r = user_session.post(f"{BASE_URL}/api/keys",
                          json={"name": f"TEST_image_{uuid.uuid4().hex[:5]}",
                                "permissions": {"image_generation": "access"}}, timeout=30)
    assert r.status_code in (200, 201), r.text[:300]
    ki = r.json()
    image_key = ki.get("key") or ki.get("api_key") or ki.get("secret") or ki.get("plaintext")
    assert image_key

    # Video-only -> 403 on /api/generate/image
    r = requests.post(f"{BASE_URL}/api/generate/image",
                      headers={"Authorization": f"Bearer {video_key}"},
                      json={"prompt": ""}, timeout=30)
    assert r.status_code == 403, f"expected 403 for wrong perm, got {r.status_code}: {r.text[:200]}"

    # Image key -> 400 on empty prompt
    r = requests.post(f"{BASE_URL}/api/generate/image",
                      headers={"Authorization": f"Bearer {image_key}"},
                      json={"prompt": ""}, timeout=30)
    assert r.status_code == 400, f"expected 400 for empty prompt, got {r.status_code}: {r.text[:200]}"
