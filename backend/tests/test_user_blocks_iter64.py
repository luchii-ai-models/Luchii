"""Backend tests for timed per-user creation blocks (iteration 64)."""
import os
import asyncio
import re
from datetime import datetime, timezone, timedelta
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin.tester@luchiiapp.com", "password": "AdminTest123!"}
USER = {"email": "blockme@luchii.ai", "password": "Block1234!", "name": "Block Me"}


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        requests.post(f"{API}/auth/register", json={"email": email, "password": password, "name": email.split("@")[0]}, timeout=20)
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN['email'], ADMIN['password'])}"}


@pytest.fixture(scope="module")
def user_h():
    requests.post(f"{API}/auth/register", json=USER, timeout=20)
    return {"Authorization": f"Bearer {_login(USER['email'], USER['password'])}"}


def _put(h, **body):
    return requests.put(f"{API}/engines/user-blocks", json=body, headers=h, timeout=20)


def _get_row(h, email):
    r = requests.get(f"{API}/engines/user-blocks", headers=h, timeout=20)
    assert r.status_code == 200
    return next((b for b in r.json()["blocks"] if b["email"] == email), None)


def _parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------- duration tests ----------------

def test_duration_24h_sets_expiry_near_24h(admin_h):
    r = _put(admin_h, email=USER["email"], kinds=["image", "video", "music"], duration="24h")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["expires_at"] is not None
    exp = _parse_iso(data["expires_at"])
    delta = exp - datetime.now(timezone.utc)
    assert timedelta(hours=23, minutes=55) < delta < timedelta(hours=24, minutes=5), f"delta={delta}"

    row = _get_row(admin_h, USER["email"])
    assert row and row["expires_at"] == data["expires_at"]


def test_duration_7d_sets_expiry_near_7d(admin_h):
    r = _put(admin_h, email=USER["email"], kinds=["image", "video", "music"], duration="7d")
    assert r.status_code == 200, r.text
    exp = _parse_iso(r.json()["expires_at"])
    delta = exp - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23, minutes=55) < delta < timedelta(days=7, minutes=5)


def test_duration_keep_preserves_expiry_while_changing_kinds(admin_h):
    # Setup: start with 7d expiry
    r = _put(admin_h, email=USER["email"], kinds=["image", "video", "music"], duration="7d")
    original = r.json()["expires_at"]
    assert original

    # Toggle a kind off using 'keep' -> expires_at unchanged
    r = _put(admin_h, email=USER["email"], kinds=["image", "video"], duration="keep")
    assert r.status_code == 200
    assert r.json()["expires_at"] == original
    assert set(r.json()["kinds"]) == {"image", "video"}

    # Toggle it back on with 'keep'
    r = _put(admin_h, email=USER["email"], kinds=["image", "video", "music"], duration="keep")
    assert r.status_code == 200
    assert r.json()["expires_at"] == original


def test_duration_null_is_permanent(admin_h):
    r = _put(admin_h, email=USER["email"], kinds=["image", "video", "music"], duration=None)
    assert r.status_code == 200
    assert r.json()["expires_at"] is None
    row = _get_row(admin_h, USER["email"])
    assert row and row["expires_at"] is None


def test_invalid_duration_returns_422(admin_h):
    r = _put(admin_h, email=USER["email"], kinds=["image"], duration="48h")
    assert r.status_code == 422, r.text


def test_empty_kinds_unblocks_and_clears_expiry(admin_h):
    # Set a 24h expiry
    _put(admin_h, email=USER["email"], kinds=["image"], duration="24h")
    # Unblock
    r = _put(admin_h, email=USER["email"], kinds=[], duration="24h")  # duration ignored when kinds empty
    assert r.status_code == 200
    assert r.json()["kinds"] == []
    assert r.json()["expires_at"] is None

    row = _get_row(admin_h, USER["email"])
    assert row is None, "user still listed after unblock"


# ---------------- enforcement with timed message ----------------

def test_blocked_video_403_message_includes_date_and_kind(admin_h, user_h):
    r = _put(admin_h, email=USER["email"], kinds=["image", "video", "music"], duration="7d")
    assert r.status_code == 200
    exp_prefix = r.json()["expires_at"][:16].replace("T", " ")  # YYYY-MM-DD HH:MM

    r = requests.post(f"{API}/video", json={"prompt": "test"}, headers=user_h, timeout=30)
    assert r.status_code == 403, r.text
    detail = r.json().get("detail", "")
    assert "Blocked by Frasberg engine rules" in detail
    assert "Action blocked by policy until" in detail
    assert exp_prefix in detail, f"expected {exp_prefix!r} in {detail!r}"
    assert "UTC" in detail
    assert "(create:video)" in detail


# ---------------- auto-lift via past expires_at in DB ----------------

def test_auto_lift_when_expires_at_in_past(admin_h):
    # Ensure user has an active block
    _put(admin_h, email=USER["email"], kinds=["image", "video", "music"], duration="7d")

    async def _set_past():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        u = await db.users.find_one({"email": USER["email"]})
        owner = f"user:{u['id']}"
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await db.engine_policy.update_one({"owner": owner}, {"$set": {"creation_block_until": past}})
        client.close()
        return owner

    owner = asyncio.new_event_loop().run_until_complete(_set_past())

    # GET /engines/user-blocks should no longer list the user (triggers load_policy -> auto-lift)
    r = requests.get(f"{API}/engines/user-blocks", headers=admin_h, timeout=20)
    assert r.status_code == 200
    emails = {b["email"] for b in r.json()["blocks"]}
    assert USER["email"] not in emails, f"user still listed after expiry: {r.json()['blocks']}"

    # Verify DB: no create:* in blockedActions, creation_block_until null
    async def _check():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        pol = await db.engine_policy.find_one({"owner": owner})
        client.close()
        return pol
    pol = asyncio.new_event_loop().run_until_complete(_check())
    assert pol is not None
    assert not any(a.startswith("create:") for a in pol.get("blockedActions", [])), pol
    assert pol.get("creation_block_until") is None, pol


# ---------------- teardown: restore to blocked image/video/music for 7d ----------------

def test_zz_restore_state(admin_h):
    r = _put(admin_h, email=USER["email"], kinds=["image", "video", "music"], duration="7d")
    assert r.status_code == 200
    assert set(r.json()["kinds"]) == {"image", "video", "music"}
    assert r.json()["expires_at"] is not None
