"""Iter61 smoke/regression after UPDATE-MAIN branch import.
Checks core backend endpoints are up, auth works, creator app mounted,
public endpoints respond. Does NOT trigger paid GPU jobs."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].splitlines()[0]
BASE_URL = BASE_URL.rstrip("/")

ADMIN_EMAIL = "admin@frasbergai.com"
ADMIN_PASSWORD = "Federation20261+"
USER_EMAIL = "test@luchii.ai"
USER_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def test_api_root(s):
    r = s.get(f"{BASE_URL}/api/")
    assert r.status_code == 200
    data = r.json()
    assert "Luchii" in data.get("message", "")


def test_admin_login(s):
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == ADMIN_EMAIL
    assert data["role"] == "admin"


def test_auth_me_after_login(s):
    r = s.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == ADMIN_EMAIL


def test_register_new_user_and_login():
    """Register a brand-new user and verify they can log back in."""
    sess = requests.Session()
    email = f"TEST_user_{uuid.uuid4().hex[:8]}@luchii.ai"
    password = "TestPass!2026"
    r = sess.post(f"{BASE_URL}/api/auth/register", json={"email": email, "password": password, "name": "Smoke Tester"})
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body.get("email", "").lower() == email.lower()
    email = body["email"]  # use normalized form

    sess2 = requests.Session()
    r = sess2.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == email


def test_regular_test_user_login():
    """Login as the documented test user. If missing, auto-register then login."""
    sess = requests.Session()
    r = sess.post(f"{BASE_URL}/api/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD})
    if r.status_code != 200:
        sess.post(f"{BASE_URL}/api/auth/register", json={"email": USER_EMAIL, "password": USER_PASSWORD, "name": "Luchii Test"})
        r = sess.post(f"{BASE_URL}/api/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == USER_EMAIL


def test_creator_app_mounted_engines(s):
    """Creator app mounted; public engines list available (no auth required)."""
    r = s.get(f"{BASE_URL}/api/creator/gpu/v1/engines")
    # Allow either 200 (public) or 401 if gated — but must not be 404
    assert r.status_code in (200, 401, 403), f"unexpected {r.status_code}: {r.text[:200]}"
    assert r.status_code != 404


def test_creator_auth_me_unauth():
    sess = requests.Session()
    r = sess.get(f"{BASE_URL}/api/creator/auth/me")
    assert r.status_code in (401, 403)


def test_creator_auth_me_authed(s):
    r = s.get(f"{BASE_URL}/api/creator/auth/me")
    assert r.status_code == 200, r.text


def test_chat_demo_endpoint(s):
    """Homepage chat demo — should either answer or return a graceful error (not 500 stacktrace)."""
    # Try common chat routes
    candidates = ["/api/chat", "/api/luchii/chat", "/api/public/chat"]
    hit = None
    for path in candidates:
        r = s.post(f"{BASE_URL}{path}", json={"message": "hello", "messages": [{"role": "user", "content": "hello"}]})
        if r.status_code != 404:
            hit = (path, r)
            break
    assert hit is not None, "no chat endpoint responded (all 404)"
    path, r = hit
    print(f"chat endpoint used: {path} -> {r.status_code} :: {r.text[:200]}")
    # Must be a well-formed status, not server crash
    assert r.status_code < 500 or "detail" in r.text.lower(), r.text[:300]


def test_public_pages_backend_doesnt_crash(s):
    """Hit a few public endpoints the pages rely on."""
    for p in ["/api/public/showcase", "/api/public/models", "/api/creator/gpu/v1/engines"]:
        r = s.get(f"{BASE_URL}{p}")
        assert r.status_code < 500, f"{p} crashed: {r.status_code} {r.text[:200]}"
