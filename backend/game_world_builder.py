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
import asyncio
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
            "laps": ("Race laps (0 = endless)", 0, 20, 1, (0, 0, 0)),
            "lapLength": ("Lap length (m)", 1000, 10000, 250, (2500, 3000, 4000)),
        },
    },
    "streets": {
        "title": "Street Vybz", "genre": "Open World", "kind": "open-world",
        "description": "Open-world city crime sim — carjacks, contracts, mob debt timer, police and fire crews.",
        "keywords": ["street", "streets", "gang", "mob", "mafia", "crime", "hood", "jack city", "pizza", "taxi",
                     "hustle", "debt", "vybz", "mob boss", "crime boss", "contract", "hitman", "open world city", "on foot"],
        "tunables": {
            "startCash": ("Starting cash", 0, 10000, 50, (800, 0, 0)),
            "debtDue": ("Mob cut ($)", 500, 10000, 50, (1500, 2500, 4500)),
            "debtTimer": ("Cut timer (s)", 60, 600, 10, (320, 240, 150)),
            "policeAggression": ("Police aggression", 0.25, 2.5, 0.05, (0.6, 1.0, 1.6)),
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
            "policeAggression": ("Police aggression", 0.25, 2.5, 0.05, (0.6, 1.0, 1.6)),
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
                     "constellation", "mothership", "ufo", "laser", "space shooter", "space battle",
                     "starship", "starfighter", "cosmic"],
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
        "choices": {
            "mazeTheme": ("Maze theme", ["neon", "ice", "lava", "jungle", "crypt", "desert", "gold"],
                          ("neon", "neon", "neon")),
        },
    },
}
ENGINE_ORDER = ["racer3d", "streets", "carjack", "dungeon3d", "spaceshooter", "maze3d"]
# Words that name the engine itself outweigh setting words ("a maze in a crypt" is a maze, not a dungeon).
CORE_WORDS = {
    "racer3d": ["race", "racing", "racer", "laps"], "streets": ["mafia", "mob", "gang", "streets"],
    "carjack": ["carjack", "gta", "heist"], "dungeon3d": ["dungeon", "fps"],
    "spaceshooter": ["space shooter", "spaceship", "shmup", "invaders"], "maze3d": ["maze", "labyrinth"],
}
MAZE_THEME_WORDS = [
    ("ice", ["ice", "icy", "frozen", "snow", "snowy", "winter", "glacier", "arctic"]),
    ("lava", ["lava", "volcano", "volcanic", "fire", "inferno", "hell", "magma"]),
    ("jungle", ["jungle", "forest", "vines", "garden", "overgrown", "hedge", "rainforest"]),
    ("crypt", ["crypt", "tomb", "catacomb", "catacombs", "haunted", "spooky", "graveyard", "stone"]),
    ("desert", ["desert", "sand", "sandy", "pyramid", "egypt", "egyptian", "dune", "dunes"]),
    ("gold", ["gold", "golden", "treasure", "temple", "palace"]),
    ("neon", ["neon", "cyber", "cyberpunk", "synth", "synthwave", "retro"]),
]
POLICE_WORDS = r"(?:police|cops?|lvmpd|swat|feds|sheriffs?|patrols?)"
POLICE_HIGH = ["aggressive", "relentless", "ruthless", "brutal", "angry", "hardcore", "insane", "merciless",
               "heavy", "swarming", "lots of", "tons of", "many", "crazy", "intense", "tough"]
POLICE_LOW = ["lazy", "chill", "relaxed", "slow", "few", "weak", "sleepy", "passive", "light", "easy", "gentle"]
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


def _clamp(engine: str, key: str, value: Any) -> Optional[Any]:
    choice = ENGINES[engine].get("choices", {}).get(key)
    if choice is not None:
        v = str(value).strip().lower() if value is not None else ""
        return v if v in choice[1] else None
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


def _score(text: str, words: List[str]) -> int:
    """Multi-word phrases ("space shooter", "police chase") are stronger signals than single words."""
    return sum(2 if " " in w or "-" in w else 1 for w in words if re.search(rf"\b{re.escape(w)}\b", text))


def pick_engine(text: str) -> str:
    scores = {e: _score(text, ENGINES[e]["keywords"]) + 2 * _hits(text, CORE_WORDS.get(e, [])) for e in ENGINE_ORDER}
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


def _maze_theme(text: str) -> Optional[str]:
    for theme, words in MAZE_THEME_WORDS:
        if _hits(text, words):
            return theme
    return None


