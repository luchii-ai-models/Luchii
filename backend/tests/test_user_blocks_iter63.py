"""Backend tests for per-user creation blocks (iteration 63)."""
import os
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://import-conflict.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
FRASBERG_KEY = os.environ["FRASBERG_API_KEYS"].split(",")[0]
ADMIN = {"email": "admin.tester@luchiiapp.com", "password": "AdminTest123!"}
BLOCKED_USER = {"email": "blockme@luchii.ai", "password": "Block1234!", "name": "Block Me"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        # try registering
        requests.post(f"{API}/auth/register", json={"email": email, "password": password, "name": email.split("@")[0]}, timeout=20)
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN["email"], ADMIN["password"])


@pytest.fixture(scope="module")
def user_token():
    # Make sure blockme user exists
    requests.post(f"{API}/auth/register", json=BLOCKED_USER, timeout=20)
    return _login(BLOCKED_USER["email"], BLOCKED_USER["password"])


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def user_headers(user_token):
    return {"Authorization": f"Bearer {user_token}"}


# ---------------------- Auth gating ----------------------

def test_user_blocks_requires_admin_user_jwt(user_headers):
    r = requests.put(f"{API}/engines/user-blocks",
                     json={"email": BLOCKED_USER["email"], "kinds": ["image"]},
                     headers=user_headers, timeout=20)
    assert r.status_code == 403, r.text


def test_user_blocks_rejects_frasberg_key():
    r = requests.put(f"{API}/engines/user-blocks",
                     json={"email": BLOCKED_USER["email"], "kinds": ["image"]},
                     headers={"X-Frasberg-Key": FRASBERG_KEY}, timeout=20)
    assert r.status_code == 403, r.text


def test_get_user_blocks_requires_admin(user_headers):
    r = requests.get(f"{API}/engines/user-blocks", headers=user_headers, timeout=20)
    assert r.status_code == 403


# ---------------------- Validation ----------------------

def test_unknown_email_returns_404(admin_headers):
    r = requests.put(f"{API}/engines/user-blocks",
                     json={"email": "nobody-xxx@luchii.ai", "kinds": ["image"]},
                     headers=admin_headers, timeout=20)
    assert r.status_code == 404
    assert "No user with that email" in r.text


def test_invalid_kind_returns_422(admin_headers):
    r = requests.put(f"{API}/engines/user-blocks",
                     json={"email": BLOCKED_USER["email"], "kinds": ["3d"]},
                     headers=admin_headers, timeout=20)
    assert r.status_code == 422


# ---------------------- Save + persistence + non-create preservation ----------------------

