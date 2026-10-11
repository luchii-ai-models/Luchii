"""Iteration 60 — Engine Runtime (/api/engines/*), Engine Rules enforcement, AWS GPU admin endpoints."""
import os
import time
import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://luchii-av-engine.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin.tester@luchiiapp.com"
ADMIN_PASSWORD = "AdminTest123!"
PLAIN_EMAIL = "plain.user@luchiiapp.com"
PLAIN_PASSWORD = "Plain1234!"

IMAGE_KEY = "frb_live_be3354f25db1ce150f1aee2ec185b5cc53d83cb1"
MUSIC_KEY = "frb_live_a0e8a8fbdce98b51a57bcacd0588604c46585113"

TIMEOUT = 60

_session = requests.Session()
_retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[502, 503, 504],
               allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE"]))
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))


def _get(url, **kw):
    kw.setdefault("timeout", TIMEOUT)
    return _session.get(url, **kw)


def _post(url, **kw):
    kw.setdefault("timeout", TIMEOUT)
    return _session.post(url, **kw)


def _put(url, **kw):
    kw.setdefault("timeout", TIMEOUT)
    return _session.put(url, **kw)


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def admin_token():
    r = _post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    return r.json().get("token")


@pytest.fixture(scope="module")
def plain_token():
    # try login, else register
    r = _post(f"{API}/auth/login", json={"email": PLAIN_EMAIL, "password": PLAIN_PASSWORD})
    if r.status_code != 200:
        r2 = _post(f"{API}/auth/register", json={"email": PLAIN_EMAIL, "password": PLAIN_PASSWORD, "name": "Plain"})
        if r2.status_code in (200, 201):
            return r2.json().get("token")
        r = _post(f"{API}/auth/login", json={"email": PLAIN_EMAIL, "password": PLAIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip("plain login failed")
    return r.json().get("token")


# ---------- Engine Runtime ----------
class TestEngineRuntime:
    def test_runtime_list(self):
        r = _get(f"{API}/engines/runtime")
        assert r.status_code == 200
        d = r.json()
        assert d.get("count") == 44, f"expected 44, got {d.get('count')}"
        engines = d.get("engines", [])
        assert len(engines) == 44
        sample = engines[0]
        for k in ("id", "name", "summary", "builders"):
            assert k in sample, f"missing {k} in {sample}"

    def test_structure_runtime(self):
        r = _get(f"{API}/engines/runtime/structure")
        assert r.status_code == 200
        d = r.json()
        assert "reads" in d and "sample_state" in d

    def test_runtime_unknown_404(self):
        r = _get(f"{API}/engines/runtime/not-a-real-engine")
        assert r.status_code == 404

    def test_structure_execute_deterministic(self):
        s = _get(f"{API}/engines/runtime/structure").json()
        state = s["sample_state"]
        r1 = _post(f"{API}/engines/structure/execute", json={"state": state})
        assert r1.status_code == 200, r1.text[:300]
        d1 = r1.json()
        assert d1.get("coverage") == 1.0
        assert d1.get("evolution", {}).get("evolutionScore") == 1
        out = d1.get("output")
        assert isinstance(out, str) and out.startswith("Structure processed:")
        env = d1.get("envelope", {})
        assert "structureId" in env
        ck1 = env.get("dynamics", {}).get("checksum")
        assert ck1

        r2 = _post(f"{API}/engines/structure/execute", json={"state": state})
        d2 = r2.json()
        ck2 = d2["envelope"]["dynamics"]["checksum"]
        assert ck1 == ck2, "checksum should be deterministic"
        assert d2["envelope"]["structureId"] != env["structureId"], "ids should differ"

    def test_motion_empty_unresolved(self):
        r = _post(f"{API}/engines/motion/execute", json={"state": {}})
        assert r.status_code == 200
        d = r.json()
        assert d.get("coverage", 1) < 1
        unresolved = d.get("unresolved", [])
        assert len(unresolved) > 0
        assert unresolved[0].startswith("state.")

    def test_all_engines_execute(self):
        rt = _get(f"{API}/engines/runtime").json()
        failures = []
        for eng in rt["engines"]:
            eid = eng["id"]
            # empty state
            r_e = _post(f"{API}/engines/{eid}/execute", json={"state": {}})
            if r_e.status_code != 200:
                failures.append((eid, "empty", r_e.status_code, r_e.text[:120]))
                continue
            # sample
            sr = _get(f"{API}/engines/runtime/{eid}")
            if sr.status_code != 200:
                failures.append((eid, "runtime-detail", sr.status_code, sr.text[:120]))
                continue
            sample = sr.json().get("sample_state", {})
            r_s = _post(f"{API}/engines/{eid}/execute", json={"state": sample})
            if r_s.status_code != 200:
                failures.append((eid, "sample", r_s.status_code, r_s.text[:120]))
        assert not failures, f"Engine execute failures: {failures}"

    def test_chain_ok(self):
        r = _post(f"{API}/engines/chain", json={"engines": ["motion", "travel"]})
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        steps = d.get("steps") or d.get("results") or []
        assert len(steps) == 2

    def test_chain_unknown_404(self):
        r = _post(f"{API}/engines/chain", json={"engines": ["motion", "nope-xyz"]})
        assert r.status_code == 404

    def test_chain_too_many_422(self):
        r = _post(f"{API}/engines/chain", json={"engines": ["motion"] * 13})
        assert r.status_code == 422

    def test_chain_state_too_big_413(self):
        big = {"blob": "x" * 70000}
        r = _post(f"{API}/engines/chain", json={"engines": ["motion"], "state": big})
        assert r.status_code == 413


# ---------- Engine Rules ----------
class TestEngineRules:
    def test_rules_shape(self):
        r = _get(f"{API}/engines/rules")
        assert r.status_code == 200
        d = r.json()
        engines = d.get("engines", {})
        # engines may be a dict keyed by id OR a list
        if isinstance(engines, dict):
            items = list(engines.values())
        else:
            items = engines
        assert len(items) == 7, f"expected 7 engines, got {len(items)}"
        ids = {e.get("id") or e.get("engine") for e in items}
        expected = {"image", "video", "music", "voice", "stt", "audio", "game-logic"}
        assert expected.issubset(ids), f"missing ids: {expected - ids}"
        for e in items:
            assert "sections" in e or "rules" in e
        # verify enforcement status per summary
        summary = d.get("summary", [])
        by_id = {s["id"]: s for s in summary}
        # game-logic reference only: 0 enforced
        assert by_id["game-logic"]["enforced"] == 0, by_id["game-logic"]
        # others have at least some enforced rules
        for k in ("image", "video", "music", "voice", "stt", "audio"):
            assert by_id[k]["enforced"] > 0, (k, by_id[k])


# ---------- Rule enforcement on agent tasks ----------
class TestEnforcement:
    def test_image_key_music_denied(self):
        r = _post(
            f"{API}/chat/agents/tasks",
            json={"type": "music", "prompt": "quick test"},
            headers={"X-Frasberg-Key": IMAGE_KEY},
            timeout=25,
        )
        assert r.status_code == 403, r.text[:200]
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text
        assert "music_generation" in detail or "music" in detail.lower()

    def test_image_key_image_ok(self):
        r = _post(
            f"{API}/chat/agents/tasks",
            json={"type": "image", "prompt": "TEST tiny image"},
            headers={"X-Frasberg-Key": IMAGE_KEY},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]

    def test_music_key_default_duration(self):
        import time
        r = _post(
            f"{API}/chat/agents/tasks",
            json={"type": "music", "prompt": "TEST tiny loop"},
            headers={"X-Frasberg-Key": MUSIC_KEY},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        task_id = d.get("id")
        # The task is initially queued with duration=None; backend defaults 15 when the job is created.
        # Poll task until it dispatches (has result.job_id), then GET the music job and check duration.
        job_id = None
        for _ in range(30):
            tr = _get(f"{API}/chat/agents/tasks/{task_id}",
                              headers={"X-Frasberg-Key": MUSIC_KEY})
            if tr.status_code == 200:
                tt = tr.json()
                res = tt.get("result") or {}
                if res.get("job_id"):
                    job_id = res["job_id"]; break
                if tt.get("status") == "failed":
                    break
            time.sleep(2)
        assert job_id, f"music task never dispatched: last={d}"
        jr = _get(f"{API}/jobs/{job_id}", headers={"X-Frasberg-Key": MUSIC_KEY})
        assert jr.status_code == 200, jr.text[:200]
        jd = jr.json()
        assert jd.get("duration") == 15, f"Expected default duration 15, got {jd.get('duration')} in {jd}"

    def test_bundle_empty_include_422(self):
        r = _post(
            f"{API}/chat/agents/bundle",
            json={"idea": "TEST", "include": []},
            headers={"X-Frasberg-Key": IMAGE_KEY},
            timeout=20,
        )
        assert r.status_code == 422, r.text[:200]

    def test_bundle_image_only_ok(self):
        r = _post(
            f"{API}/chat/agents/bundle",
            json={"idea": "TEST tiny", "include": ["image"]},
            headers={"X-Frasberg-Key": IMAGE_KEY},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        tasks = d.get("tasks") or d.get("jobs") or []
        assert len(tasks) == 1, f"Expected 1 task got {len(tasks)}: {str(d)[:300]}"


# ---------- AWS GPU admin ----------
class TestAwsAdmin:
    def test_get_aws_admin(self, admin_token):
        r = _get(f"{API}/gpu-admin/aws", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d.get("configured") is True
        assert "mode" in d and "idle_min" in d and "quota" in d and "quota_request" in d
        assert d["quota"] == 0

    def test_non_admin_forbidden(self, plain_token):
        r = _get(f"{API}/gpu-admin/aws", headers={"Authorization": f"Bearer {plain_token}"})
        assert r.status_code == 403

    def test_put_settings_valid(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = _put(f"{API}/gpu-admin/aws/settings", json={"mode": "on_demand"}, headers=h)
        assert r.status_code == 200, r.text[:200]
        r = _put(f"{API}/gpu-admin/aws/settings", json={"idle_min": 30}, headers=h)
        assert r.status_code == 200, r.text[:200]

    def test_put_settings_invalid(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = _put(f"{API}/gpu-admin/aws/settings", json={"idle_min": 7}, headers=h)
        assert r.status_code == 422
        r = _put(f"{API}/gpu-admin/aws/settings", json={"mode": "nope"}, headers=h)
        assert r.status_code == 422

    def test_restore_defaults(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = _put(f"{API}/gpu-admin/aws/settings", json={"mode": "always_on", "idle_min": 20}, headers=h)
        assert r.status_code == 200

    def test_usage_current(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = _get(f"{API}/gpu-admin/aws/usage", headers=h)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        for k in ("month", "hours", "compute_usd", "storage_usd", "total_usd", "projected_usd", "daily"):
            assert k in d, f"missing {k}"
        assert isinstance(d["daily"], list)

    def test_usage_invalid_month(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = _get(f"{API}/gpu-admin/aws/usage", params={"month": "2026-13"}, headers=h)
        assert r.status_code == 422

    def test_usage_future_month_null_projected(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = _get(f"{API}/gpu-admin/aws/usage", params={"month": "2026-09"}, headers=h)
        assert r.status_code == 200
        assert r.json().get("projected_usd") is None
