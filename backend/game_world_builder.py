"""Frasberg Game Builder — prompt -> WorldDefinition (full-game-stack-schema 1.0.0) -> WorldGraph -> real Frasberg engine.

No AI-written game code. A prompt is turned into a typed WorldDefinition by deterministic keyword rules
(engine choice, difficulty, time of day, weather, palette, counts, title). When the owner's Frasberg server
(LUCHII_UPSTREAM_URL + LUCHII_UPSTREAM_API_KEY) answers, it may refine title/tagline/settings — every value it
returns is validated against the engine's tunables, so rules always stay the source of truth.

The world is stored in the WorldGraph collection (same record shape, policy, continuity, diagnostics and audit as
/v1/worldgraph) and played by one of the bundled engines in /app/games (racer3d, streets, dungeon3d, maze3d,
spaceshooter, carjack). The engine HTML is served with window.FRASBERG_WORLD injected + /api/games/assets/world.js,
which exposes window.FWC (engine config) that each engine reads.
"""
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import auth as auth_module
from core import db
from games_portal import GAMES_DIR
from routes_worldgraph import (SCHEMA_VERSION, WorldDefinition, _audit, _continuity_event, _diagnostics_log,
                               _now_ms, _policy_check)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/game-builder")

CREATED_WITH = "frasberg-game-builder"