def _police_aggression(text: str) -> Optional[float]:
    """Reads e.g. "aggressive cops", "relentless police", "lazy cops", "no police", "police aggression 1.8"."""
    m = re.search(rf"{POLICE_WORDS}\s*aggression\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    if re.search(rf"\b(?:no|zero|without)\s+{POLICE_WORDS}\b", text):
        return 0.25
    for words, value in ((POLICE_HIGH, 1.9), (POLICE_LOW, 0.5)):
        alt = "|".join(re.escape(w) for w in words)
        if re.search(rf"\b(?:{alt})\s+(?:\w+\s+)?{POLICE_WORDS}\b", text) or \
                re.search(rf"\b{POLICE_WORDS}\s+(?:are|is|that are|who are)?\s*(?:very\s+|super\s+|really\s+)?(?:{alt})\b", text):
            return value
    return None


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
    cfg.update({k: spec[2][idx] for k, spec in ENGINES[engine].get("choices", {}).items()})
    colors = _colors(text)
    laps = _number_before(text, ["laps?"])
    if engine == "racer3d":
        if laps:
            cfg["laps"] = laps
        km = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kilometers?|kilometres?)\s*(?:laps?|track|circuit)", text)
        if km:
            cfg["lapLength"] = float(km.group(1)) * 1000
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
        theme = _maze_theme(text)
        if theme:
            cfg["mazeTheme"] = theme
    elif engine == "streets":
        cash = _money(text)
        if cash is not None:
            cfg["startCash"] = cash
        agg = _police_aggression(text)
        if agg is not None:
            cfg["policeAggression"] = agg
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
        agg = _police_aggression(text)
        if agg is not None:
            cfg["policeAggression"] = agg
    for k in list(cfg):
        if k in ENGINES[engine]["tunables"] or k in ENGINES[engine].get("choices", {}):
            cfg[k] = _clamp(engine, k, cfg[k])
    return {"engine": engine, "difficulty": diff, "time_of_day": tod, "weather": weather, "config": cfg,
            "title": _title(prompt, engine, tod), "tagline": ENGINES[engine]["description"], "laps": laps,
            "colors": colors}


# ---------------------------------------------------------------- Frasberg server refinement
FRASBERG_SYSTEM = (
    "You are the Frasberg Game Builder planner. You never write code. Given a game idea and the rule-based plan, "
    "return ONLY a JSON object with optional keys: title (<=40 chars), tagline (<=110 chars), engine (one of "
    + ", ".join(ENGINE_ORDER) + "), difficulty (easy|normal|hard), time_of_day (dawn|day|dusk|night), "
    "weather (clear|rain|fog|stormy|heat_haze), config (object of engine settings using ONLY the plan's config keys; "
    "numbers for numeric settings, mazeTheme one of neon|ice|lava|jungle|crypt|desert|gold)."
)


# Last result of a call to the owner's Frasberg server (shown on the Game Builder status pill).
UPSTREAM_STATE: Dict[str, Any] = {"reachable": None, "status": None, "detail": "not checked yet", "checked_at": None}


def _mark_upstream(reachable: bool, status: Optional[int], detail: str) -> None:
    UPSTREAM_STATE.update({"reachable": reachable, "status": status, "detail": detail[:200], "checked_at": _now_ms()})


async def frasberg_complete(system: str, user_text: str, timeout: float = 12.0, max_tokens: int = 600) -> Optional[str]:
    url = os.environ.get("LUCHII_UPSTREAM_URL", "").strip()
    key = os.environ.get("LUCHII_UPSTREAM_API_KEY", "").strip()
    if not url or not key:
        _mark_upstream(False, None, "LUCHII_UPSTREAM_URL / LUCHII_UPSTREAM_API_KEY not set")
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
            hint = " (blocked by Cloudflare)" if r.status_code == 403 and "cloudflare" in r.text.lower() else ""
            _mark_upstream(False, r.status_code, f"HTTP {r.status_code}{hint}")
            return None
        content = r.json()["choices"][0]["message"]["content"]
        _mark_upstream(True, r.status_code, "online")
        return content
    except Exception as e:  # noqa: BLE001
        logger.info("Frasberg server unreachable for game builder: %s", str(e)[:160])
        _mark_upstream(False, None, f"unreachable: {type(e).__name__}")
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
                                                             **({"count": npc_counts[role]} if npc_counts.get(role) else {}),
                                                             **({"aggression": cfg["policeAggression"]}
                                                                if role == "police" and "policeAggression" in cfg else {})},
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
        world["track"] = {"id": "track-main", "name": f"{plan['title']} Circuit",
                          "lengthMeters": int(cfg.get("lapLength") or 3000),
                          "surface": "asphalt", "sectors": 3}
        world["vehicleClasses"] = [{"id": "vc-hyper", "name": "Hyper EV", "horsepower": int(cfg["maxSpeed"] * 9),
                                    "drivetrain": "awd", "tags": ["player"]}]
        n_laps = int(cfg.get("laps") or 0)
        world["raceRuleset"] = {"id": "rules-main", "name": f"{n_laps}-lap race" if n_laps else "Endless overtake",
                                "lapCount": n_laps or 1,
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
            "tunables": [{"key": k, "type": "range", "label": s[0], "min": s[1], "max": s[2], "step": s[3],
                          "default": s[4][1]} for k, s in e["tunables"].items()] +
                        [{"key": k, "type": "select", "label": s[0], "options": s[1], "default": s[2][1]}
                         for k, s in e.get("choices", {}).items()]}


