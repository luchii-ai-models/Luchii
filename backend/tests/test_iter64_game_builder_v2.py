"""Iter64: Frasberg Game Builder v2 - server status, shareable pages, new engine settings
(race laps/lapLength, police aggression, maze themes). Upstream api.frasberg.com is blocked
by Cloudflare 403 -> offline-state responses are EXPECTED (not a bug).
"""
import os
import pytest
import requests


def _url():
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _url()
USER_EMAIL = "test@luchii.ai"
USER_PASS = "Test1234!"


@pytest.fixture(scope="session")
def anon():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def user(anon):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": USER_EMAIL, "password": USER_PASS})
    if r.status_code != 200:
        s.post(f"{BASE_URL}/api/auth/register", json={"email": USER_EMAIL, "password": USER_PASS, "name": "Test"})
        r = s.post(f"{BASE_URL}/api/auth/login", json={"email": USER_EMAIL, "password": USER_PASS})
    assert r.status_code == 200, r.text
    return s


# ---------------- Frasberg status (public, upstream is really offline)
class TestFrasbergStatus:
    def test_status_public_and_offline(self, anon):
        r = anon.get(f"{BASE_URL}/api/game-builder/frasberg-status")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("reachable") is False
        assert d.get("host") == "api.frasberg.com"
        assert d.get("status") == 403
        assert "403" in (d.get("detail") or "")
        assert "cloudflare" in (d.get("detail") or "").lower()

    def test_status_refresh_reprobes(self, anon):
        r = anon.get(f"{BASE_URL}/api/game-builder/frasberg-status?refresh=1")
        assert r.status_code == 200
        d = r.json()
        assert d.get("checked_at") is not None
        assert d.get("reachable") is False


# ---------------- Engines catalog: new tunables
class TestEngineTunables:
    @pytest.fixture(scope="class")
    def engines(self):
        r = requests.get(f"{BASE_URL}/api/game-builder/engines")
        assert r.status_code == 200, r.text
        return {e["id"]: e for e in r.json()["engines"]}

    def test_racer_laps_and_lapLength(self, engines):
        r = engines["racer3d"]
        tun = {t["key"]: t for t in r["tunables"]}
        assert "laps" in tun and tun["laps"]["min"] == 0 and tun["laps"]["max"] == 20
        assert "lapLength" in tun and tun["lapLength"]["min"] == 1000 and tun["lapLength"]["max"] == 10000

    def test_streets_and_carjack_police(self, engines):
        for eid in ("streets", "carjack"):
            tun = {t["key"]: t for t in engines[eid]["tunables"]}
            assert "policeAggression" in tun
            assert tun["policeAggression"]["min"] == 0.25
            assert tun["policeAggression"]["max"] == 2.5

    def test_maze_theme_select(self, engines):
        tun = {t["key"]: t for t in engines["maze3d"]["tunables"]}
        assert "mazeTheme" in tun
        t = tun["mazeTheme"]
        assert t["type"] == "select"
        assert set(t["options"]) >= {"neon", "ice", "lava", "jungle", "crypt", "desert", "gold"}


