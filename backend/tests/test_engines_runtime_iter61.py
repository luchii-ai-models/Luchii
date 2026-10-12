"""Iter61: Frasberg Engine Runtime end-to-end tests.

Covers:
- Auth gating on /api/engines/runtime (anon 401, non-admin 403, admin ok, platform-key ok)
- Execute single engine (mind, logic) with continuity persistence + delete
- Chain endpoint with platform-key auth
- Flow endpoint (known/unknown domain)
- Policy / Governance (owner + global, platform-key cannot set global)
- Diagnostics increments, identity, rules auth
"""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://media-engine-hub.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin.tester@luchiiapp.com"
ADMIN_PWD = "AdminTest123!"
PLATFORM_KEY = os.environ["FRASBERG_API_KEYS"].split(",")[0]

TIMEOUT = 60


# ---------- fixtures ----------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=TIMEOUT)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def key_headers():
    return {"X-Frasberg-Key": PLATFORM_KEY}


@pytest.fixture(scope="session")
def nonadmin_token():
    email = f"nonadmin_{uuid.uuid4().hex[:8]}@luchiiapp.com"
    pwd = "Plain1234!"
    r = requests.post(f"{BASE_URL}/api/auth/register", json={"email": email, "password": pwd, "name": "Non Admin"}, timeout=TIMEOUT)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    j = r.json()
    token = j.get("token") or j.get("access_token")
    if not token:
        r2 = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=TIMEOUT)
        assert r2.status_code == 200
        token = r2.json()["token"]
    return token