def _cover(engine: Optional[str]) -> str:
    name = "streets" if engine in ("carjack", None) or engine not in ENGINES else engine
    return f"/api/games/assets/backdrop-{name}.jpg"


def _record_out(doc: dict) -> dict:
    w = doc["world"]
    m = w.get("metadata") or {}
    return {"id": w["id"], "name": w["name"], "engine": m.get("engine"),
            "engine_title": ENGINES.get(m.get("engine"), {}).get("title"), "tagline": m.get("tagline"),
            "difficulty": m.get("difficulty"), "enriched_by": m.get("enrichedBy"), "config": m.get("engineConfig") or {},
            "environment": m.get("environment") or {}, "prompt": m.get("prompt"), "world": w,
            "play_url": f"/api/game-builder/worlds/{w['id']}/play", "share_path": f"/g/{w['id']}",
            "cover_url": _cover(m.get("engine")), "plays": doc.get("plays", 0),
            "created_at": doc.get("created_at"), "updated_at": doc.get("updated_at")}


@router.get("/frasberg-status")
async def frasberg_status(refresh: bool = False):
    """Is the owner's Frasberg server (LUCHII_UPSTREAM_URL) answering? Re-probes when stale (>60s) or refresh=1."""
    stale = UPSTREAM_STATE["checked_at"] is None or _now_ms() - UPSTREAM_STATE["checked_at"] > 60_000
    if refresh or stale:
        await frasberg_complete("Reply with the single word: ok", "ping", timeout=8.0, max_tokens=5)
    host = re.sub(r"^https?://([^/]+).*$", r"\1", os.environ.get("LUCHII_UPSTREAM_URL", "")) or None
    return {**UPSTREAM_STATE, "host": host}


@router.get("/public/{world_id}")
async def public_world(world_id: str):
    """Public share page data for one game world (no auth — the world id is the share secret)."""
    doc = await db.worldgraph.find_one({"world.id": world_id, "world.kind": "game",
                                        "world.metadata.createdWith": CREATED_WITH}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="World not found")
    out = _record_out(doc)
    engine = out["engine"]
    spec = ENGINES.get(engine, {})
    highlights = []
    for k, v in (out["config"] or {}).items():
        t = spec.get("tunables", {}).get(k) or spec.get("choices", {}).get(k)
        if t:
            highlights.append({"key": k, "label": t[0], "value": v})
    owner = await db.users.find_one({"id": doc.get("owner_id")}, {"_id": 0, "name": 1})
    creator = ((owner or {}).get("name") or "A Frasberg builder").split(" ")[0]
    out.pop("world", None)
    out.pop("prompt", None)
    return {**out, "genre": spec.get("genre"), "highlights": highlights, "creator": creator,
            "npc_groups": [c["props"].get("label") for c in doc["world"]["scenes"][0]["components"]
                           if c.get("type") == "npc.group"],
            "track": doc["world"].get("track"), "race_rules": doc["world"].get("raceRuleset"),
            "vehicles": [v.get("name") for v in doc["world"].get("vehicleClasses") or []]}


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
    if plan.get("enriched_by") == "rules+frasberg":
        # The Frasberg server is answering again: upgrade this owner's older rules-only worlds in the background.
        task = asyncio.create_task(_refine_owner_backlog(owner))
        _BG.add(task)
        task.add_done_callback(_BG.discard)
    return _record_out(doc)


_BG: set = set()


