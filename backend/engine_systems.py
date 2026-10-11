"""Frasberg system engines (packages/{governance,policy,diagnostics,worldgraph}-engine, packages/engine-flow,
packages/engine/src/unified-enforce.ts, apps/engine-server/*-enforce.ts) ported to Python.
The TypeScript versions read Supabase RPCs; here the same data lives in MongoDB."""
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import engine_runtime

db = None

FLOW_DOMAINS = ["identity", "persona", "character", "role", "function", "task", "action", "behavior", "pattern", "structure"]
AWARENESS_PATH = ["consciousnessPerception", "mindAwareness", "cognitiveMindspace", "reasoningArchitecture", "logicCognition",
                  "designReasoning", "blueprintLogic", "architecturePlan", "structureBlueprint", "patternArchitecture",
                  "exchangeStructure", "interactionFlow", "influenceExchange", "fieldPropagation", "vectorInfluence",
                  "forceDirection", "dynamicsVector", "motionForce", "travelKinetics", "navigationMotion", "routeDecision",
                  "pathNavigation", "directionMap", "pathwayDirection"]
DIAG_COMPONENTS = ["gateway", "router", "engine"]

SYSTEMS = [
    {"id": "governance", "name": "Governance", "package": "packages/governance-engine",
     "summary": "Global and per-owner action blocks, checked before every engine run."},
    {"id": "policy", "name": "Policy", "package": "packages/policy-engine",
     "summary": "Per-owner blocked actions, checked before every engine run."},
    {"id": "diagnostics", "name": "Diagnostics", "package": "packages/diagnostics-engine",
     "summary": "Logs every gateway, router and engine event per owner and aggregates them."},
    {"id": "worldgraph", "name": "WorldGraph", "package": "packages/worldgraph-engine",
     "summary": "Persistent continuity state and the owner's identity graph."},
    {"id": "engine-flow", "name": "Engine Flow", "package": "packages/engine-flow",
     "summary": "Identity → persona → character → role → function → task → action → behavior → pattern → structure."},
    {"id": "unified-enforce", "name": "Unified Enforce", "package": "packages/engine (unified-enforce.ts)",
     "summary": "Identity, continuity, diagnostics and policy enforcement on every engine call."},
]


class EnforceError(Exception):
    pass


def init(database):
    global db
    db = database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(items) -> list:
    return sorted({str(x).strip() for x in (items or []) if str(x).strip()})[:200]


# ---------- governance ----------
async def load_governance(owner: str) -> dict:
    g = await db.engine_governance.find_one({"owner": "*"}, {"_id": 0}) or {}
    o = await db.engine_governance.find_one({"owner": owner}, {"_id": 0}) or {}
    return {"globalBlock": g.get("block", []), "ownerBlock": o.get("block", [])}


async def save_governance(owner: str, block: list, by: str) -> dict:
    await db.engine_governance.update_one({"owner": owner}, {"$set": {"block": _clean(block), "updated_by": by,
                                                                      "updated_at": _now()}}, upsert=True)
    return await load_governance(owner if owner != "*" else by)


def enforce_governance(gov: Optional[dict], action: str) -> dict:
    if not gov:
        return {"allowed": True}
    if action in (gov.get("globalBlock") or []):
        return {"allowed": False, "reason": "Globally blocked by governance"}
    if action in (gov.get("ownerBlock") or []):
        return {"allowed": False, "reason": "Owner-level governance block"}
    return {"allowed": True}


# ---------- policy ----------
async def load_policy(owner: str) -> dict:
    p = await db.engine_policy.find_one({"owner": owner}, {"_id": 0}) or {}
    return {"blockedActions": p.get("blockedActions", [])}


async def save_policy(owner: str, blocked: list, by: str) -> dict:
    await db.engine_policy.update_one({"owner": owner}, {"$set": {"blockedActions": _clean(blocked), "updated_by": by,
                                                                  "updated_at": _now()}}, upsert=True)
    return await load_policy(owner)


