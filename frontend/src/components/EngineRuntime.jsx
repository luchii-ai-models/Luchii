import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { Boxes, Play, Loader2, Search, Wand2, X, Link2, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";
import { Button } from "./ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const pct = (n) => `${Math.round((n || 0) * 100)}%`;

function Json({ value, testid }) {
  return (
    <pre data-testid={testid} className="mt-2 max-h-72 overflow-auto rounded-lg border border-white/10 bg-black/60 p-3 text-[11px] leading-relaxed text-neutral-300 whitespace-pre-wrap break-all">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function CoverageBar({ value }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
      <div className="h-full rounded-full bg-[#00F0FF] transition-all" style={{ width: pct(value) }} />
    </div>
  );
}

function RunPanel({ engine, onClose }) {
  const [detail, setDetail] = useState(null);
  const [input, setInput] = useState("Hello from Frasberg Creator");
  const [state, setState] = useState("{}");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showModel, setShowModel] = useState(false);

  useEffect(() => {
    setRes(null); setState("{}"); setDetail(null);
    axios.get(`${API}/engines/runtime/${engine.id}`).then(({ data }) => setDetail(data)).catch(() => {});
  }, [engine.id]);

  const run = async () => {
    let parsed;
    try { parsed = state.trim() ? JSON.parse(state) : {}; } catch { toast.error("State must be valid JSON"); return; }
    if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) { toast.error("State must be a JSON object"); return; }
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/engines/${engine.id}/execute`, { input, state: parsed });
      setRes(data);
    } catch (e) { toast.error(e?.response?.data?.detail || "Engine run failed"); } finally { setBusy(false); }
  };

  return (
    <div className="rounded-2xl border border-[#00F0FF]/30 bg-[#00F0FF]/[0.04] p-5" data-testid="engine-run-panel">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-display font-semibold text-lg text-white" data-testid="engine-run-title">{engine.name} Engine</div>
          <div className="text-xs text-neutral-500 break-words">{engine.package} · {engine.server_file}</div>
        </div>
        <button type="button" onClick={onClose} data-testid="engine-run-close" className="shrink-0 rounded-full p-1.5 text-neutral-400 hover:bg-white/10 hover:text-white" aria-label="Close">
          <X className="w-4 h-4" />
        </button>
      </div>

      {detail && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {detail.builders.map((b) => (
            <span key={b.fn} className="text-[11px] rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-neutral-300">
              {b.fn}() <span className="text-neutral-500">· reads {b.reads}</span>
            </span>
          ))}
          {detail.graph && <span className="text-[11px] rounded-full border border-white/10 px-2 py-0.5 text-neutral-400">{detail.graph}()</span>}
          {detail.envelope && <span className="text-[11px] rounded-full border border-white/10 px-2 py-0.5 text-neutral-400">{detail.envelope}()</span>}
          {detail.evolve && <span className="text-[11px] rounded-full border border-white/10 px-2 py-0.5 text-neutral-400">{detail.evolve}()</span>}
        </div>
      )}

      <div className="mt-4 grid md:grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs text-neutral-400">Input</span>
          <input data-testid="engine-run-input" value={input} onChange={(e) => setInput(e.target.value)} maxLength={2000}
            className="mt-1 w-full h-10 rounded-lg border border-white/10 bg-black/50 px-3 text-sm text-white outline-none focus:border-[#00F0FF]/60" />
        </label>
        <div className="flex items-end gap-2">
          <Button type="button" data-testid="engine-run-sample" variant="outline" disabled={!detail}
            onClick={() => detail && setState(JSON.stringify(detail.sample_state, null, 2))}
            className="rounded-full border-white/15 bg-transparent text-white hover:bg-white/10">
            <Wand2 className="w-4 h-4 mr-2" /> Load sample state
          </Button>
          <Button type="button" data-testid="engine-run-btn" onClick={run} disabled={busy}
            className="rounded-full bg-[#00F0FF] text-black hover:bg-[#00d4de] font-semibold">
            {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />} Run engine
          </Button>
        </div>
      </div>
      <label className="block mt-3">
        <span className="text-xs text-neutral-400">State (JSON the engine reads)</span>
        <textarea data-testid="engine-run-state" value={state} onChange={(e) => setState(e.target.value)} rows={5} spellCheck={false}
          className="mt-1 w-full rounded-lg border border-white/10 bg-black/50 p-3 font-mono text-xs text-neutral-200 outline-none focus:border-[#00F0FF]/60" />
      </label>

      {res && (
        <div className="mt-4" data-testid="engine-run-result">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="rounded-xl border border-white/10 bg-black/40 p-3">
              <div className="text-[11px] text-neutral-500">Evolution score</div>
              <div className="text-lg font-semibold text-white tabular-nums" data-testid="engine-run-score">{res.evolution?.evolutionScore ?? "—"}</div>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/40 p-3">
              <div className="text-[11px] text-neutral-500">Input coverage</div>
              <div className="text-lg font-semibold text-white tabular-nums" data-testid="engine-run-coverage">{pct(res.coverage)}</div>
              <CoverageBar value={res.coverage} />
            </div>
            <div className="rounded-xl border border-white/10 bg-black/40 p-3">
              <div className="text-[11px] text-neutral-500">Reads resolved</div>
              <div className="text-lg font-semibold text-white tabular-nums">{res.resolved}/{res.reads}</div>
            </div>
            <div className="rounded-xl border border-white/10 bg-black/40 p-3">
              <div className="text-[11px] text-neutral-500">Run time</div>
              <div className="text-lg font-semibold text-white tabular-nums">{res.duration_ms} ms</div>
            </div>
          </div>
          <p className="mt-3 text-sm text-neutral-200" data-testid="engine-run-output">{res.output}</p>
          {res.unresolved?.length > 0 && (
            <p className="mt-1 text-xs text-amber-300 break-words" data-testid="engine-run-unresolved">
              Missing in state: {res.unresolved.slice(0, 4).join(", ")}{res.unresolved.length > 4 ? ` +${res.unresolved.length - 4} more` : ""}
            </p>
          )}
          <div className="mt-3 text-xs text-neutral-400">Envelope</div>
          <Json value={res.envelope} testid="engine-run-envelope" />
          <button type="button" onClick={() => setShowModel((v) => !v)} data-testid="engine-run-model-toggle"
            className="mt-2 inline-flex items-center gap-1 text-xs text-[#00F0FF] hover:underline">
            {showModel ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />} Full model + evolution
          </button>
          {showModel && <Json value={{ model: res.model, evolution: res.evolution }} testid="engine-run-model" />}
        </div>
      )}
    </div>
  );
}

export default function EngineRuntime({ compact = false }) {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(null);
  const [chain, setChain] = useState([]);
  const [chainRes, setChainRes] = useState(null);
  const [chainBusy, setChainBusy] = useState(false);

  useEffect(() => { axios.get(`${API}/engines/runtime`).then(({ data: d }) => setData(d)).catch(() => setData({ engines: [], count: 0 })); }, []);

  const list = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (data?.engines || []).filter((e) => !s || e.name.toLowerCase().includes(s) || e.summary.toLowerCase().includes(s));
  }, [data, q]);

  const toggleChain = (id) => setChain((c) => (c.includes(id) ? c.filter((x) => x !== id) : c.length >= 12 ? c : [...c, id]));
  const runChain = async () => {
    setChainBusy(true);
    try {
      const { data: d } = await axios.post(`${API}/engines/chain`, { engines: chain, input: "Frasberg chain run", state: {} });
      setChainRes(d);
    } catch (e) { toast.error(e?.response?.data?.detail || "Chain run failed"); } finally { setChainBusy(false); }
  };

  return (
    <section data-testid="engine-runtime" className={compact ? "mt-14" : ""}>
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <h2 className="font-display font-bold text-2xl flex items-center gap-2"><Boxes className="w-5 h-5 text-[#00F0FF]" /> Engine Runtime</h2>
          <p className="text-sm text-neutral-400 mt-1" data-testid="engine-runtime-count">
            {data ? `${data.count} Frasberg engines from packages/*-engine, running live in the backend. Pick one and run it.` : "Loading engines…"}
          </p>
        </div>
        <div className="relative w-full md:w-72">
          <Search className="w-4 h-4 text-neutral-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input data-testid="engine-runtime-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search engines"
            className="w-full h-10 rounded-full border border-white/10 bg-white/[0.03] pl-9 pr-4 text-sm text-white outline-none focus:border-[#00F0FF]/60" />
        </div>
      </div>

      {open && <div className="mt-5"><RunPanel engine={open} onClose={() => setOpen(null)} /></div>}

      {chain.length > 0 && (
        <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.03] p-4" data-testid="engine-chain">
          <div className="flex flex-wrap items-center gap-2">
            <Link2 className="w-4 h-4 text-[#00F0FF]" />
            <span className="text-sm text-white">Chain:</span>
            {chain.map((id, i) => <span key={id} className="text-xs text-neutral-300">{i ? "→ " : ""}{id}</span>)}
            <div className="ml-auto flex gap-2">
              <Button type="button" data-testid="engine-chain-run" onClick={runChain} disabled={chainBusy}
                className="h-8 rounded-full bg-[#00F0FF] text-black hover:bg-[#00d4de] font-semibold text-xs">
                {chainBusy ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Play className="w-3.5 h-3.5 mr-1" />} Run chain
              </Button>
              <Button type="button" data-testid="engine-chain-clear" variant="outline" onClick={() => { setChain([]); setChainRes(null); }}
                className="h-8 rounded-full border-white/15 bg-transparent text-white hover:bg-white/10 text-xs">Clear</Button>
            </div>
          </div>
          {chainRes && (
            <div className="mt-3 space-y-1.5" data-testid="engine-chain-result">
              {chainRes.steps.map((s, i) => (
                <div key={`${s.engine}-${i}`} className="flex items-center gap-3 text-xs">
                  <span className="w-28 shrink-0 text-neutral-300">{i + 1}. {s.name}</span>
                  <div className="flex-1"><CoverageBar value={s.coverage} /></div>
                  <span className="w-12 text-right text-neutral-400 tabular-nums">{pct(s.coverage)}</span>
                </div>
              ))}
              <p className="text-[11px] text-neutral-500 pt-1">{`Each engine’s outputs feed the next engine’s state. Average coverage ${pct(chainRes.coverage)}.`}</p>
            </div>
          )}
        </div>
      )}

      <div className="mt-5 grid sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="engine-runtime-grid">
        {!data && Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-28 rounded-2xl border border-white/10 bg-white/[0.02] animate-pulse" />)}
        {list.map((e) => (
          <div key={e.id} data-testid={`engine-card-rt-${e.id}`}
            className={`rounded-2xl border p-4 flex flex-col gap-2 transition ${open?.id === e.id ? "border-[#00F0FF]/50 bg-[#00F0FF]/[0.05]" : "border-white/10 bg-white/[0.03] hover:border-white/20"}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="font-display font-semibold text-white">{e.name}</div>
              <span className="text-[10px] uppercase tracking-wider text-emerald-300">live</span>
            </div>
            <div className="text-xs text-neutral-400 break-words">{e.summary}</div>
            <div className="text-[11px] text-neutral-600">{e.builders.length} builder{e.builders.length === 1 ? "" : "s"} · {e.model || "model"}</div>
            <div className="mt-auto flex gap-2 pt-1">
              <button type="button" data-testid={`engine-open-${e.id}`} onClick={() => { setOpen(e); setTimeout(() => document.querySelector("[data-testid=engine-run-panel]")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60); }}
                className="inline-flex items-center h-8 rounded-full bg-[#00F0FF] px-3 text-xs font-semibold text-black hover:bg-[#00d4de]">
                <Play className="w-3.5 h-3.5 mr-1" /> Run
              </button>
              <button type="button" data-testid={`engine-chain-add-${e.id}`} onClick={() => toggleChain(e.id)} aria-pressed={chain.includes(e.id)}
                className={`inline-flex items-center h-8 rounded-full border px-3 text-xs ${chain.includes(e.id) ? "border-[#00F0FF]/60 text-[#00F0FF]" : "border-white/15 text-neutral-300 hover:bg-white/10"}`}>
                <Link2 className="w-3.5 h-3.5 mr-1" /> {chain.includes(e.id) ? "In chain" : "Chain"}
              </button>
            </div>
          </div>
        ))}
        {data && !list.length && <p className="text-sm text-neutral-500" data-testid="engine-runtime-empty">No engine matches “{q}”.</p>}
      </div>
    </section>
  );
}
