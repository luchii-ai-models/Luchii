"""Tests for public gallery + admin publish-recent endpoints."""
import os
import uuid
import base64
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback - read from frontend .env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "admin.tester@luchiiapp.com"
ADMIN_PASSWORD = "AdminTest2026!"

# 1x1 jpeg
TINY_JPEG_B64 = (
    "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgG"
    "BgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQ"
    "EBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCAABAAEDASIAAhEB"
    "AxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAA"
    "AAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AL+AH//Z"
)


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return r.json().get("token")


@pytest.fixture(scope="module")
def user_token():
    email = f"TEST_user_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": "TestPass2026!", "name": "Test User"}, timeout=15)
    if r.status_code not in (200, 201):
        pytest.skip(f"User register failed: {r.status_code} {r.text}")
    return r.json().get("token")


@pytest.fixture
def seeded_generations(mongo):
    """Insert 2 recent (last 30 min) and 1 old (3 h ago) generations. Clean up after."""
    recent_ids = [f"TEST_recent_{uuid.uuid4().hex[:8]}" for _ in range(2)]
    old_id = f"TEST_old_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    docs = [
        {"id": recent_ids[0], "kind": "generate", "prompt": "recent one",
         "style": "photoreal", "image_base64": TINY_JPEG_B64,
         "created_at": now.isoformat(), "public": False},
        {"id": recent_ids[1], "kind": "generate", "prompt": "recent two",
         "style": "cinematic", "image_base64": TINY_JPEG_B64,
         "created_at": (now - timedelta(minutes=30)).isoformat(), "public": False},
        {"id": old_id, "kind": "generate", "prompt": "old one",
         "style": "photoreal", "image_base64": TINY_JPEG_B64,
         "created_at": (now - timedelta(hours=3)).isoformat(), "public": False},
    ]
    mongo.generations.insert_many(docs)
    yield {"recent": recent_ids, "old": old_id}
    mongo.generations.delete_many({"id": {"$in": recent_ids + [old_id]}})


# ---------- public gallery ----------
class TestPublicGallery:
    def test_public_gallery_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/gallery/public", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        for item in data:
            assert item.get("public") is True or "public" not in item  # endpoint filters public:true
            assert "_id" not in item

    def test_public_gallery_newest_first(self, mongo, seeded_generations):
        # Mark one recent as public manually
        mongo.generations.update_one(
            {"id": seeded_generations["recent"][0]},
            {"$set": {"public": True, "published_at": datetime.now(timezone.utc).isoformat()}})
        r = requests.get(f"{BASE_URL}/api/gallery/public", timeout=15)
        assert r.status_code == 200
        data = r.json()
        ids = [d["id"] for d in data]
        assert seeded_generations["recent"][0] in ids
        # Sorted desc by created_at
        timestamps = [d["created_at"] for d in data if "created_at" in d]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------- admin publish-recent ----------
class TestAdminPublishRecent:
    def test_no_auth_rejected(self):
        r = requests.post(f"{BASE_URL}/api/admin/gallery/publish-recent?hours=2", timeout=15)
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"

    def test_non_admin_rejected(self, user_token):
        r = requests.post(f"{BASE_URL}/api/admin/gallery/publish-recent?hours=2",
                          headers={"Authorization": f"Bearer {user_token}"}, timeout=15)
        assert r.status_code == 403, f"Expected 403, got {r.status_code} {r.text}"

    def test_publish_recent_marks_recent_only(self, admin_token, mongo, seeded_generations):
        r = requests.post(f"{BASE_URL}/api/admin/gallery/publish-recent?hours=2",
                          headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        body = r.json()
        assert "published" in body
        assert body["published"] >= 2  # at least our 2 recents

        # Verify recents are public
        for rid in seeded_generations["recent"]:
            doc = mongo.generations.find_one({"id": rid})
            assert doc["public"] is True, f"recent {rid} should be public"

        # Old should remain private
        old = mongo.generations.find_one({"id": seeded_generations["old"]})
        assert old["public"] is False, "old doc should not have been published"

        # Verify they show in public gallery
        rr = requests.get(f"{BASE_URL}/api/gallery/public?limit=120", timeout=15)
        ids = [d["id"] for d in rr.json()]
        for rid in seeded_generations["recent"]:
            assert rid in ids
        assert seeded_generations["old"] not in ids