# ---------------------------------------------------------------- engine catalog
# tunables: key -> (label, min, max, step, defaults by difficulty easy/normal/hard)
ENGINES: Dict[str, Dict[str, Any]] = {
    "racer3d": {
        "title": "Las Vegas Racer", "genre": "Racing", "kind": "racing",
        "description": "3D neon highway racer — lane traffic, nitro pickups, overtakes.",
        "keywords": ["race", "racing", "racer", "highway", "drift", "nitro", "lap", "laps", "circuit", "track",
                     "speed", "fast car", "supercar", "motorway", "vegas", "strip", "overtake", "drag"],
        "tunables": {
            "startSpeed": ("Start speed", 15, 50, 1, (24, 30, 38)),
            "maxSpeed": ("Top speed", 50, 120, 1, (65, 80, 100)),
            "accel": ("Acceleration", 0.2, 1.5, 0.05, (0.4, 0.55, 0.85)),
            "trafficDensity": ("Traffic density", 0.1, 0.95, 0.05, (0.35, 0.55, 0.8)),
            "fogDensity": ("Fog", 0.0, 0.05, 0.001, (0.008, 0.012, 0.02)),
        },
    },
    "streets": {
        "title": "Street Vybz", "genre": "Open World", "kind": "open-world",
        "description": "Open-world city crime sim — carjacks, contracts, mob debt timer, police and fire crews.",
        "keywords": ["street", "streets", "gang", "mob", "mafia", "crime", "hood", "jack city", "pizza", "taxi",
                     "hustle", "debt", "vybz", "boss", "contract", "hitman", "open world city", "on foot"],
        "tunables": {
            "startCash": ("Starting cash", 0, 10000, 50, (800, 0, 0)),
            "debtDue": ("Mob cut ($)", 500, 10000, 50, (1500, 2500, 4500)),
            "debtTimer": ("Cut timer (s)", 60, 600, 10, (320, 240, 150)),
        },
    },
    "carjack": {
        "title": "Frasberg Carjack", "genre": "Open World Driving", "kind": "open-world",
        "description": "Multiplayer open-world carjack — vehicle physics, traffic AI, police chases, missions, weather.",
        "keywords": ["carjack", "car jack", "steal", "heist", "getaway", "police chase", "cops", "gta", "chase",
                     "traffic", "city driving", "multiplayer", "showroom", "garage", "mission", "wanted"],
        "tunables": {
            "startMoney": ("Starting money", 0, 20000, 100, (4000, 1500, 300)),
            "maxHealth": ("Health", 25, 300, 5, (150, 100, 70)),
            "maxSpeed": ("Car top speed", 120, 360, 5, (200, 220, 260)),
            "trafficCount": ("Traffic cars", 5, 80, 1, (20, 30, 45)),
            "npcCount": ("Pedestrians", 0, 80, 1, (20, 25, 35)),
        },
    },
    "dungeon3d": {
        "title": "Luchii Dungeon", "genre": "FPS", "kind": "shooter",
        "description": "First-person dungeon shooter — waves of drones, torchlight, ammo and health.",
        "keywords": ["dungeon", "fps", "first person", "first-person", "shooter arena", "zombie", "zombies",
                     "horror", "castle", "crypt", "catacomb", "torch", "drone", "drones", "wave", "survive", "gun"],
        "tunables": {
            "playerHp": ("Player health", 25, 400, 5, (160, 100, 70)),
            "ammo": ("Clip size", 5, 120, 1, (45, 30, 20)),
            "startEnemies": ("Starting enemies", 1, 30, 1, (3, 5, 8)),
            "waveBase": ("Enemies per wave", 1, 20, 1, (2, 3, 6)),
            "enemySpeed": ("Enemy speed", 0.4, 2.5, 0.05, (0.8, 1.0, 1.35)),
        },
    },
    "spaceshooter": {
        "title": "Constellation Wars", "genre": "Shooter", "kind": "shooter",
        "description": "Space shoot-'em-up — enemy formations, motherships, power-ups and weapon unlocks.",
        "keywords": ["space", "galaxy", "alien", "aliens", "spaceship", "ship", "star", "stars", "asteroid",
                     "asteroids", "invader", "invaders", "shmup", "shoot em up", "shoot-em-up", "planet", "orbit",
                     "constellation", "mothership", "ufo", "laser"],
        "tunables": {
            "lives": ("Lives", 1, 15, 1, (5, 3, 2)),
            "enemySpeed": ("Enemy speed", 0.4, 2.5, 0.05, (0.8, 1.0, 1.35)),
            "bossEvery": ("Boss every N waves", 2, 12, 1, (6, 5, 4)),
            "extraRows": ("Extra enemy rows", 0, 4, 1, (0, 0, 1)),
            "startWave": ("Starting wave", 1, 20, 1, (1, 1, 1)),
        },
    },
    "maze3d": {
        "title": "Meta Maze", "genre": "Puzzle", "kind": "puzzle",
        "description": "Procedural 3D labyrinth — reach the beacon before the clock runs out.",
        "keywords": ["maze", "labyrinth", "puzzle", "escape", "beacon", "explore", "lost", "corridor", "find the exit",
                     "mystery", "riddle", "brain"],
        "tunables": {
            "startSize": ("Maze size", 5, 19, 2, (7, 9, 13)),
            "timeMul": ("Time allowance", 0.4, 2.5, 0.05, (1.4, 1.0, 0.7)),
        },
    },
}
ENGINE_ORDER = ["racer3d", "streets", "carjack", "dungeon3d", "spaceshooter", "maze3d"]
DIFFICULTY_IDX = {"easy": 0, "normal": 1, "hard": 2}
TIMES = ["dawn", "day", "dusk", "night"]
WEATHERS = ["clear", "rain", "fog", "stormy", "heat_haze"]
CARJACK_WEATHER = {"clear": "clear", "rain": "rain", "fog": "fog", "stormy": "heavy-rain", "heat_haze": "clear"}
PALETTE = {
    "red": 0xff3355, "crimson": 0xdc143c, "orange": 0xff7a3c, "gold": 0xffd24a, "yellow": 0xffe14a,
    "green": 0x44ff88, "emerald": 0x2ecc71, "teal": 0x22d3c5, "cyan": 0x22ccff, "blue": 0x3d7bff,
    "purple": 0xaa66ff, "violet": 0x8a5cff, "pink": 0xff2d78, "magenta": 0xff2dd4, "white": 0xffffff,
    "black": 0x222222, "silver": 0xc0c8d0,
}
NPC_ROLES = {
    "racer3d": [("traffic", "Strip traffic")],
    "streets": [("pedestrian", "Jack City locals"), ("police", "LVMPD patrol"), ("mob", "Frankie's crew")],
    "carjack": [("traffic", "City traffic"), ("pedestrian", "Pedestrians"), ("police", "Police AI")],
    "dungeon3d": [("enemy", "Dungeon drones")],
    "spaceshooter": [("enemy", "Enemy formation"), ("boss", "Mothership")],
    "maze3d": [],
}


def _clamp(engine: str, key: str, value: Any) -> Optional[float]:
    spec = ENGINES[engine]["tunables"].get(key)
    if spec is None:
        return None
    _, lo, hi, step, _ = spec
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    v = max(lo, min(hi, v))
    if key == "startSize":  # maze generator needs odd sizes
        v = int(v) | 1
    if isinstance(step, int) and float(step).is_integer() and step >= 1:
        v = int(round(v))
    return v


