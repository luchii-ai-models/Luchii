"""Iter62: GPU Quota Alert banner + Engines in Creation (image/video/music/upscale) governance.

Order:
1. Quota banner tests (simulation already in Mongo: quota=8, approved, dismissed=false)
2. Creation governance: block create:image/video/music globally, verify 403, then reset
3. /api/engines/creations stats + auth
4. Quota check (removes simulation) -- RUN LAST
"""
import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin.tester@luchiiapp.com"
ADMIN_PWD = "AdminTest123!"
PLATFORM_KEY = os.environ["FRASBERG_API_KEYS"].split(",")[0]
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TIMEOUT = 60


# ---------- fixtures ----------
@pytest.fixture(scope="session")
def admin_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def key_headers():
    return {"X-Frasberg-Key": PLATFORM_KEY}


@pytest.fixture(scope="session")
def mongo_aws():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]["aws_gpu"]
    client.close()


def _reset_simulation(coll):
    coll.update_one({"name": "frasberg-gpu-b24aea"},
                    {"$set": {"quota_alert_dismissed": False}})


# ---------- 1. Quota banner (GPU Quota Alert) ----------
class TestQuotaBanner:
    def test_overview_quota_alert_true(self, admin_headers, mongo_aws):
        _reset_simulation(mongo_aws)
        r = requests.get(f"{BASE_URL}/api/gpu-admin/aws", headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("configured") is True
        assert j.get("quota") == 8, f"expected simulated quota=8, got {j.get('quota')}"
        assert j.get("quota_needed") is not None and isinstance(j["quota_needed"], int)
        assert j.get("quota_approved_at"), "quota_approved_at should be set"
        assert j.get("quota_alert") is True, f"quota_alert must be true while on_demand+approved+not dismissed; mode={j.get('mode')}, dismissed-flag not reflected"
        assert j.get("mode") == "on_demand"

    def test_dismiss_hides_alert(self, admin_headers, mongo_aws):
        _reset_simulation(mongo_aws)
        r = requests.post(f"{BASE_URL}/api/gpu-admin/aws/quota/dismiss",
                          headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json().get("dismissed") is True
        r2 = requests.get(f"{BASE_URL}/api/gpu-admin/aws", headers=admin_headers, timeout=TIMEOUT)
        assert r2.status_code == 200
        assert r2.json().get("quota_alert") is False
        # restore for next test
        _reset_simulation(mongo_aws)
        r3 = requests.get(f"{BASE_URL}/api/gpu-admin/aws", headers=admin_headers, timeout=TIMEOUT)
        assert r3.json().get("quota_alert") is True


# ---------- 2. Engines in Creation: governance blocks ----------
BLOCKED_PREFIX = "Blocked by Frasberg engine rules"


class TestCreationGovernance:
    @pytest.fixture(autouse=True)
    def _block_global(self, admin_headers):
        # SET global governance to block create:*
        r = requests.put(f"{BASE_URL}/api/engines/governance", headers=admin_headers,
                         json={"actions": ["create:image", "create:video", "create:music"],
                               "scope": "global"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        yield
        # ALWAYS reset
        requests.put(f"{BASE_URL}/api/engines/governance", headers=admin_headers,
                     json={"actions": [], "scope": "global"}, timeout=TIMEOUT)

    def _assert_blocked(self, r):
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"
        detail = r.json().get("detail", "")
        assert detail.startswith(BLOCKED_PREFIX), f"unexpected detail: {detail}"

    def test_generate_jobs_blocked(self):
        r = requests.post(f"{BASE_URL}/api/generate/jobs", json={"prompt": "x"}, timeout=TIMEOUT)
        self._assert_blocked(r)

    def test_video_blocked(self):
        r = requests.post(f"{BASE_URL}/api/video", json={"prompt": "x"}, timeout=TIMEOUT)
        self._assert_blocked(r)

    def test_music_blocked(self):
        r = requests.post(f"{BASE_URL}/api/music", json={"prompt": "x"}, timeout=TIMEOUT)
        self._assert_blocked(r)

    def test_generate_blocked(self):
        r = requests.post(f"{BASE_URL}/api/generate", json={"prompt": "x"}, timeout=TIMEOUT)
        self._assert_blocked(r)

    def test_upscale_jobs_blocked(self):
        # upscale_jobs requires image_base64 in UpscaleIn; use a 1x1 PNG placeholder
        tiny = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
                "nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=")
        r = requests.post(f"{BASE_URL}/api/upscale/jobs",
                          json={"prompt": "x", "image_base64": tiny}, timeout=TIMEOUT)
        self._assert_blocked(r)


# ---------- 3. /api/engines/creations stats + auth ----------
class TestEnginesCreationsEndpoint:
    def test_requires_admin_not_key(self, key_headers):
        r = requests.get(f"{BASE_URL}/api/engines/creations",
                         headers=key_headers, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_admin_ok_with_counts(self, admin_headers):
        # snapshot before
        r0 = requests.get(f"{BASE_URL}/api/engines/creations",
                          headers=admin_headers, timeout=TIMEOUT)
        assert r0.status_code == 200, r0.text
        j0 = r0.json()
        assert "kinds" in j0
        for k in ("image", "video", "music"):
            assert k in j0["kinds"], f"missing kind {k}"
            assert "checked" in j0["kinds"][k]
            assert "blocked" in j0["kinds"][k]
        before = {k: (j0["kinds"][k]["checked"], j0["kinds"][k]["blocked"]) for k in ("image", "video", "music")}

        # trigger blocks: set global block
        requests.put(f"{BASE_URL}/api/engines/governance", headers=admin_headers,
                     json={"actions": ["create:image", "create:video", "create:music"],
                           "scope": "global"}, timeout=TIMEOUT)
        try:
            requests.post(f"{BASE_URL}/api/generate/jobs", json={"prompt": "stat"}, timeout=TIMEOUT)
            requests.post(f"{BASE_URL}/api/video", json={"prompt": "stat"}, timeout=TIMEOUT)
            requests.post(f"{BASE_URL}/api/music", json={"prompt": "stat"}, timeout=TIMEOUT)
            time.sleep(1)
            r1 = requests.get(f"{BASE_URL}/api/engines/creations",
                              headers=admin_headers, timeout=TIMEOUT)
            assert r1.status_code == 200
            j1 = r1.json()
            for k in ("image", "video", "music"):
                ck, bk = j1["kinds"][k]["checked"], j1["kinds"][k]["blocked"]
                assert ck > before[k][0], f"{k} checked did not increase ({before[k][0]} -> {ck})"
                assert bk > before[k][1], f"{k} blocked did not increase ({before[k][1]} -> {bk})"
            # recent should be a list
            recent = j1.get("recent") or j1.get("kinds", {}).get("image", {}).get("recent")
            assert recent is not None, f"no recent list in response: keys={list(j1.keys())}"
        finally:
            requests.put(f"{BASE_URL}/api/engines/governance", headers=admin_headers,
                         json={"actions": [], "scope": "global"}, timeout=TIMEOUT)


# ---------- 4. quota/check — removes the simulation (RUN LAST) ----------
class TestZZZQuotaCheckRemovesSimulation:
    """Named ZZZ so pytest default order runs this after the others."""

    def test_quota_check_wipes_approval(self, admin_headers, mongo_aws):
        _reset_simulation(mongo_aws)
        r = requests.post(f"{BASE_URL}/api/gpu-admin/aws/quota/check",
                          headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        # Real AWS quota is 0
        assert j.get("quota") == 0, f"after real check, quota should be 0; got {j.get('quota')}"
        assert j.get("quota_approved_at") in (None, ""), f"quota_approved_at should be nulled; got {j.get('quota_approved_at')}"
        assert j.get("quota_alert") is False
