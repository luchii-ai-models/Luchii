"""Frasberg Engine Runtime: the TypeScript engines in packages/*-engine, executed in the backend.

scripts/build_engine_ir.js compiles every exported engine function to ESTree JSON (engines_ir.json). This module
interprets that IR, so the engines run exactly as written, with the following changes so results are real:

- Property reads on missing data return null instead of throwing (JS would crash on `undefined.x`); every such read
  is reported in `unresolved`.
- Math.random() inside evolve() becomes the engine's input coverage: the share of the property reads the engine
  made that were present in the supplied state. Elsewhere (the checksum idiom Math.random().toString(36).slice(2))
  it becomes a deterministic hash of the function's input, so the same input always gives the same checksum.
- Date.now() is the real time; ids are UUID4.

Pipeline for one engine: every builder(state) -> graph(merged builder output) -> model -> envelope(model) ->
evolve(model) -> output "<Name> processed: <input>" (same as apps/engine-server/<id>-execute.ts).
"""
import hashlib
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Optional

IR_PATH = Path(__file__).parent / "engines_ir.json"
_IR = json.loads(IR_PATH.read_text())["engines"]

NAMES = {"groundtruth": "Ground Truth", "zeropoint": "Zero Point"}


class Undefined:
    __slots__ = ()

    def __repr__(self):
        return "undefined"


UNDEF = Undefined()


class EngineError(Exception):
    pass


class _Return(Exception):
    def __init__(self, value):
        self.value = value


def _canon(v: Any) -> str:
    return json.dumps(_to_json(v), sort_keys=True, separators=(",", ":"), default=str)


def _hash_unit(*parts: Any) -> float:
    h = hashlib.sha256("|".join(_canon(p) for p in parts).encode()).hexdigest()
    return int(h[:13], 16) / float(16 ** 13)


def _to_json(v: Any) -> Any:
    if v is UNDEF:
        return None
    if isinstance(v, dict):
        return {k: _to_json(x) for k, x in v.items() if x is not UNDEF}
    if isinstance(v, list):
        return [_to_json(x) for x in v]
    if isinstance(v, float) and v.is_integer() and abs(v) < 2 ** 53:
        return int(v)
    return v


def _num_to_str(n: float, radix: int = 10) -> str:
    if radix == 10:
        return str(int(n)) if float(n).is_integer() else repr(float(n))
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    neg, n = n < 0, abs(n)
    ip, fp = int(n), n - int(n)
    s = ""
    while True:
        s = digits[ip % radix] + s
        ip //= radix
        if not ip:
            break
    if fp:
        s += "."
        for _ in range(11):
            fp *= radix
            d = int(fp)
            s += digits[d]
            fp -= d
            if fp <= 0:
                break
    return ("-" if neg else "") + s


def _js_eq(a, b) -> bool:
    if a is UNDEF or a is None:
        return b is UNDEF if a is UNDEF else b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def _truthy(v) -> bool:
    if v is UNDEF or v is None or v is False:
        return False
    if isinstance(v, (int, float)) and (v == 0 or (isinstance(v, float) and math.isnan(v))):
        return False
    if v == "":
        return False
    return True