# ---------------------------------------------------------------- rules
def _hits(text: str, words: List[str]) -> int:
    return sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", text))


def pick_engine(text: str) -> str:
    scores = {e: _hits(text, ENGINES[e]["keywords"]) for e in ENGINE_ORDER}
    best = max(ENGINE_ORDER, key=lambda e: (scores[e], -ENGINE_ORDER.index(e)))
    if scores[best] == 0:
        if _hits(text, ["car", "cars", "drive", "driving", "vehicle"]):
            return "racer3d"
        if _hits(text, ["shoot", "shooter", "enemy", "enemies", "battle", "fight"]):
            return "dungeon3d"
        return "spaceshooter"
    return best


def _difficulty(text: str) -> str:
    if _hits(text, ["easy", "casual", "relaxed", "chill", "kids", "kid", "beginner", "simple", "cozy"]):
        return "easy"
    if _hits(text, ["hard", "brutal", "insane", "expert", "hardcore", "difficult", "nightmare", "extreme", "intense"]):
        return "hard"
    return "normal"


def _time_of_day(text: str) -> Optional[str]:
    if _hits(text, ["night", "midnight", "neon", "nighttime", "moonlit", "dark"]):
        return "night"
    if _hits(text, ["dawn", "sunrise", "morning"]):
        return "dawn"
    if _hits(text, ["dusk", "sunset", "evening", "twilight"]):
        return "dusk"
    if _hits(text, ["day", "daytime", "noon", "sunny", "afternoon"]):
        return "day"
    return None


def _weather(text: str) -> Optional[str]:
    if _hits(text, ["storm", "stormy", "thunder", "lightning", "hurricane"]):
        return "stormy"
    if _hits(text, ["rain", "rainy", "raining", "wet", "monsoon"]):
        return "rain"
    if _hits(text, ["fog", "foggy", "mist", "misty", "haze", "snow", "snowy", "blizzard"]):
        return "fog"
    if _hits(text, ["desert", "heatwave", "scorching", "heat"]):
        return "heat_haze"
    if _hits(text, ["clear", "sunny"]):
        return "clear"
    return None


def _colors(text: str) -> List[int]:
    return [PALETTE[c] for c in PALETTE if re.search(rf"\b{c}\b", text)]


def _number_before(text: str, nouns: List[str]) -> Optional[int]:
    for n in nouns:
        m = re.search(rf"(\d{{1,5}})\s*(?:x\s*)?{n}\b", text)
        if m:
            return int(m.group(1))
    return None


def _money(text: str) -> Optional[int]:
    m = re.search(r"\$\s?(\d[\d,]{0,7})", text) or re.search(r"(\d[\d,]{1,7})\s*(?:cash|dollars|money|bucks)\b", text)
    return int(m.group(1).replace(",", "")) if m else None


def _title(prompt: str, engine: str, tod: Optional[str]) -> str:
    m = re.search(r"[\"“']([^\"”']{3,48})[\"”']", prompt) or \
        re.search(r"\b(?:called|named|titled)\s+([A-Z0-9][\w' \-]{2,40}?)(?:[.,;!]|\s+(?:where|with|that|in|on)\b|$)", prompt)
    if m:
        return m.group(1).strip()
    base = ENGINES[engine]["title"]
    return f"{tod.capitalize()} {base}" if tod else base