def test_save_user_block_case_insensitive_and_preserves_other_actions(admin_headers, user_token):
    # Seed a non-create action in the user's policy directly in DB (API only allows admins to set policy)
    async def _seed():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        u = await db.users.find_one({"email": BLOCKED_USER["email"]})
        owner = f"user:{u['id']}"
        # Insert execute:mind alongside whatever exists
        await db.engine_policy.update_one(
            {"owner": owner},
            {"$addToSet": {"blockedActions": "execute:mind"}, "$setOnInsert": {"owner": owner}},
            upsert=True,
        )
        client.close()
        return u["id"]
    user_id = asyncio.get_event_loop().run_until_complete(_seed())

    # Admin blocks image/video/music using UPPERCASE email -> should match case-insensitively
    r = requests.put(f"{API}/engines/user-blocks",
                     json={"email": BLOCKED_USER["email"].upper(), "kinds": ["image", "video", "music"]},
                     headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == BLOCKED_USER["email"]
    assert set(data["kinds"]) == {"image", "video", "music"}

    # GET user-blocks shows this user
    r = requests.get(f"{API}/engines/user-blocks", headers=admin_headers, timeout=20)
    assert r.status_code == 200
    blocks = r.json()["blocks"]
    row = next((b for b in blocks if b["email"] == BLOCKED_USER["email"]), None)
    assert row, f"user not in blocks list: {blocks}"
    assert set(row["kinds"]) == {"image", "video", "music"}

    # Verify non-create action preserved by querying DB directly
    async def _check():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        pol = await db.engine_policy.find_one({"owner": f"user:{user_id}"})
        client.close()
        return pol["blockedActions"]
    actions = asyncio.get_event_loop().run_until_complete(_check())
    assert "execute:mind" in actions
    assert "create:image" in actions and "create:video" in actions and "create:music" in actions


# ---------------------- Enforcement on generate endpoints (blocked kinds only) ----------------------

def test_blocked_image_jobs_returns_403(user_headers):
    r = requests.post(f"{API}/generate/jobs",
                      json={"prompt": "test block", "mode": "sdxl"},
                      headers=user_headers, timeout=30)
    assert r.status_code == 403, r.text
    assert "Blocked by Frasberg engine rules" in r.text
    assert "create:image" in r.text


def test_blocked_video_returns_403(user_headers):
    r = requests.post(f"{API}/video",
                      json={"prompt": "a short clip"},
                      headers=user_headers, timeout=30)
    assert r.status_code == 403, r.text
    assert "create:video" in r.text


def test_blocked_music_returns_403(user_headers):
    r = requests.post(f"{API}/music",
                      json={"prompt": "lofi beat"},
                      headers=user_headers, timeout=30)
    assert r.status_code == 403, r.text
    assert "create:music" in r.text


# ---------------------- Creations recent includes owner_label ----------------------

def test_creations_recent_owner_label(admin_headers):
    r = requests.get(f"{API}/engines/creations", headers=admin_headers, timeout=20)
    assert r.status_code == 200
    data = r.json()
    assert "recent" in data and len(data["recent"]) > 0
    sample = next((x for x in data["recent"] if x.get("owner_id", "").startswith("user:")), None)
    assert sample, "no user: owner entries in recent"
    assert "owner_label" in sample
    # owner_label should be email, not raw user:<id>
    assert "@" in sample["owner_label"]


# ---------------------- Unblock removes from list ----------------------

def test_unblock_empty_kinds_removes_user(admin_headers, user_token):
    r = requests.put(f"{API}/engines/user-blocks",
                     json={"email": BLOCKED_USER["email"], "kinds": []},
                     headers=admin_headers, timeout=20)
    assert r.status_code == 200
    assert r.json()["kinds"] == []

    r = requests.get(f"{API}/engines/user-blocks", headers=admin_headers, timeout=20)
    assert r.status_code == 200
    emails = {b["email"] for b in r.json()["blocks"]}
    assert BLOCKED_USER["email"] not in emails

    # Non-create action still preserved (checked via DB)
    async def _check():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        u = await db.users.find_one({"email": BLOCKED_USER["email"]})
        pol = await db.engine_policy.find_one({"owner": f"user:{u['id']}"})
        # cleanup: remove execute:mind
        if pol:
            await db.engine_policy.update_one({"owner": f"user:{u['id']}"},
                                              {"$pull": {"blockedActions": "execute:mind"}})
        client.close()
        return pol["blockedActions"] if pol else []
    pol = asyncio.get_event_loop().run_until_complete(_check())
    assert "execute:mind" in pol
    assert not any(a.startswith("create:") for a in pol)


# ---------------------- Teardown: restore block state per request ----------------------

def test_zz_restore_blocked_state(admin_headers):
    """Leave blockme blocked for image/video/music as expected by context."""
    r = requests.put(f"{API}/engines/user-blocks",
                     json={"email": BLOCKED_USER["email"], "kinds": ["image", "video", "music"]},
                     headers=admin_headers, timeout=20)
    assert r.status_code == 200
    # Global governance should remain empty
    r = requests.put(f"{API}/engines/governance",
                     json={"actions": [], "scope": "global"},
                     headers=admin_headers, timeout=20)
    assert r.status_code in (200, 403)