# ---------------- Prompt rules
class TestPromptRules:
    created_ids = []

    def _create(self, s, prompt, engine=None):
        payload = {"prompt": prompt}
        if engine:
            payload["engine"] = engine
        r = s.post(f"{BASE_URL}/api/game-builder/worlds", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        TestPromptRules.created_ids.append(d["id"])
        return d

    def test_racer_5_laps(self, user):
        d = self._create(user, "A neon night race with 5 laps")
        assert d["engine"] == "racer3d"
        assert d["config"]["laps"] == 5
        rr = d["world"].get("raceRuleset")
        assert rr and rr["lapCount"] == 5 and "5-lap" in rr["name"]

    def test_racer_lapLength_4km(self, user):
        d = self._create(user, "street race, 3 laps on a 4 km circuit")
        assert d["engine"] == "racer3d"
        assert d["config"]["lapLength"] == 4000
        assert d["world"]["track"]["lengthMeters"] == 4000

    def test_streets_relentless_cops(self, user):
        d = self._create(user, "Mob boss city with relentless cops", engine="streets")
        assert d["engine"] == "streets"
        assert d["config"]["policeAggression"] == pytest.approx(1.9, abs=0.01)

    def test_carjack_lazy_cops(self, user):
        d = self._create(user, "GTA heist with lazy cops")
        assert d["engine"] == "carjack"
        assert d["config"]["policeAggression"] == pytest.approx(0.5, abs=0.01)

    def test_carjack_no_police(self, user):
        d = self._create(user, "carjack with no police")
        assert d["engine"] == "carjack"
        assert d["config"]["policeAggression"] == pytest.approx(0.25, abs=0.01)

    def test_maze_frozen_crypt_ice(self, user):
        d = self._create(user, "a maze in a frozen crypt")
        assert d["engine"] == "maze3d"
        assert d["config"]["mazeTheme"] == "ice"

    def test_maze_lava(self, user):
        d = self._create(user, "lava labyrinth")
        assert d["engine"] == "maze3d"
        assert d["config"]["mazeTheme"] == "lava"

    def test_maze_haunted_crypt(self, user):
        d = self._create(user, "haunted crypt maze")
        assert d["engine"] == "maze3d"
        assert d["config"]["mazeTheme"] == "crypt"


# ---------------- Refine while server offline
class TestRefineOffline:
    def test_refine_pending_offline(self, user):
        r = user.post(f"{BASE_URL}/api/game-builder/worlds/refine-pending")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "pending" in d and "refined" in d and d["refined"] == 0
        assert d["server"]["reachable"] is False

    def test_refine_one_world_503(self, user):
        c = user.post(f"{BASE_URL}/api/game-builder/worlds",
                      json={"prompt": "racing night", "engine": "racer3d"})
        assert c.status_code == 200
        wid = c.json()["id"]
        r = user.post(f"{BASE_URL}/api/game-builder/worlds/{wid}/refine")
        assert r.status_code == 503
        assert "frasberg" in r.text.lower() or "server" in r.text.lower()
        user.delete(f"{BASE_URL}/api/game-builder/worlds/{wid}")


# ---------------- PATCH new settings
class TestPatchSettings:
    def test_racer_laps_lapLength_patch(self, user):
        c = user.post(f"{BASE_URL}/api/game-builder/worlds",
                      json={"prompt": "night race", "engine": "racer3d"}).json()
        wid = c["id"]
        r = user.patch(f"{BASE_URL}/api/game-builder/worlds/{wid}",
                       json={"config": {"laps": 4, "lapLength": 2000}})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["config"]["laps"] == 4
        assert d["config"]["lapLength"] == 2000
        assert d["world"]["raceRuleset"]["lapCount"] == 4
        assert d["world"]["track"]["lengthMeters"] == 2000
        user.delete(f"{BASE_URL}/api/game-builder/worlds/{wid}")

    def test_maze_theme_ok(self, user):
        c = user.post(f"{BASE_URL}/api/game-builder/worlds",
                      json={"prompt": "maze fun", "engine": "maze3d"}).json()
        wid = c["id"]
        r = user.patch(f"{BASE_URL}/api/game-builder/worlds/{wid}",
                       json={"config": {"mazeTheme": "ice"}})
        assert r.status_code == 200, r.text
        assert r.json()["config"]["mazeTheme"] == "ice"
        r2 = user.patch(f"{BASE_URL}/api/game-builder/worlds/{wid}",
                        json={"config": {"mazeTheme": "pizza"}})
        assert r2.status_code == 400
        assert "pizza" in r2.text or "must be one of" in r2.text
        user.delete(f"{BASE_URL}/api/game-builder/worlds/{wid}")


# ---------------- Public share page
class TestPublicShare:
    def test_public_world_no_auth(self, user, anon):
        c = user.post(f"{BASE_URL}/api/game-builder/worlds",
                      json={"prompt": "a neon maze in a frozen crypt"}).json()
        wid = c["id"]
        assert c["share_path"] == f"/g/{wid}"
        r = anon.get(f"{BASE_URL}/api/game-builder/public/{wid}")
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("name", "tagline", "engine_title", "genre", "cover_url",
                  "highlights", "creator", "npc_groups"):
            assert k in d, f"missing {k}"
        assert "world" not in d
        assert "prompt" not in d
        # cover_url loads 200
        cover = d["cover_url"]
        full = cover if cover.startswith("http") else f"{BASE_URL}{cover}"
        cr = anon.get(full)
        assert cr.status_code == 200
        user.delete(f"{BASE_URL}/api/game-builder/worlds/{wid}")

    def test_public_unknown_404(self, anon):
        r = anon.get(f"{BASE_URL}/api/game-builder/public/does-not-exist-xyz")
        assert r.status_code == 404

    def test_worlds_list_has_share_path(self, user):
        c = user.post(f"{BASE_URL}/api/game-builder/worlds",
                      json={"prompt": "night racing", "engine": "racer3d"}).json()
        wid = c["id"]
        r = user.get(f"{BASE_URL}/api/game-builder/worlds")
        assert r.status_code == 200
        worlds = r.json()["worlds"]
        matching = [w for w in worlds if w["id"] == wid]
        assert matching and matching[0]["share_path"] == f"/g/{wid}"
        user.delete(f"{BASE_URL}/api/game-builder/worlds/{wid}")


# ---------------- Play HTML with laps / mazeTheme
class TestPlayHtml:
    def test_racer_laps_hud_pill(self, user, anon):
        c = user.post(f"{BASE_URL}/api/game-builder/worlds",
                      json={"prompt": "night race 5 laps", "engine": "racer3d"}).json()
        wid = c["id"]
        r = anon.get(f"{BASE_URL}/api/game-builder/worlds/{wid}/play")
        assert r.status_code == 200
        html = r.text
        assert "FRASBERG_WORLD" in html
        assert "lapPill" in html or "LAP" in html
        user.delete(f"{BASE_URL}/api/game-builder/worlds/{wid}")

    def test_maze_theme_play(self, user, anon):
        c = user.post(f"{BASE_URL}/api/game-builder/worlds",
                      json={"prompt": "lava maze", "engine": "maze3d"}).json()
        wid = c["id"]
        r = anon.get(f"{BASE_URL}/api/game-builder/worlds/{wid}/play")
        assert r.status_code == 200
        assert "FRASBERG_WORLD" in r.text
        assert "lava" in r.text  # mazeTheme injected into config
        user.delete(f"{BASE_URL}/api/game-builder/worlds/{wid}")


# cleanup trailing worlds from TestPromptRules
def test_zzz_cleanup(user):
    for wid in TestPromptRules.created_ids:
        user.delete(f"{BASE_URL}/api/game-builder/worlds/{wid}")