def plan_from_rules(prompt: str, engine_hint: Optional[str] = None) -> Dict[str, Any]:
    text = prompt.lower()
    engine = engine_hint if engine_hint in ENGINES else pick_engine(text)
    diff = _difficulty(text)
    tod, weather = _time_of_day(text), _weather(text)
    idx = DIFFICULTY_IDX[diff]
    cfg: Dict[str, Any] = {k: spec[4][idx] for k, spec in ENGINES[engine]["tunables"].items()}
    colors = _colors(text)
    laps = _number_before(text, ["laps?"])
    if engine == "racer3d":
        if colors:
            cfg["trafficColors"] = colors
        if weather == "fog":
            cfg["fogDensity"] = 0.03
        if tod == "day":
            cfg["fogColor"] = 0x8fb4d8
    elif engine == "spaceshooter":
        lives = _number_before(text, ["lives", "life", "ships"])
        if lives:
            cfg["lives"] = lives
        boss = re.search(r"boss (?:every|each) (\d{1,2})", text)
        if boss:
            cfg["bossEvery"] = int(boss.group(1))
    elif engine == "dungeon3d":
        n = _number_before(text, ["enemies", "drones", "zombies", "monsters"])
        if n:
            cfg["startEnemies"] = n
        hp = _number_before(text, ["hp", "health"])
        if hp:
            cfg["playerHp"] = hp
    elif engine == "maze3d":
        size = re.search(r"(\d{1,2})\s*(?:x\s*\d{1,2})?\s*(?:maze|grid)", text)
        if size:
            cfg["startSize"] = int(size.group(1))
        mins = _number_before(text, ["minutes?", "mins?"])
        if mins:
            cfg["timeMul"] = max(0.4, min(2.5, (mins * 60) / 96))
    elif engine == "streets":
        cash = _money(text)
        if cash is not None:
            cfg["startCash"] = cash
    elif engine == "carjack":
        cash = _money(text)
        if cash is not None:
            cfg["startMoney"] = cash
        if colors:
            cfg["carColor"] = "#%06x" % colors[0]
        if weather:
            cfg["weather"] = CARJACK_WEATHER[weather]
        n = _number_before(text, ["cars", "traffic"])
        if n:
            cfg["trafficCount"] = n
    for k in list(cfg):
        if k in ENGINES[engine]["tunables"]:
            cfg[k] = _clamp(engine, k, cfg[k])
    return {"engine": engine, "difficulty": diff, "time_of_day": tod, "weather": weather, "config": cfg,
            "title": _title(prompt, engine, tod), "tagline": ENGINES[engine]["description"], "laps": laps,
            "colors": colors}


# ---------------------------------------------------------------- Frasberg server refinement
FRASBERG_SYSTEM = (
    "You are the Frasberg Game Builder planner. You never write code. Given a game idea and the rule-based plan, "
    "return ONLY a JSON object with optional keys: title (<=40 chars), tagline (<=110 chars), engine (one of "
    + ", ".join(ENGINE_ORDER) + "), difficulty (easy|normal|hard), time_of_day (dawn|day|dusk|night), "
    "weather (clear|rain|fog|stormy|heat_haze), config (object of numeric engine settings from the plan's keys)."
)


async def frasberg_complete(system: str, user_text: str, timeout: float = 12.0, max_tokens: int = 600) -> Optional[str]:
    url = os.environ.get("LUCHII_UPSTREAM_URL", "").strip()
    key = os.environ.get("LUCHII_UPSTREAM_API_KEY", "").strip()
    if not url or not key:
        return None
    if url.rstrip("/").endswith("/v1/chat"):
        url = url.rstrip("/") + "/completions"
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                           "X-Luchii-Router": "1"},
                             json={"model": "luchii-70b", "max_tokens": max_tokens, "temperature": 0.4,
                                   "messages": [{"role": "system", "content": system},
                                                {"role": "user", "content": user_text}]})
        if r.status_code >= 400:
            logger.info("Frasberg server returned %s for game builder", r.status_code)
            return None
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        logger.info("Frasberg server unreachable for game builder: %s", str(e)[:160])
        return None


def _parse_json(text: str) -> Optional[dict]:
    i, j = text.find("{"), text.rfind("}")
    if i == -1 or j <= i:
        return None
    try:
        data = json.loads(text[i:j + 1])
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


async def refine_with_frasberg(prompt: str, plan: Dict[str, Any], engine_locked: bool) -> Dict[str, Any]:
    raw = await frasberg_complete(FRASBERG_SYSTEM, json.dumps({"idea": prompt[:1500], "plan": plan})[:6000])
    data = _parse_json(raw) if raw else None
    if not data:
        return {**plan, "enriched_by": "rules"}
    out = dict(plan)
    if not engine_locked and data.get("engine") in ENGINES and data["engine"] != plan["engine"]:
        out = plan_from_rules(prompt, data["engine"])
    if isinstance(data.get("title"), str) and data["title"].strip():
        out["title"] = data["title"].strip()[:40]
    if isinstance(data.get("tagline"), str) and data["tagline"].strip():
        out["tagline"] = data["tagline"].strip()[:110]
    if data.get("time_of_day") in TIMES:
        out["time_of_day"] = data["time_of_day"]
    if data.get("weather") in WEATHERS:
        out["weather"] = data["weather"]
    if isinstance(data.get("config"), dict):
        cfg = dict(out["config"])
        for k, v in data["config"].items():
            cv = _clamp(out["engine"], k, v)
            if cv is not None:
                cfg[k] = cv
        out["config"] = cfg
    out["enriched_by"] = "rules+frasberg"
    return out


