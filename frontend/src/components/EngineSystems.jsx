import React, { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { Network, Play, Loader2, ShieldBan, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "./ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const field = "w-full h-10 rounded-lg border border-white/10 bg-black/50 px-3 text-sm text-white outline-none focus:border-[#00F0FF]/60";
const toList = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

function BlockEditor({ label, testid, value, onSave }) {
  const [text, setText] = useState(value.join(", "));
  useEffect(() => setText(value.join(", ")), [value]);
  return (
    <div className="rounded-xl border border-white/10 bg-black/40 p-3">
      <div className="text-xs text-neutral-400 mb-1">{label}</div>
      <div className="flex gap-2">
        <input data-testid={`${testid}-input`} value={text} onChange={(e) => setText(e.target.value)} placeholder="execute:mind, flow:task" className={field} />
        <Button type="button" data-testid={`${testid}-save`} onClick={() => onSave(toList(text))}
          className="h-10 rounded-full bg-[#00F0FF] text-black hover:bg-[#00d4de] font-semibold"><Save className="w-4 h-4" /></Button>
      </div>
    </div>
  );
}

function FlowRunner({ headers, domains }) {
  const [domain, setDomain] = useState("structure");
  const [input, setInput] = useState("Frasberg flow run");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setRes((await axios.post(`${API}/engines/flow`, { domain, input }, { headers })).data); }
    catch (e) { toast.error(e?.response?.data?.detail || "Flow failed"); } finally { setBusy(false); }
  };
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4" data-testid="engine-flow">
      <div className="text-sm font-semibold text-white">Engine Flow</div>
      <div className="mt-2 flex flex-col md:flex-row gap-2">
        <select data-testid="engine-flow-domain" value={domain} onChange={(e) => setDomain(e.target.value)} className={`${field} md:w-48`}>
          {domains.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <input data-testid="engine-flow-input" value={input} onChange={(e) => setInput(e.target.value)} className={field} />
        <Button type="button" data-testid="engine-flow-run" onClick={run} disabled={busy}
          className="h-10 rounded-full bg-[#00F0FF] text-black hover:bg-[#00d4de] font-semibold">
          {busy ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Play className="w-4 h-4 mr-1" />} Run flow
        </Button>
      </div>
      {res && (
        <div className="mt-3 text-xs text-neutral-300 space-y-1" data-testid="engine-flow-result">
          <div className="text-neutral-400">{res.stages.map((s) => s.name).join(" → ")}</div>
          <div data-testid="engine-flow-output">{res.output} · score {res.evolution?.evolutionScore} · {res.duration_ms} ms</div>
        </div>
      )}
    </div>
  );
}

export default function EngineSystems({ headers }) {
  const [sys, setSys] = useState(null);
  const [diag, setDiag] = useState(null);
  const [ident, setIdent] = useState(null);

  const load = useCallback(() => {
    axios.get(`${API}/engines/systems`, { headers }).then(({ data }) => setSys(data)).catch(() => {});
    axios.get(`${API}/engines/diagnostics`, { headers }).then(({ data }) => setDiag(data)).catch(() => {});
    axios.get(`${API}/engines/identity`, { headers }).then(({ data }) => setIdent(data)).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const save = async (path, actions, scope = "owner") => {
    try { await axios.put(`${API}/engines/${path}`, { actions, scope }, { headers }); toast.success("Saved"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Save failed"); }
  };
  const dropContinuity = async (cid) => {
    try { await axios.delete(`${API}/engines/continuity/${encodeURIComponent(cid)}`, { headers }); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Delete failed"); }
  };

  if (!sys) return null;
  return (
    <section className="mt-14" data-testid="engine-systems">
      <h2 className="font-display font-bold text-2xl flex items-center gap-2"><Network className="w-5 h-5 text-[#00F0FF]" /> System engines</h2>
      <p className="text-sm text-neutral-400 mt-1">Governance, policy, diagnostics, WorldGraph, Engine Flow and Unified Enforce. Owner: <code className="text-neutral-200">{sys.owner}</code></p>
      <div className="mt-5 grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {sys.systems.map((s) => (
          <div key={s.id} data-testid={`engine-system-${s.id}`} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <div className="flex items-center justify-between"><span className="font-display font-semibold text-white">{s.name}</span><span className="text-[10px] uppercase tracking-wider text-emerald-300">live</span></div>
            <div className="text-xs text-neutral-400 mt-1">{s.summary}</div>
            <div className="text-[11px] text-neutral-600 mt-1">{s.package}</div>
          </div>
        ))}
      </div>
      <div className="mt-5"><FlowRunner headers={headers} domains={sys.flow_domains} /></div>
      <div className="mt-5 grid md:grid-cols-3 gap-3">
        <BlockEditor label="Policy · blocked actions (yours)" testid="engine-policy" value={sys.policy.blockedActions} onSave={(a) => save("policy", a)} />
        <BlockEditor label="Governance · owner block" testid="engine-gov-owner" value={sys.governance.ownerBlock} onSave={(a) => save("governance", a)} />
        <BlockEditor label="Governance · global block (all owners)" testid="engine-gov-global" value={sys.governance.globalBlock} onSave={(a) => save("governance", a, "global")} />
      </div>
      {diag && (
        <div className="mt-5 grid grid-cols-3 gap-3" data-testid="engine-diagnostics">
          {Object.entries(diag).map(([c, d]) => (
            <div key={c} className="rounded-xl border border-white/10 bg-black/40 p-3">
              <div className="text-[11px] text-neutral-500 capitalize">{c} events</div>
              <div className="text-lg font-semibold text-white tabular-nums" data-testid={`engine-diag-${c}`}>{d.events}</div>
              {d.blocked > 0 && <div className="text-[11px] text-amber-300 flex items-center gap-1"><ShieldBan className="w-3 h-3" />{d.blocked} blocked</div>}
            </div>
          ))}
        </div>
      )}
      {ident && (
        <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.03] p-4" data-testid="engine-identity">
          <div className="text-sm font-semibold text-white">WorldGraph</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {ident.nodes.slice(0, 30).map((n) => <span key={n.engine} className="text-[11px] rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-neutral-300">{n.engine} · {n.runs}</span>)}
            {!ident.nodes.length && <span className="text-xs text-neutral-500">No engine runs yet.</span>}
          </div>
          {ident.continuity.length > 0 && (
            <div className="mt-3 space-y-1">
              {ident.continuity.map((c) => (
                <div key={c.continuity} className="flex items-center gap-2 text-xs text-neutral-300" data-testid={`engine-continuity-${c.continuity}`}>
                  <span className="font-mono">{c.continuity}</span><span className="text-neutral-500">{c.runs} runs · last {c.last_engine}</span>
                  <button type="button" data-testid={`engine-continuity-delete-${c.continuity}`} onClick={() => dropContinuity(c.continuity)} className="ml-auto text-neutral-500 hover:text-red-300"><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
