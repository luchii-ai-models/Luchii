"""Engine rules from config/emergent/engines/*.prompt.md, applied to the platform's real engines.

The prompt files were written for an AI orchestrator. Rules that map onto this platform are enforced in code (see
ENFORCEMENT); the rest are published as reference so API users can see them. Loaded once at import.
"""
from pathlib import Path
from typing import Optional

_REPO_PROMPTS = Path(__file__).resolve().parents[1] / "config" / "emergent" / "engines"
_VENDORED = Path(__file__).resolve().parent / "assets" / "engine_prompts"   # copy shipped with the backend
PROMPT_DIR = _REPO_PROMPTS if _REPO_PROMPTS.is_dir() else _VENDORED

# engine id -> (permission named in the prompt, FRASBERG_KEY_ROUTES feature that grants it, real platform engine)
PERMISSIONS = {
    "image": ("image_generation", "image", "Luchii Nova-Muse / Dreamline / Vision (/api/generate)"),
    "video": ("video_generation", "video", "Luchii Cinematica / Animus on Frasberg Motion GPUs (/api/video)"),
    "music": ("music_generation", "music", "Luchii Harmonia (/api/music)"),
    "voice": ("text_to_speech", "tts", "Luchii voices (/api/voice/speak)"),
    "stt": ("speech_to_text", "stt", "Luchii transcription (/api/sts)"),
    "audio": ("audio_native", "audio", "Luchii audio tools"),
    "game-logic": (None, None, "Reference only - no racing simulation runs on this platform"),
}

# Short, cost-efficient defaults ("Default to short clips / short compositions unless long-form is requested").
DEFAULT_DURATION = {"video": 5, "music": 15}

# How each rule is applied here. Matched against the rule text (lower-case substring).
ENFORCEMENT = [
    ("only activate if the user explicitly", "enforced",
     "Agents only run the engines named in the task (type) or bundle (include); nothing is added implicitly."),
    ("requires ", "enforced",
     "API-key callers (X-Frasberg-Key) need a key routed to this engine's feature; otherwise the request is declined in one sentence (403)."),
    ("only proceed if music_generation", "enforced",
     "API-key callers need a key routed to the music feature; otherwise declined in one sentence (403)."),
    ("if permission", "enforced", "Declines are a single sentence naming the missing permission."),
    ("decline with one sentence", "enforced", "Declines are a single sentence."),
    ("default to short", "enforced", "Video defaults to 5s when no duration is given (max 15s)."),
    ("short, cost-efficient", "enforced", "Music/audio default to short renders (music 15s when no duration is given)."),
    ("keep processing jobs short", "enforced", "Audio jobs use the short defaults."),
    ("never generate new music", "enforced", "Audio tools never call the music engine; agent tasks cannot route audio to music."),
    ("only use api-key compatible", "enforced", "Image calls to Frasberg use API keys only (no session auth)."),
    ("do not use endpoints requiring session auth", "enforced", "Image calls to Frasberg use API keys only."),
    ("avoid unnecessary multimodal stacking", "enforced",
     "A bundle renders only the engines listed in include; a single task renders exactly one engine."),
    ("primary heavy modality", "reference", "Video runs first on the Frasberg GPU (AWS, then Kaggle), then Lite."),
]


def _parse(path: Path) -> dict:
    text = path.read_text()
    eid = path.name.replace("-engine.prompt.md", "")
    title = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    sections, cur = [], {"heading": "Rules", "rules": []}
    for ln in text.splitlines()[1:]:
        s = ln.strip()
        if not s:
            continue
        if s.endswith(":") and not s.startswith("-"):
            if cur["rules"]:
                sections.append(cur)
            cur = {"heading": s[:-1], "rules": []}
        elif s.startswith("-"):
            rule = s.lstrip("- ").strip()
            how = next(((st, note) for key, st, note in ENFORCEMENT if key in rule.lower()), ("reference", None))
            cur["rules"].append({"text": rule, "status": how[0], "how": how[1]})
    if cur["rules"]:
        sections.append(cur)
    perm, feature, real = PERMISSIONS.get(eid, (None, None, None))
    if eid == "game-logic":
        for sec in sections:
            for r in sec["rules"]:
                r.update(status="reference", how=None)
    return {"id": eid, "title": title, "permission": perm, "feature": feature, "platform_engine": real,
            "default_duration": DEFAULT_DURATION.get(eid), "sections": sections,
            "source": f"config/emergent/engines/{path.name}"}


def load() -> dict:
    out = {}
    if PROMPT_DIR.is_dir():
        for p in sorted(PROMPT_DIR.glob("*-engine.prompt.md")):
            r = _parse(p)
            out[r["id"]] = r
    return out


RULES = load()


def decline_sentence(engine: str) -> str:
    perm = PERMISSIONS.get(engine, (None,))[0] or f"{engine}"
    return f"This API key does not have {perm} permission, so the {engine} engine declined."


def key_allowed(engine: str, key_prefix: Optional[str], routes: dict) -> bool:
    """routes = FRASBERG_KEY_ROUTES ({feature: [8-char key prefixes]}). Unrouted features stay open."""
    feature = PERMISSIONS.get(engine, (None, None))[1]
    if not feature or feature not in routes or not key_prefix:
        return True
    return any(key_prefix.startswith(p) or p.startswith(key_prefix) for p in routes[feature])


def default_duration(kind: str, requested: Optional[int]) -> int:
    return requested if requested is not None else DEFAULT_DURATION.get(kind, 8)


def summary() -> list:
    out = []
    for r in RULES.values():
        rules = [x for s in r["sections"] for x in s["rules"]]
        out.append({"id": r["id"], "title": r["title"], "permission": r["permission"],
                    "platform_engine": r["platform_engine"], "rules": len(rules),
                    "enforced": sum(1 for x in rules if x["status"] == "enforced")})
    return out