class _Run:
    """One engine execution: tracks property reads for coverage and the unresolved paths."""

    def __init__(self, engine_id: str):
        self.engine_id = engine_id
        self.reads = 0
        self.missing = 0
        self.unresolved: list = []
        self.in_evolve = False
        self.coverage = 1.0
        self.params: set = set()
        self.label = "state"

    # ----- expressions -----
    def path_of(self, node) -> str:
        if node["type"] == "Identifier":
            return self.label if node["name"] in self.params else node["name"]
        if node["type"] == "MemberExpression" and not node.get("computed"):
            return f"{self.path_of(node['object'])}.{node['property']['name']}"
        return "?"

    def ev(self, node, env: dict, fn: str):
        t = node["type"]
        if t == "Literal":
            return node["value"]
        if t == "Identifier":
            n = node["name"]
            if n == "undefined":
                return UNDEF
            if n in env:
                return env[n]
            raise EngineError(f"{fn}: unknown identifier {n}")
        if t == "ObjectExpression":
            out: dict = {}
            for p in node["properties"]:
                if p["type"] == "SpreadElement":
                    src = self.ev(p["argument"], env, fn)
                    if isinstance(src, dict):
                        out.update(src)
                    continue
                key = p["key"]["name"] if p["key"]["type"] == "Identifier" else str(p["key"]["value"])
                out[key] = self.ev(p["value"], env, fn)
            return out
        if t == "ArrayExpression":
            return [self.ev(e, env, fn) for e in node["elements"]]
        if t == "MemberExpression":
            obj = self.ev(node["object"], env, fn)
            key = self.ev(node["property"], env, fn) if node.get("computed") else node["property"]["name"]
            if obj is Math_:
                return ("Math", key)
            if obj is Date_:
                return ("Date", key)
            if isinstance(obj, (str, float, int)) and not isinstance(obj, bool) and key in ("toString", "slice", "length"):
                return ("method", obj, key) if key != "length" else len(obj) if isinstance(obj, str) else UNDEF
            if isinstance(obj, list) and key == "length":
                return len(obj)
            self.reads += 1
            val = obj.get(key, UNDEF) if isinstance(obj, dict) else UNDEF
            if val is UNDEF:
                self.missing += 1
                p = self.path_of(node)
                if len(self.unresolved) < 40 and p not in self.unresolved:
                    self.unresolved.append(p)
            return val
        if t == "CallExpression":
            callee = self.ev(node["callee"], env, fn)
            args = [self.ev(a, env, fn) for a in node["arguments"]]
            if callee == ("Date", "now"):
                return int(time.time() * 1000)
            if callee == ("Math", "random"):
                if self.in_evolve:
                    return self.coverage
                return _hash_unit(self.engine_id, fn, env.get("__args__"))
            if isinstance(callee, tuple) and callee[0] == "Math":
                f = getattr(math, callee[1], None)
                if callee[1] in ("min", "max"):
                    return (min if callee[1] == "min" else max)(args)
                if callable(f):
                    return f(*args)
            if isinstance(callee, tuple) and callee[0] == "method":
                _, val, name = callee
                if name == "toString":
                    return _num_to_str(val, int(args[0]) if args else 10) if not isinstance(val, str) else val
                if name == "slice" and isinstance(val, str):
                    a = int(args[0]) if args else 0
                    b = int(args[1]) if len(args) > 1 else None
                    return val[a:b]
            raise EngineError(f"{fn}: unsupported call {self.path_of(node['callee'])}")
        if t == "ConditionalExpression":
            return self.ev(node["consequent"] if _truthy(self.ev(node["test"], env, fn)) else node["alternate"], env, fn)
        if t == "BinaryExpression":
            a, b, op = self.ev(node["left"], env, fn), self.ev(node["right"], env, fn), node["operator"]
            if op in ("===", "=="):
                return _js_eq(a, b)
            if op in ("!==", "!="):
                return not _js_eq(a, b)
            if op in ("+", "-", "*", "/", ">", "<", ">=", "<="):
                if op == "+" and (isinstance(a, str) or isinstance(b, str)):
                    return f"{a}{b}"
                if not all(isinstance(x, (int, float)) for x in (a, b)):
                    return False if op in (">", "<", ">=", "<=") else float("nan")
                return {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else float("inf"),
                        ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
            raise EngineError(f"{fn}: unsupported operator {op}")
        if t == "LogicalExpression":
            a = self.ev(node["left"], env, fn)
            if node["operator"] == "||":
                return a if _truthy(a) else self.ev(node["right"], env, fn)
            if node["operator"] == "&&":
                return self.ev(node["right"], env, fn) if _truthy(a) else a
            if node["operator"] == "??":
                return a if a not in (None, UNDEF) else self.ev(node["right"], env, fn)
        if t == "UnaryExpression":
            v = self.ev(node["argument"], env, fn)
            if node["operator"] == "!":
                return not _truthy(v)
            if node["operator"] == "-":
                return -v
            if node["operator"] == "typeof":
                return "undefined" if v is UNDEF else "object" if isinstance(v, (dict, list)) or v is None else \
                    "string" if isinstance(v, str) else "boolean" if isinstance(v, bool) else "number"
        if t == "TemplateLiteral":
            out = ""
            for i, q in enumerate(node["quasis"]):
                out += q["value"]["cooked"]
                if i < len(node["expressions"]):
                    out += str(_to_json(self.ev(node["expressions"][i], env, fn)))
            return out
        raise EngineError(f"{fn}: unsupported syntax {t}")

    # ----- statements -----
    def ex(self, node, env: dict, fn: str):
        t = node["type"]
        if t == "BlockStatement":
            for s in node["body"]:
                self.ex(s, env, fn)
        elif t == "ReturnStatement":
            raise _Return(self.ev(node["argument"], env, fn) if node.get("argument") else UNDEF)
        elif t == "VariableDeclaration":
            for d in node["declarations"]:
                env[d["id"]["name"]] = self.ev(d["init"], env, fn) if d.get("init") else UNDEF
        elif t == "IfStatement":
            if _truthy(self.ev(node["test"], env, fn)):
                self.ex(node["consequent"], env, fn)
            elif node.get("alternate"):
                self.ex(node["alternate"], env, fn)
        elif t == "ExpressionStatement":
            self.ev(node["expression"], env, fn)
        else:
            raise EngineError(f"{fn}: unsupported statement {t}")

    def call(self, f: dict, arg: Any, label: str = "state"):
        self.params, self.label = set(f["params"]), label
        env = {"Math": Math_, "Date": Date_, "__args__": arg}
        for p in f["params"]:
            env[p] = arg
        try:
            self.ex(f["body"], env, f["name"])
        except _Return as r:
            return r.value
        return UNDEF


Math_ = object()
Date_ = object()


# ---------- registry ----------
def _member_paths(node, param: str, out: list, eq: dict):
    """Collect `param.a.b.c` read paths (and literals they are compared to, for the sample-state builder)."""
    if isinstance(node, list):
        for x in node:
            _member_paths(x, param, out, eq)
        return
    if not isinstance(node, dict):
        return
    if node.get("type") == "BinaryExpression" and node["operator"] in ("===", "==") and \
            node["left"].get("type") == "MemberExpression" and node["right"].get("type") == "Literal":
        p = _chain(node["left"])
        if p and p[0] == param:
            eq[".".join(p[1:])] = node["right"]["value"]
    if node.get("type") == "MemberExpression":
        p = _chain(node)
        if p and p[0] == param and len(p) > 1:
            s = ".".join(p[1:])
            if s not in out:
                out.append(s)
            return
    for v in node.values():
        if isinstance(v, (dict, list)):
            _member_paths(v, param, out, eq)


def _chain(node) -> Optional[list]:
    if node.get("type") == "Identifier":
        return [node["name"]]
    if node.get("type") == "MemberExpression" and not node.get("computed"):
        c = _chain(node["object"])
        return c + [node["property"]["name"]] if c else None
    return None


def _camel(s: str) -> str:
    parts = s.replace("_", "-").split("-")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _leaf_paths(paths: list) -> list:
    """Drop paths that are prefixes of longer ones (a.b when a.b.c is read)."""
    return [p for p in paths if not any(q.startswith(p + ".") for q in paths)]


def _build_registry() -> dict:
    reg = {}
    for eid, e in _IR.items():
        model_fields = [f["name"] for f in (e.get("model") or {}).get("fields", [])]
        builders, graph, envelope, evolve = [], None, None, None
        for file, fns in e["files"].items():
            for f in fns:
                if file == "evolve":
                    evolve = f
                elif file.endswith("-graph") or f["name"].endswith("Graph"):
                    graph = graph or f
                elif file.endswith("-envelope"):
                    envelope = f
                else:
                    reads, eq = [], {}
                    for p in f["params"]:
                        _member_paths(f["body"], p, reads, eq)
                    target = next((m for m in model_fields if m.lower() == _camel(file).lower()), _camel(file))
                    builders.append({"file": file, "fn": f["name"], "param": (f["params"] or [None])[0],
                                     "field": target, "reads": reads, "eq": eq, "ir": f})
        id_field = next((m for m in model_fields if m.endswith("Id")), f"{_camel(eid)}Id")
        graph_field = next((m for m in model_fields if m.endswith("Graph")), f"{_camel(eid)}Graph")
        reg[eid] = {"id": eid, "name": NAMES.get(eid, eid.capitalize()), "package": e["package"],
                    "model": e.get("model"), "id_field": id_field, "graph_field": graph_field,
                    "builders": builders, "graph": graph, "envelope": envelope, "evolve": evolve}
    return reg


REGISTRY = _build_registry()


def _set_path(d: dict, path: str, value):
    keys = path.split(".")
    cur = d
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur.setdefault(keys[-1], value)


def sample_state(eid: str) -> dict:
    """A state object that satisfies every property the engine reads, using the values its ternaries test for."""
    e = REGISTRY[eid]
    out: dict = {}
    for b in e["builders"]:
        for p in _leaf_paths(b["reads"]):
            _set_path(out, p, b["eq"].get(p, f"sample-{p.split('.')[-1]}"))
    return out


def describe(eid: str, full: bool = False) -> dict:
    e = REGISTRY[eid]
    d = {"id": eid, "name": e["name"], "package": e["package"], "server_file": f"apps/engine-server/{eid}-execute.ts",
         "builders": [{"fn": b["fn"], "file": f"{b['file']}.ts", "field": b["field"], "param": b["param"],
                       "reads": len(_leaf_paths(b["reads"]))} for b in e["builders"]],
         "graph": e["graph"]["name"] if e["graph"] else None,
         "envelope": e["envelope"]["name"] if e["envelope"] else None,
         "evolve": e["evolve"]["name"] if e["evolve"] else None,
         "model": e["model"]["name"] if e["model"] else None,
         "fields": [f["name"] for f in (e["model"] or {}).get("fields", [])]}
    d["summary"] = (f"{' + '.join(b['field'] for b in e['builders']) or 'no builders'} → "
                    f"{e['graph_field']} → envelope → evolution")
    if full:
        d["reads"] = {b["fn"]: _leaf_paths(b["reads"]) for b in e["builders"]}
        d["sample_state"] = sample_state(eid)
    return d


def catalogue() -> list:
    return [describe(k) for k in sorted(REGISTRY)]


def execute(eid: str, input_text: str = "", state: Optional[dict] = None) -> dict:
    if eid not in REGISTRY:
        raise KeyError(eid)
    e = REGISTRY[eid]
    state = state if isinstance(state, dict) else {}
    t0 = time.perf_counter()
    run = _Run(eid)
    built, merged = {}, {}
    for b in e["builders"]:
        out = run.call(b["ir"], state)
        built[b["field"]] = out
        if isinstance(out, dict):
            merged.update(out)
    run.coverage = round(1 - run.missing / run.reads, 4) if run.reads else 1.0
    reads, missing = run.reads, run.missing
    graph = run.call(e["graph"], merged, "built") if e["graph"] else None
    model = {e["id_field"]: str(uuid.uuid4()), **built, e["graph_field"]: graph, "createdAt": int(time.time() * 1000)}
    envelope = run.call(e["envelope"], model, "model") if e["envelope"] else None
    run.in_evolve = True
    evolution = run.call(e["evolve"], model, "model") if e["evolve"] else None
    return {
        "engine": eid, "name": e["name"], e["id_field"]: model[e["id_field"]],
        "evolution": _to_json(evolution),
        "output": f"{e['name']} processed: {input_text}",
        "model": _to_json(model), "envelope": _to_json(envelope),
        "coverage": run.coverage, "reads": reads, "resolved": reads - missing,
        "unresolved": run.unresolved[:20],
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        "executed_at": int(time.time() * 1000),
    }


def chain(ids: list, input_text: str = "", state: Optional[dict] = None) -> dict:
    """Run engines in order; each engine's builder outputs are merged into the state the next engine sees."""
    st = dict(state or {})
    steps = []
    for eid in ids:
        r = execute(eid, input_text, st)
        steps.append(r)
        for v in r["model"].values():
            if isinstance(v, dict):
                st.update(v)
        st.update({k: v for k, v in r["model"].items() if isinstance(v, dict)})
    return {"steps": steps, "final_state_keys": sorted(st.keys())[:200],
            "coverage": round(sum(s["coverage"] for s in steps) / len(steps), 4) if steps else None}