def enforce_policy(policy: Optional[dict], action: str) -> dict:
    if policy and action in (policy.get("blockedActions") or []):
        return {"allowed": False, "reason": "Action blocked by policy"}
    return {"allowed": True}


# ---------- diagnostics ----------
async def log_diagnostics(owner: str, component: str, payload: dict):
    await db.engine_diagnostics.insert_one({"id": str(uuid.uuid4()), "owner_id": owner, "component": component,
                                            "payload": payload, "created_at": _now()})


async def fetch_diagnostics(owner: str, component: str, limit: int = 50) -> list:
    return await db.engine_diagnostics.find({"owner_id": owner, "component": component}, {"_id": 0}) \
        .sort("created_at", -1).to_list(limit)


async def aggregate_diagnostics(owner: str) -> dict:
    out = {}
    for c in DIAG_COMPONENTS:
        total = await db.engine_diagnostics.count_documents({"owner_id": owner, "component": c})
        blocked = await db.engine_diagnostics.count_documents({"owner_id": owner, "component": c, "payload.allowed": False})
        out[c] = {"events": total, "blocked": blocked, "recent": await fetch_diagnostics(owner, c, 10)}
    return out


# ---------- worldgraph ----------
async def load_continuity(owner: str, cid: str) -> dict:
    d = await db.engine_continuity.find_one({"owner": owner, "continuity": cid}, {"_id": 0})
    return d or {"owner": owner, "continuity": cid, "state": {}, "runs": 0}


async def update_continuity(owner: str, cid: str, new_state: dict, engine: str):
    state = {k: v for k, v in new_state.items()}
    if len(str(state)) > 60_000:
        state = dict(list(state.items())[-40:])
    await db.engine_continuity.update_one(
        {"owner": owner, "continuity": cid},
        {"$set": {"state": state, "last_engine": engine, "updated_at": _now()}, "$inc": {"runs": 1},
         "$setOnInsert": {"created_at": _now()}}, upsert=True)


async def list_continuity(owner: str) -> list:
    return await db.engine_continuity.find({"owner": owner}, {"_id": 0, "state": 0}).sort("updated_at", -1).to_list(50)


async def delete_continuity(owner: str, cid: str) -> bool:
    return (await db.engine_continuity.delete_one({"owner": owner, "continuity": cid})).deleted_count > 0


async def load_identity(owner: str) -> dict:
    rows = await db.engine_diagnostics.aggregate([
        {"$match": {"owner_id": owner, "component": "engine", "payload.allowed": True}},
        {"$group": {"_id": "$payload.engine", "runs": {"$sum": 1}, "last": {"$max": "$created_at"}}},
        {"$sort": {"runs": -1}}]).to_list(100)
    nodes = [{"engine": r["_id"], "runs": r["runs"], "last_run": r["last"]} for r in rows if r["_id"]]
    return {"owner": owner, "nodes": nodes, "edges": [{"from": owner, "to": n["engine"]} for n in nodes],
            "continuity": await list_continuity(owner)}


# ---------- unified enforce ----------
async def unified_enforce(engine: str, owner: str, context: dict) -> dict:
    """apps/engine-server/unified-enforce.ts: identity → continuity → diagnostics → policy (+ governance)."""
    action = context.get("action") or f"execute:{engine}"
    if not (owner or "").strip():
        raise EnforceError("Owner identity must not be empty.")
    cid = context.get("continuity")
    if cid is not None and (not isinstance(cid, str) or not cid.strip() or len(cid) > 256):
        raise EnforceError("Continuity identifier must be a non-empty string of at most 256 characters.")
    request_id = context.get("requestId") or str(uuid.uuid4())
    await log_diagnostics(owner, "gateway", {"requestId": request_id, "auth": owner.split(":", 1)[0], "allowed": True})
    await log_diagnostics(owner, "router", {"requestId": request_id, "route": engine, "action": action, "allowed": True})
    pol = enforce_policy(await load_policy(owner), action)
    gov = enforce_governance(await load_governance(owner), action)
    verdict = pol if not pol["allowed"] else gov
    await log_diagnostics(owner, "engine", {"engine": engine, "action": action, "requestId": request_id,
                                            "continuity": cid, "allowed": verdict["allowed"],
                                            "reason": verdict.get("reason")})
    if not verdict["allowed"]:
        raise EnforceError(f"{verdict['reason']} ({action})")
    return {"requestId": request_id, "action": action, "allowed": True}