# ---------------------------------------------------------------- WorldDefinition
def build_world(prompt: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    engine = plan["engine"]
    meta = ENGINES[engine]
    cfg = plan["config"]
    wid = f"wg-{uuid.uuid4()}"
    tags = [engine, meta["genre"].lower(), plan["difficulty"]] + [t for t in (plan.get("time_of_day"), plan.get("weather")) if t]
    npc_counts = {"traffic": cfg.get("trafficCount"), "pedestrian": cfg.get("npcCount"),
                  "enemy": cfg.get("startEnemies")}
    components = [
        {"id": "engine", "type": "engine.runtime", "props": {"engine": engine, "title": meta["title"], **cfg},
         "children": [], "actions": [{"id": "act-start", "type": "game.start", "targetId": "engine"}]},
        {"id": "environment", "type": "environment", "props": {"timeOfDay": plan.get("time_of_day") or "live",
                                                                "weather": plan.get("weather") or "live"},
         "children": [], "actions": []},
    ] + [
        {"id": f"npc-{role}", "type": "npc.group", "props": {"role": role, "label": label,
                                                             **({"count": npc_counts[role]} if npc_counts.get(role) else {})},
         "children": [], "actions": []}
        for role, label in NPC_ROLES.get(engine, [])
    ]
    world: Dict[str, Any] = {
        "id": wid, "name": plan["title"], "kind": "game",
        "metadata": {"schemaVersion": SCHEMA_VERSION, "createdWith": CREATED_WITH, "tags": tags,
                     "engine": engine, "engineConfig": cfg, "prompt": prompt[:1000], "tagline": plan["tagline"],
                     "difficulty": plan["difficulty"], "enrichedBy": plan.get("enriched_by", "rules"),
                     "environment": {k: v for k, v in (("time_of_day", plan.get("time_of_day")),
                                                       ("weather", plan.get("weather"))) if v}},
        "scenes": [{"id": "scene-main", "name": plan["title"], "components": components,
                    "actions": [{"id": "scene-enter", "type": "scene.enter", "targetId": "engine"}]}],
        "pages": [], "screens": [], "flows": [],
        "routes": [{"id": "route-play", "path": "/play", "targetKind": "scene", "targetId": "scene-main", "guards": []}],
        "vehicleClasses": [], "nodes": [], "status": "active",
    }
    if engine == "racer3d":
        world["track"] = {"id": "track-main", "name": f"{plan['title']} Circuit", "lengthMeters": 4800,
                          "surface": "asphalt", "sectors": 3}
        world["vehicleClasses"] = [{"id": "vc-hyper", "name": "Hyper EV", "horsepower": int(cfg["maxSpeed"] * 9),
                                    "drivetrain": "awd", "tags": ["player"]}]
        world["raceRuleset"] = {"id": "rules-main", "name": "Endless overtake", "lapCount": plan.get("laps") or 1,
                                "rollingStart": True, "allowedVehicleClassIds": ["vc-hyper"]}
    elif engine == "carjack":
        world["vehicleClasses"] = [{"id": "vc-player", "name": cfg.get("carName") or "Frasberg GT",
                                    "horsepower": int(cfg["maxSpeed"] * 2.4), "drivetrain": "rwd", "tags": ["player"]},
                                   {"id": "vc-traffic", "name": "City traffic", "horsepower": 180,
                                    "drivetrain": "fwd", "tags": ["npc"]}]
    elif engine == "streets":
        world["vehicleClasses"] = [{"id": "vc-street", "name": "Jack City streetcar", "horsepower": 320,
                                    "drivetrain": "rwd", "tags": ["jackable"]}]
    return WorldDefinition(**world).model_dump()


# ---------------------------------------------------------------- API
class CreateWorldIn(BaseModel):
    prompt: str
    engine: Optional[str] = None


class UpdateWorldIn(BaseModel):
    name: Optional[str] = None
    tagline: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    time_of_day: Optional[str] = None
    weather: Optional[str] = None


def _engine_public(eid: str) -> dict:
    e = ENGINES[eid]
    return {"id": eid, "title": e["title"], "genre": e["genre"], "description": e["description"],
            "thumbnail": f"/games-thumbs/{eid}.jpg" if eid != "carjack" else "/api/games/assets/backdrop-streets.jpg",
            "tunables": [{"key": k, "label": s[0], "min": s[1], "max": s[2], "step": s[3],
                          "default": s[4][1]} for k, s in e["tunables"].items()]}


def _record_out(doc: dict) -> dict:
    w = doc["world"]
    m = w.get("metadata") or {}
    return {"id": w["id"], "name": w["name"], "engine": m.get("engine"),
            "engine_title": ENGINES.get(m.get("engine"), {}).get("title"), "tagline": m.get("tagline"),
            "difficulty": m.get("difficulty"), "enriched_by": m.get("enrichedBy"), "config": m.get("engineConfig") or {},
            "environment": m.get("environment") or {}, "prompt": m.get("prompt"), "world": w,
            "play_url": f"/api/game-builder/worlds/{w['id']}/play",
            "created_at": doc.get("created_at"), "updated_at": doc.get("updated_at")}


@router.get("/engines")
async def list_engines():
    return {"engines": [_engine_public(e) for e in ENGINE_ORDER], "schemaVersion": SCHEMA_VERSION}


@router.post("/plan")
async def preview_plan(body: CreateWorldIn, user: dict = Depends(auth_module.get_current_user)):
    prompt = (body.prompt or "").strip()
    if len(prompt) < 3:
        raise HTTPException(status_code=400, detail="Describe the game you want to build")
    plan = plan_from_rules(prompt, body.engine)
    return {"plan": plan, "world": build_world(prompt, {**plan, "enriched_by": "rules"})}


@router.post("/worlds")
async def create_world(body: CreateWorldIn, user: dict = Depends(auth_module.get_current_user)):
    prompt = (body.prompt or "").strip()
    if len(prompt) < 3:
        raise HTTPException(status_code=400, detail="Describe the game you want to build")
    if body.engine and body.engine not in ENGINES:
        raise HTTPException(status_code=400, detail=f"Unknown engine. Use one of: {', '.join(ENGINE_ORDER)}")
    owner = user["id"]
    await _policy_check(owner, "worldgraph.create")
    plan = plan_from_rules(prompt, body.engine)
    plan = await refine_with_frasberg(prompt, plan, engine_locked=bool(body.engine))
    world = build_world(prompt, plan)
    now = _now_ms()
    doc = {"id": str(uuid.uuid4()), "owner_id": owner, "world": world, "status": "active",
           "source": CREATED_WITH, "created_at": now, "updated_at": now}
    await db.worldgraph.insert_one(doc.copy())
    await _continuity_event(owner, "worldgraph.created", world["id"])
    await _diagnostics_log(owner, "game-builder", {"op": "create", "world_id": world["id"], "engine": plan["engine"],
                                                   "enriched_by": plan.get("enriched_by")})
    await _audit(owner, "create", world["id"], {"key": None})
    return _record_out(doc)


@router.get("/worlds")
async def my_worlds(user: dict = Depends(auth_module.get_current_user)):
    docs = await db.worldgraph.find({"owner_id": user["id"], "world.kind": "game",
                                     "world.metadata.createdWith": CREATED_WITH}, {"_id": 0}) \
        .sort("updated_at", -1).to_list(100)
    return {"worlds": [_record_out(d) for d in docs]}


async def _owned(user: dict, world_id: str) -> dict:
    doc = await db.worldgraph.find_one({"owner_id": user["id"], "world.id": world_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="World not found")
    return doc


@router.get("/worlds/{world_id}")
async def get_world(world_id: str, user: dict = Depends(auth_module.get_current_user)):
    return _record_out(await _owned(user, world_id))


@router.patch("/worlds/{world_id}")
async def update_world(world_id: str, body: UpdateWorldIn, user: dict = Depends(auth_module.get_current_user)):
    owner = user["id"]
    await _policy_check(owner, "worldgraph.update")
    doc = await _owned(user, world_id)
    w = doc["world"]
    m = w["metadata"]
    engine = m.get("engine")
    if engine not in ENGINES:
        raise HTTPException(status_code=400, detail="World has no Frasberg engine")
    sets: Dict[str, Any] = {}
    if body.config:
        cfg = dict(m.get("engineConfig") or {})
        for k, v in body.config.items():
            cv = _clamp(engine, k, v)
            if cv is None:
                raise HTTPException(status_code=400, detail=f"Unknown setting '{k}' for {engine}")
            cfg[k] = cv
        sets["world.metadata.engineConfig"] = cfg
        comps = w["scenes"][0]["components"]
        for comp in comps:
            if comp["id"] == "engine":
                comp["props"] = {**comp["props"], **cfg}
        sets["world.scenes"] = w["scenes"]
    if body.name and body.name.strip():
        sets["world.name"] = body.name.strip()[:60]
    if body.tagline is not None:
        sets["world.metadata.tagline"] = body.tagline.strip()[:140]
    env = dict(m.get("environment") or {})
    if body.time_of_day is not None:
        if body.time_of_day and body.time_of_day not in TIMES:
            raise HTTPException(status_code=400, detail="time_of_day must be dawn, day, dusk or night")
        env.pop("time_of_day", None)
        if body.time_of_day:
            env["time_of_day"] = body.time_of_day
    if body.weather is not None:
        if body.weather and body.weather not in WEATHERS:
            raise HTTPException(status_code=400, detail="weather must be one of " + ", ".join(WEATHERS))
        env.pop("weather", None)
        if body.weather:
            env["weather"] = body.weather
    sets["world.metadata.environment"] = env
    sets["updated_at"] = _now_ms()
    await db.worldgraph.update_one({"owner_id": owner, "world.id": world_id}, {"$set": sets})
    await _continuity_event(owner, "worldgraph.updated", world_id)
    await _diagnostics_log(owner, "game-builder", {"op": "update", "world_id": world_id,
                                                   "fields": sorted(body.model_dump(exclude_none=True))})
    await _audit(owner, "update", world_id, {"key": None})
    return _record_out(await _owned(user, world_id))


@router.delete("/worlds/{world_id}")
async def delete_world(world_id: str, user: dict = Depends(auth_module.get_current_user)):
    owner = user["id"]
    await _policy_check(owner, "worldgraph.delete")
    await _owned(user, world_id)
    await db.worldgraph.delete_one({"owner_id": owner, "world.id": world_id})
    await _continuity_event(owner, "worldgraph.deleted", world_id)
    await _audit(owner, "delete", world_id, {"key": None})
    return {"deleted": world_id}


@router.get("/worlds/{world_id}/play")
async def play_world(world_id: str):
    """Public by unguessable world id (share link). Serves the real engine with the world injected."""
    doc = await db.worldgraph.find_one({"world.id": world_id, "world.kind": "game"}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="World not found")
    w = doc["world"]
    m = w.get("metadata") or {}
    engine = m.get("engine")
    if engine not in ENGINES:
        raise HTTPException(status_code=400, detail="World has no Frasberg engine")
    html_path = GAMES_DIR / engine / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Engine build missing")
    cfg = dict(m.get("engineConfig") or {})
    env = m.get("environment") or {}
    if engine == "carjack":
        hours = {"dawn": 7, "day": 12, "dusk": 19.5, "night": 23}
        if env.get("time_of_day") in hours:
            cfg["hour"] = hours[env["time_of_day"]]
        if env.get("weather") in CARJACK_WEATHER:
            cfg["weather"] = CARJACK_WEATHER[env["weather"]]
    payload = {"id": w["id"], "name": w["name"], "tagline": m.get("tagline"), "engine": engine,
               "engineTitle": ENGINES[engine]["title"], "config": cfg,
               "environment": env, "world": w}
    blob = json.dumps(payload).replace("</", "<\\/")
    base = f'<base href="/api/games/{engine}/">' if engine == "carjack" else ""
    inject = (f"{base}<script>window.FRASBERG_WORLD={blob};</script>"
              '<script src="/api/games/assets/world.js"></script>')
    html = html_path.read_text()
    i = html.lower().find("<head>")
    html = html[:i + 6] + inject + html[i + 6:] if i != -1 else inject + html
    await db.worldgraph.update_one({"world.id": world_id}, {"$inc": {"plays": 1}})
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
