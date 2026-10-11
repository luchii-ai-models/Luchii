"""Iteration-2 tests: Luchii Painter-X remix job, gallery DELETE, models page images."""
import os
import uuid
import base64
import time
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "admin.tester@luchiiapp.com"
ADMIN_PASSWORD = "AdminTest2026!"

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
def user_a():
    email = f"TEST_a_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": "TestPass2026!", "name": "User A"}, timeout=20)
    assert r.status_code in (200, 201), r.text
    return {"email": email, "token": r.json()["token"], "id": r.json().get("user", {}).get("id") or r.json().get("id")}


@pytest.fixture(scope="module")
def user_b():
    email = f"TEST_b_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": "TestPass2026!", "name": "User B"}, timeout=20)
    assert r.status_code in (200, 201), r.text
    return {"email": email, "token": r.json()["token"], "id": r.json().get("user", {}).get("id") or r.json().get("id")}


def _me_id(token):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if r.status_code == 200:
        d = r.json()
        return d.get("id") or d.get("user", {}).get("id")
    return None


# ------------------- Gallery DELETE -------------------
class TestGalleryDelete:
    def test_unauth_delete_401(self):
        r = requests.delete(f"{BASE_URL}/api/generations/does-not-exist", timeout=10)
        assert r.status_code in (401, 403), f"got {r.status_code}"

    def test_delete_unknown_id_404(self, user_a):
        r = requests.delete(f"{BASE_URL}/api/generations/TEST_unknown_{uuid.uuid4().hex[:6]}",
                            headers={"Authorization": f"Bearer {user_a['token']}"}, timeout=10)
        assert r.status_code == 404

    def test_delete_owned_200(self, mongo, user_a):
        uid = _me_id(user_a["token"]) or user_a.get("id")
        assert uid, "could not resolve user id"
        gid = f"TEST_del_{uuid.uuid4().hex[:8]}"
        mongo.generations.insert_one({
            "id": gid, "kind": "generate", "prompt": "test del", "style": "photoreal",
            "model": "Luchii Nova-Muse", "image_base64": TINY_JPEG_B64,
            "created_at": datetime.now(timezone.utc).isoformat(), "user_id": uid, "public": False
        })
        r = requests.delete(f"{BASE_URL}/api/generations/{gid}",
                            headers={"Authorization": f"Bearer {user_a['token']}"}, timeout=10)
        assert r.status_code == 200, r.text
        assert mongo.generations.find_one({"id": gid}) is None

    def test_delete_other_users_404(self, mongo, user_a, user_b):
        uid_a = _me_id(user_a["token"]) or user_a.get("id")
        gid = f"TEST_other_{uuid.uuid4().hex[:8]}"
        mongo.generations.insert_one({
            "id": gid, "kind": "generate", "prompt": "someone else", "style": "photoreal",
            "model": "Luchii Nova-Muse", "image_base64": TINY_JPEG_B64,
            "created_at": datetime.now(timezone.utc).isoformat(), "user_id": uid_a, "public": False
        })
        r = requests.delete(f"{BASE_URL}/api/generations/{gid}",
                            headers={"Authorization": f"Bearer {user_b['token']}"}, timeout=10)
        assert r.status_code == 404
        # still exists
        assert mongo.generations.find_one({"id": gid}) is not None
        mongo.generations.delete_one({"id": gid})


# ------------------- Public gallery regression -------------------
class TestPublicGalleryRegression:
    def test_public_gallery_ok(self):
        r = requests.get(f"{BASE_URL}/api/gallery/public", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ------------------- Remix (single job) -------------------
@pytest.mark.remix
class TestRemixPainterX:
    def test_remix_golden_hour(self, user_a):
        with open("/app/frontend/public/showcase/golden-hour.jpg", "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        data_url = f"data:image/jpeg;base64,{img_b64}"
        r = requests.post(f"{BASE_URL}/api/edit/jobs",
                          json={"prompt": "turn her hair bright silver, keep face identical, cinematic key light",
                                "image_base64": data_url, "style": None},
                          headers={"Authorization": f"Bearer {user_a['token']}"}, timeout=30)
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]
        assert r.json()["status"] in ("queued", "running")

        # Poll up to 8 min
        deadline = time.time() + 8 * 60
        last_status = None
        while time.time() < deadline:
            s = requests.get(f"{BASE_URL}/api/image-jobs/{job_id}", timeout=20)
            assert s.status_code == 200
            body = s.json()
            last_status = body["status"]
            if last_status == "completed":
                break
            if last_status == "failed":
                pytest.fail(f"job failed: {body.get('error')}")
            time.sleep(10)
        assert last_status == "completed", f"timed out, last_status={last_status}"
        body = s.json()
        res = body["result"]
        assert res["model"] == "Luchii Painter-X"
        img_data = res["image_base64"]
        assert img_data and img_data.startswith("data:image/")
        # decode and inspect size
        raw = base64.b64decode(img_data.split(",", 1)[1])
        try:
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(raw))
            long_edge = max(im.size)
            print(f"remix result size: {im.size}, format={im.format}")
            assert long_edge >= 1500, f"long edge {long_edge} < 1500 (want sharp HD)"
            assert im.format in ("JPEG", "JPG")
        except ImportError:
            # fallback: just ensure meaningful bytes
            assert len(raw) > 100_000, f"only {len(raw)} bytes, unlikely HD"