async def _refine_owner_backlog(owner: str) -> None:
    try:
        docs = await db.worldgraph.find({"owner_id": owner, "world.metadata.createdWith": CREATED_WITH,
                                         "world.metadata.enrichedBy": {"$ne": "rules+frasberg"}}, {"_id": 0}).to_list(20)
        for d in docs:
            if not await _refine_doc(owner, d) and UPSTREAM_STATE.get("reachable") is False:
                break
    except Exception:  # noqa: BLE001
        logger.exception("background Frasberg refinement failed")


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
                choice = ENGINES[engine].get("choices", {}).get(k)
                if choice:
                    raise HTTPException(status_code=400, detail=f"'{k}' must be one of: {', '.join(choice[1])}")
                raise HTTPException(status_code=400, detail=f"Unknown setting '{k}' for {engine}")
            cfg[k] = cv
        sets["world.metadata.engineConfig"] = cfg
        comps = w["scenes"][0]["components"]
        for comp in comps:
            if comp["id"] == "engine":
                comp["props"] = {**comp["props"], **cfg}
            if comp["id"] == "npc-police" and "policeAggression" in cfg:
                comp["props"] = {**comp["props"], "aggression": cfg["policeAggression"]}
        sets["world.scenes"] = w["scenes"]
        if engine == "racer3d":
            n_laps = int(cfg.get("laps") or 0)
            if w.get("track"):
                sets["world.track.lengthMeters"] = int(cfg.get("lapLength") or 3000)
            if w.get("raceRuleset"):
                sets["world.raceRuleset.lapCount"] = n_laps or 1
                sets["world.raceRuleset.name"] = f"{n_laps}-lap race" if n_laps else "Endless overtake"
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


async def _refine_doc(owner: str, doc: dict) -> Optional[dict]:
    """Re-run the Frasberg server refinement on a saved world, keeping the owner's current settings as the base."""
    w = doc["world"]
    m = w.get("metadata") or {}
    prompt = m.get("prompt") or w.get("name") or ""
    engine = m.get("engine")
    plan = plan_from_rules(prompt, engine)
    plan["config"] = {**plan["config"], **(m.get("engineConfig") or {})}
    plan["title"], plan["tagline"] = w.get("name") or plan["title"], m.get("tagline") or plan["tagline"]
    env = m.get("environment") or {}
    plan["time_of_day"], plan["weather"] = env.get("time_of_day"), env.get("weather")
    refined = await refine_with_frasberg(prompt, plan, engine_locked=True)
    if refined.get("enriched_by") != "rules+frasberg":
        return None
    new_world = build_world(prompt, refined)
    new_world["id"] = w["id"]
    await db.worldgraph.update_one({"owner_id": owner, "world.id": w["id"]},
                                   {"$set": {"world": new_world, "updated_at": _now_ms()}})
    await _continuity_event(owner, "worldgraph.updated", w["id"])
    await _diagnostics_log(owner, "game-builder", {"op": "refine", "world_id": w["id"], "enriched_by": "rules+frasberg"})
    return await db.worldgraph.find_one({"owner_id": owner, "world.id": w["id"]}, {"_id": 0})


@router.post("/worlds/refine-pending")
async def refine_pending(user: dict = Depends(auth_module.get_current_user)):
    """Re-check the Frasberg server for every world that was built from rules only."""
    owner = user["id"]
    await _policy_check(owner, "worldgraph.update")
    docs = await db.worldgraph.find({"owner_id": owner, "world.metadata.createdWith": CREATED_WITH,
                                     "world.metadata.enrichedBy": {"$ne": "rules+frasberg"}}, {"_id": 0}) \
        .sort("updated_at", -1).to_list(20)
    refined = 0
    for d in docs:
        if await _refine_doc(owner, d):
            refined += 1
        elif UPSTREAM_STATE.get("reachable") is False:
            break  # server is down — stop instead of waiting on every world
    return {"pending": len(docs), "refined": refined, "server": UPSTREAM_STATE}


@router.post("/worlds/{world_id}/refine")
async def refine_world(world_id: str, user: dict = Depends(auth_module.get_current_user)):
    owner = user["id"]
    await _policy_check(owner, "worldgraph.update")
    doc = await _owned(user, world_id)
    out = await _refine_doc(owner, doc)
    if not out:
        raise HTTPException(status_code=503, detail=f"Frasberg server is not answering yet ({UPSTREAM_STATE['detail']}) — "
                                                    "your world keeps its rule-based settings.")
    return _record_out(out)


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
