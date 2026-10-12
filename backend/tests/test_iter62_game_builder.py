"""Iter62: Game Builder (WorldGraph engines) + navbar/model-pair + creator engines regression."""
import os
import time
import pytest
import requests

def _load_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    try:
        for line in open("/app/frontend/.env"):
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not configured")


BASE_URL = _load_url()
USER_EMAIL = "test@luchii.ai"
USER_PASS = "Test1234!"


@pytest.fixture(scope="session")
def user_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": USER_EMAIL, "password": USER_PASS})
    if r.status_code != 200:
        # ensure exists
        s.post(f"{BASE_URL}/api/auth/register", json={"email": USER_EMAIL, "password": USER_PASS, "name": "Test"})
        r = s.post(f"{BASE_URL}/api/auth/login", json={"email": USER_EMAIL, "password": USER_PASS})
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="session")
def anon_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- Engines catalog
def test_engines_catalog(anon_session):
    r = anon_session.get(f"{BASE_URL}/api/game-builder/engines")
    assert r.status_code == 200, r.text
    data = r.json()
    engines = data["engines"]
    ids = [e["id"] for e in engines]
    assert ids == ["racer3d", "streets", "carjack", "dungeon3d", "spaceshooter", "maze3d"]
    for e in engines:
        assert e["tunables"] and all("key" in t and "min" in t and "max" in t for t in e["tunables"])


def test_create_world_unauthenticated(anon_session):
    r = anon_session.post(f"{BASE_URL}/api/game-builder/worlds", json={"prompt": "something"})
    assert r.status_code == 401, r.status_code


def test_create_world_unknown_engine(user_session):
    r = user_session.post(f"{BASE_URL}/api/game-builder/worlds",
                          json={"prompt": "something", "engine": "nonexistent"})
    assert r.status_code == 400


# ---------------- Rules-based engine picking
CREATED_IDS = []


@pytest.mark.parametrize("prompt,expected_engine,check", [
    ("neon night street race 3 laps pink traffic", "racer3d", lambda c, m: True),
    ("steal cars police chase in rain $5000", "carjack", lambda c, m: c.get("startMoney") == 5000),
    ("alien invaders space boss every 3 waves 7 lives", "spaceshooter",
     lambda c, m: c.get("lives") == 7 and c.get("bossEvery") == 3),
    ("zombie dungeon 12 enemies", "dungeon3d", lambda c, m: c.get("startEnemies") == 12),
    ('cozy foggy maze called "Mist Hollow"', "maze3d", lambda c, m: m.get("name") == "Mist Hollow"),
    ("mob boss crime city start with $900", "streets", lambda c, m: c.get("startCash") == 900),
])
def test_create_world_rules(user_session, prompt, expected_engine, check):
    r = user_session.post(f"{BASE_URL}/api/game-builder/worlds", json={"prompt": prompt})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["engine"] == expected_engine, f"Expected {expected_engine}, got {data['engine']} for prompt: {prompt}"
    assert data["enriched_by"] == "rules"
    assert check(data["config"], data), f"check failed for {prompt}: cfg={data['config']} name={data['name']}"
    CREATED_IDS.append(data["id"])


def test_engine_param_forces(user_session):
    r = user_session.post(f"{BASE_URL}/api/game-builder/worlds",
                          json={"prompt": "zombie dungeon 12 enemies", "engine": "maze3d"})
    assert r.status_code == 200
    assert r.json()["engine"] == "maze3d"
    CREATED_IDS.append(r.json()["id"])


# ---------------- List/worldgraph integration
def test_my_worlds_lists(user_session):
    r = user_session.get(f"{BASE_URL}/api/game-builder/worlds")
    assert r.status_code == 200
    ids = {w["id"] for w in r.json()["worlds"]}
    assert any(i in ids for i in CREATED_IDS), "Created world not in my-worlds listing"


def test_worldgraph_integration(user_session):
    r = user_session.get(f"{BASE_URL}/api/v1/worldgraph")
    assert r.status_code == 200, r.text
    worlds = r.json()["payload"]["worlds"]
    ids = {w.get("world", {}).get("id") for w in worlds if isinstance(w, dict)}
    assert any(i in ids for i in CREATED_IDS), "Game-builder worlds should also surface in worldgraph"


# ---------------- Patch (clamp + reject unknown) + delete
def test_patch_clamp_and_env(user_session):
    assert CREATED_IDS, "need prior created world"
    wid = CREATED_IDS[0]  # racer3d
    r = user_session.patch(f"{BASE_URL}/api/game-builder/worlds/{wid}",
                           json={"config": {"maxSpeed": 9999}, "time_of_day": "night", "weather": "rain"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["config"]["maxSpeed"] <= 120  # clamped
    assert data["environment"].get("time_of_day") == "night"
    assert data["environment"].get("weather") == "rain"


def test_patch_unknown_key_400(user_session):
    wid = CREATED_IDS[0]
    r = user_session.patch(f"{BASE_URL}/api/game-builder/worlds/{wid}",
                           json={"config": {"notARealKey": 1}})
    assert r.status_code == 400


def test_play_world_public(anon_session):
    wid = CREATED_IDS[0]
    r = anon_session.get(f"{BASE_URL}/api/game-builder/worlds/{wid}/play")
    assert r.status_code == 200, r.status_code
    assert "window.FRASBERG_WORLD" in r.text
    assert "/api/games/assets/world.js" in r.text


def test_delete_world(user_session):
    wid = CREATED_IDS[-1]
    r = user_session.delete(f"{BASE_URL}/api/game-builder/worlds/{wid}")
    assert r.status_code == 200
    r2 = user_session.get(f"{BASE_URL}/api/game-builder/worlds/{wid}")
    assert r2.status_code == 404


# ---------------- Games library / creator / regression
def test_games_includes_carjack(anon_session):
    r = anon_session.get(f"{BASE_URL}/api/games")
    assert r.status_code == 200
    data = r.json()
    games = data if isinstance(data, list) else (data.get("games") or [])
    ids = [g["id"] for g in games]
    assert "carjack" in ids


def test_games_carjack_play(anon_session):
    r = anon_session.get(f"{BASE_URL}/api/games/carjack/play")
    assert r.status_code == 200
    assert len(r.text) > 100


def test_creator_engines_image_xl(anon_session):
    r = anon_session.get(f"{BASE_URL}/api/creator/gpu/v1/engines")
    assert r.status_code == 200
    text = r.text
    assert "frasberg-image-xl" in text