# ---------- engine flow ----------
def is_engine_awareness(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("perception"), dict) or not isinstance(value.get("field"), dict):
        return False
    cur = value["perception"]
    for k in AWARENESS_PATH:
        if not isinstance(cur, dict):
            return False
        cur = cur.get(k)
    return isinstance(cur, dict) and isinstance(cur.get("structuralPathway"), str) and \
        isinstance(value["field"].get("harmonyAwarenessField"), str)


def sample_awareness() -> dict:
    leaf: dict = {"structuralPathway": "frasberg-pathway"}
    for k in reversed(AWARENESS_PATH):
        leaf = {k: leaf}
    return {"perception": leaf, "field": {"harmonyAwarenessField": "frasberg-harmony"}}


def flow(domain: str, awareness: dict, input_text: str, state: Optional[dict] = None) -> dict:
    """packages/engine-flow executeEngine: build every stage up to `domain`, each feeding the next."""
    if domain not in FLOW_DOMAINS:
        raise EnforceError(f"Unknown domain {domain}")
    t0 = time.perf_counter()
    stages = FLOW_DOMAINS[: FLOW_DOMAINS.index(domain) + 1]
    res = engine_runtime.chain(stages, input_text, {**(state or {}), "awareness": awareness})
    last = res["steps"][-1]
    id_field = "functionId" if domain == "function" else f"{domain}Id"
    return {id_field: last.get(id_field) or last["model"].get(id_field), "evolution": last["evolution"],
            "output": f"{last['name']} processed: {input_text}", "domain": domain,
            "awareness_valid": is_engine_awareness(awareness),
            "stages": [{"engine": s["engine"], "name": s["name"], "coverage": s["coverage"]} for s in res["steps"]],
            "coverage": res["coverage"], "duration_ms": round((time.perf_counter() - t0) * 1000, 2)}


# ---------- creations (image / video / music jobs) ----------
CREATION_KINDS = ("image", "video", "music")


async def check_creation(kind: str, owner: str, prompt: str) -> dict:
    """Unified-enforce `create:<kind>` for the owner, then run the Engine Flow over the creation. Raises EnforceError."""
    enf = await unified_enforce(f"create-{kind}", owner, {"action": f"create:{kind}"})
    res = flow("structure", sample_awareness(), prompt[:2000], {"creation": {"kind": kind, "prompt": prompt[:500]}})
    rec = {"requestId": enf["requestId"], "action": enf["action"], "flow_id": res.get("structureId"),
           "score": (res.get("evolution") or {}).get("evolutionScore"), "coverage": res["coverage"],
           "stages": len(res["stages"]), "duration_ms": res["duration_ms"], "checked_at": _now()}
    await log_diagnostics(owner, "engine", {"engine": "engine-flow", "action": f"flow:create:{kind}", "allowed": True,
                                            "requestId": enf["requestId"], "creation": kind, "flow_id": rec["flow_id"],
                                            "score": rec["score"]})
    return rec


async def creation_stats(limit: int = 15) -> dict:
    match = {"component": "engine", "payload.action": {"$in": [f"create:{k}" for k in CREATION_KINDS]}}
    out = {"kinds": {}}
    for k in CREATION_KINDS:
        q = {"component": "engine", "payload.action": f"create:{k}"}
        out["kinds"][k] = {"checked": await db.engine_diagnostics.count_documents(q),
                           "blocked": await db.engine_diagnostics.count_documents({**q, "payload.allowed": False})}
    out["recent"] = await db.engine_diagnostics.find(match, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return out