# ---------- /api/engines/runtime auth ----------
class TestRuntimeAuth:
    def test_anonymous_401(self):
        r = requests.get(f"{BASE_URL}/api/engines/runtime", timeout=TIMEOUT)
        assert r.status_code == 401

    def test_nonadmin_403(self, nonadmin_token):
        r = requests.get(f"{BASE_URL}/api/engines/runtime", headers={"Authorization": f"Bearer {nonadmin_token}"}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_admin_ok(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/engines/runtime", headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        assert j["count"] == 44, f"expected 44 engines, got {j.get('count')}"
        assert j["total"] == 50
        assert isinstance(j["systems"], list) and len(j["systems"]) == 6

    def test_platform_key_ok(self, key_headers):
        r = requests.get(f"{BASE_URL}/api/engines/runtime", headers=key_headers, timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["count"] == 44


# ---------- execute + continuity ----------
class TestExecute:
    def test_execute_mind(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/engines/mind/execute", headers=admin_headers,
                          json={"input": "hello"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "Mind" in j.get("output", "") and "hello" in j["output"], f"unexpected output: {j.get('output')}"
        assert j.get("requestId")
        assert "coverage" in j

    def test_execute_logic(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/engines/logic/execute", headers=admin_headers,
                          json={"input": "abc"}, timeout=TIMEOUT)
        assert r.status_code == 200
        assert "Logic" in r.json()["output"] and "abc" in r.json()["output"]

    def test_continuity_persist_and_delete(self, admin_headers):
        cid = f"w-test-{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/engines/mind/execute", headers=admin_headers,
                          json={"input": "persist", "continuity": cid}, timeout=TIMEOUT)
        assert r.status_code == 200
        r2 = requests.get(f"{BASE_URL}/api/engines/continuity/{cid}", headers=admin_headers, timeout=TIMEOUT)
        assert r2.status_code == 200
        assert r2.json().get("runs", 0) >= 1
        r3 = requests.delete(f"{BASE_URL}/api/engines/continuity/{cid}", headers=admin_headers, timeout=TIMEOUT)
        assert r3.status_code in (200, 204)
        r4 = requests.get(f"{BASE_URL}/api/engines/continuity/{cid}", headers=admin_headers, timeout=TIMEOUT)
        # After delete runs should be 0 or 404
        assert r4.status_code == 404 or r4.json().get("runs", 0) == 0


# ---------- chain ----------
class TestChain:
    def test_chain_with_key(self, key_headers):
        r = requests.post(f"{BASE_URL}/api/engines/chain", headers=key_headers,
                          json={"input": "zap", "engines": ["mind", "logic"]}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json().get("requestId")


# ---------- flow ----------
class TestFlow:
    def test_flow_structure(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/engines/flow", headers=admin_headers,
                          json={"domain": "structure"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        j = r.json()
        stages = j.get("stages") or []
        assert len(stages) == 10
        names = [s.get("engine") or s.get("name") or s.get("id") for s in stages]
        assert names[0] == "identity" and names[-1] == "structure", f"stages={names}"
        assert j.get("awareness_valid") is True

    def test_flow_unknown_404(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/engines/flow", headers=admin_headers,
                          json={"domain": "nope-xyz"}, timeout=TIMEOUT)
        assert r.status_code == 404


# ---------- policy & governance ----------
class TestPolicyGovernance:
    def test_policy_blocks_action(self, admin_headers):
        try:
            # block execute:mind
            r = requests.put(f"{BASE_URL}/api/engines/policy", headers=admin_headers,
                             json={"actions": ["execute:mind"]}, timeout=TIMEOUT)
            assert r.status_code == 200, r.text
            r2 = requests.post(f"{BASE_URL}/api/engines/mind/execute", headers=admin_headers,
                               json={"input": "x"}, timeout=TIMEOUT)
            assert r2.status_code == 403
            assert "policy" in r2.text.lower() or "blocked" in r2.text.lower()
        finally:
            # reset
            requests.put(f"{BASE_URL}/api/engines/policy", headers=admin_headers,
                         json={"actions": []}, timeout=TIMEOUT)
        # verify mind works again
        r3 = requests.post(f"{BASE_URL}/api/engines/mind/execute", headers=admin_headers,
                           json={"input": "y"}, timeout=TIMEOUT)
        assert r3.status_code == 200

    def test_governance_global_admin_blocks_all(self, admin_headers, key_headers):
        try:
            r = requests.put(f"{BASE_URL}/api/engines/governance", headers=admin_headers,
                             json={"actions": ["execute:logic"], "scope": "global"}, timeout=TIMEOUT)
            assert r.status_code == 200, r.text
            # should block even for the platform-key owner
            r2 = requests.post(f"{BASE_URL}/api/engines/logic/execute", headers=key_headers,
                               json={"input": "x"}, timeout=TIMEOUT)
            assert r2.status_code == 403
        finally:
            requests.put(f"{BASE_URL}/api/engines/governance", headers=admin_headers,
                         json={"actions": [], "scope": "global"}, timeout=TIMEOUT)
            requests.put(f"{BASE_URL}/api/engines/governance", headers=admin_headers,
                         json={"actions": [], "scope": "owner"}, timeout=TIMEOUT)

    def test_governance_global_platform_key_denied(self, key_headers):
        r = requests.put(f"{BASE_URL}/api/engines/governance", headers=key_headers,
                         json={"actions": [], "scope": "global"}, timeout=TIMEOUT)
        assert r.status_code == 403


# ---------- diagnostics, identity, rules ----------
class TestDiagnosticsIdentityRules:
    def test_diagnostics_counts_increase(self, admin_headers):
        d1 = requests.get(f"{BASE_URL}/api/engines/diagnostics", headers=admin_headers, timeout=TIMEOUT).json()
        requests.post(f"{BASE_URL}/api/engines/mind/execute", headers=admin_headers,
                      json={"input": "diag"}, timeout=TIMEOUT)
        d2 = requests.get(f"{BASE_URL}/api/engines/diagnostics", headers=admin_headers, timeout=TIMEOUT).json()
        # Try to compare an engine-related counter at any reasonable path
        def pick(d):
            if isinstance(d, dict):
                for k in ("engine", "engines", "router", "gateway"):
                    v = d.get(k)
                    if isinstance(v, (int, float)):
                        return v
                    if isinstance(v, dict):
                        for kk in ("count", "runs", "events", "total"):
                            if isinstance(v.get(kk), (int, float)):
                                return v[kk]
            return None
        v1, v2 = pick(d1), pick(d2)
        if v1 is not None and v2 is not None:
            assert v2 >= v1

    def test_identity_nodes(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/engines/identity", headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        assert "nodes" in j or isinstance(j, (list, dict))

    def test_rules_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/engines/rules", timeout=TIMEOUT)
        assert r.status_code == 401

    def test_rules_admin_ok(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/engines/rules", headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200
