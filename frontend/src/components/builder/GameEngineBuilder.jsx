import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Play, Trash2, Save, ExternalLink, Share2, Boxes, Wand2, ChevronDown, RefreshCw, Server, Link2 } from "lucide-react";
import { toast } from "sonner";

const BASE = process.env.REACT_APP_BACKEND_URL;
const API = `${BASE}/api/game-builder`;
const TIMES = ["", "dawn", "day", "dusk", "night"];
const WEATHERS = ["", "clear", "rain", "fog", "stormy", "heat_haze"];
const EXAMPLES = [
  "A hard neon night street race with 3 laps and pink traffic",
  "A 5-lap race on a 4 km circuit at sunset",
  "Mob boss crime city with relentless cops",
  "A frozen ice labyrinth in 2 minutes",
  "Steal cars and escape a police chase in the rain with $5000",
  "Alien invaders in deep space, boss every 3 waves, 7 lives",
  "A zombie dungeon with 12 enemies at midnight",
  "A cozy foggy maze called \"Mist Hollow\"",
  "Mob boss crime city, start with $900",
];

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
  return data;
}

export default function GameEngineBuilder({ user, onSignIn }) {
  const [engines, setEngines] = useState([]);
  const [engine, setEngine] = useState("");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [worlds, setWorlds] = useState([]);
  const [current, setCurrent] = useState(null);
  const [draft, setDraft] = useState({});
  const [env, setEnv] = useState({ time_of_day: "", weather: "" });
  const [saving, setSaving] = useState(false);
  const [playKey, setPlayKey] = useState(0);
  const [showJson, setShowJson] = useState(false);
  const [server, setServer] = useState(null);
  const [checking, setChecking] = useState(false);
  const [refining, setRefining] = useState(false);

  useEffect(() => {
    api("/engines").then((d) => setEngines(d.engines || [])).catch(() => {});
    api("/frasberg-status").then(setServer).catch(() => {});
  }, []);

  async function recheck() {
    setChecking(true);
    try {
      const st = await api("/frasberg-status?refresh=1");
      setServer(st);
      if (st.reachable && user) {
        const r = await api("/worlds/refine-pending", { method: "POST" });
        if (r.refined) { toast.success(`Frasberg server added detail to ${r.refined} world${r.refined > 1 ? "s" : ""}`); loadWorlds(); }
        else toast.success("Frasberg server is online — new worlds get its detail");
      } else if (!st.reachable) {
        toast.error(`Frasberg server still offline (${st.detail})`);
      }
    } catch (e) { toast.error(e.message); } finally { setChecking(false); }
  }

  async function refine() {
    if (!current) return;
    setRefining(true);
    try {
      const w = await api(`/worlds/${current.id}/refine`, { method: "POST" });
      toast.success("Frasberg server detail added");
      open(w);
      loadWorlds();
    } catch (e) {
      toast.error(e.message);
      api("/frasberg-status").then(setServer).catch(() => {});
    } finally { setRefining(false); }
  }

  const loadWorlds = useCallback(async () => {
    if (!user) return;
    try { setWorlds((await api("/worlds")).worlds || []); } catch { /* signed out */ }
  }, [user]);
  useEffect(() => { loadWorlds(); }, [loadWorlds]);

  function open(w) {
    setCurrent(w);
    setDraft(w.config || {});
    setEnv({ time_of_day: w.environment?.time_of_day || "", weather: w.environment?.weather || "" });
    setPlayKey((k) => k + 1);
  }

  async function build(p) {
    const text = (p ?? prompt).trim();
    if (!user) { onSignIn(); return; }
    if (text.length < 3) { toast.error("Describe the game you want to build"); return; }
    setBusy(true);
    try {
      const w = await api("/worlds", { method: "POST", body: JSON.stringify({ prompt: text, engine: engine || null }) });
      toast.success(`Built "${w.name}" on ${w.engine_title}`);
      open(w);
      loadWorlds();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!current) return;
    setSaving(true);
    const numeric = {};
    const tun = engines.find((e) => e.id === current.engine)?.tunables || [];
    tun.forEach((t) => { if (draft[t.key] !== undefined) numeric[t.key] = t.type === "select" ? draft[t.key] : Number(draft[t.key]); });
    try {
      const w = await api(`/worlds/${current.id}`, {
        method: "PATCH",
        body: JSON.stringify({ config: numeric, time_of_day: env.time_of_day, weather: env.weather }),
      });
      toast.success("World saved to WorldGraph");
      open(w);
      loadWorlds();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(w, e) {
    e.stopPropagation();
    try {
      await api(`/worlds/${w.id}`, { method: "DELETE" });
      if (current?.id === w.id) setCurrent(null);
      loadWorlds();
    } catch (err) { toast.error(err.message); }
  }

  const playSrc = current ? `${BASE}${current.play_url}` : "";
  const sharePath = current ? current.share_path || `/g/${current.id}` : "";
  const tunables = current ? engines.find((e) => e.id === current.engine)?.tunables || [] : [];

  return (
    <div className="mt-10 grid gap-8 lg:grid-cols-[280px_1fr]" data-testid="game-engine-builder">
      <aside data-testid="engine-worlds-sidebar">
        {user ? (
          <>
            <p className="px-1 font-mono text-[15px] uppercase tracking-[0.2em] text-lux-text2">My game worlds</p>
            <div className="mt-3 max-h-[60vh] space-y-1.5 overflow-y-auto pr-1" data-testid="engine-worlds-list">
              {worlds.length === 0 && <p className="px-1 text-[15px] text-lux-text2">No worlds yet. Describe your first game.</p>}
              {worlds.map((w) => (
                <div key={w.id} onClick={() => open(w)} data-testid={`engine-world-${w.id}`}
                  className={`cursor-pointer rounded-xl border px-4 py-3 transition-colors ${current?.id === w.id ? "border-lux-accent bg-lux-surface" : "border-lux-border bg-lux-surface/60 hover:border-lux-accent/50"}`}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm text-lux-text">{w.name}</p>
                    <button onClick={(e) => remove(w, e)} aria-label="Delete world" data-testid={`engine-world-delete-${w.id}`}
                      className="shrink-0 text-lux-text2 transition-colors hover:text-red-500"><Trash2 size={13} /></button>
                  </div>
                  <p className="mt-1 font-mono text-[13px] uppercase tracking-wide text-lux-text2">{w.engine_title} · {w.difficulty}</p>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="rounded-2xl border border-lux-border bg-lux-surface p-6" data-testid="engine-signin-card">
            <p className="font-display text-lg font-700 tracking-tight">Sign in to build</p>
            <p className="mt-2 text-[15px] leading-relaxed text-lux-text2">Your game worlds are saved to WorldGraph under your account.</p>
            <button onClick={onSignIn} data-testid="engine-signin-cta"
              className="mt-4 w-full rounded-full bg-lux-text px-5 py-2.5 text-center text-sm font-600 text-lux-bg">Sign in / Sign up free</button>
          </div>
        )}
      </aside>

      <div className="min-w-0 space-y-6">
        <div className="glass rounded-3xl p-5">
          <p className="mb-3 font-mono text-[14px] uppercase tracking-[0.2em] text-lux-text2">Frasberg engine</p>
          <div className="flex flex-wrap gap-2" data-testid="engine-picker">
            <button type="button" onClick={() => setEngine("")} data-testid="engine-pick-auto"
              className={`rounded-full border px-4 py-2 text-sm transition-colors ${engine === "" ? "border-lux-accent bg-lux-surface font-600" : "border-lux-border text-lux-text2 hover:border-lux-accent/60"}`}>
              <Wand2 size={13} className="mr-1 inline" /> Auto-pick
            </button>
            {engines.map((e) => (
              <button key={e.id} type="button" onClick={() => setEngine(e.id)} data-testid={`engine-pick-${e.id}`} title={e.description}
                className={`rounded-full border px-4 py-2 text-sm transition-colors ${engine === e.id ? "border-lux-accent bg-lux-surface font-600" : "border-lux-border text-lux-text2 hover:border-lux-accent/60"}`}>
                {e.title} <span className="text-lux-text2">· {e.genre}</span>
              </button>
            ))}
          </div>
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} data-testid="engine-prompt"
            placeholder="Describe your game: setting, time of day, weather, difficulty, lives, laps, cash, enemies…"
            className="mt-4 w-full resize-none rounded-2xl border border-lux-border bg-lux-surface px-4 py-3 text-[15px] text-lux-text outline-none placeholder:text-lux-text2 focus:border-lux-accent" />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-1.5">
              {EXAMPLES.map((ex) => (
                <button key={ex} type="button" onClick={() => setPrompt(ex)} data-testid="engine-example"
                  className="rounded-full border border-lux-border px-3 py-1 text-[13px] text-lux-text2 hover:border-lux-accent/60 hover:text-lux-text">{ex}</button>
              ))}
            </div>
            <button type="button" onClick={() => build()} disabled={busy} data-testid="engine-build-btn"
              className="inline-flex items-center gap-2 rounded-full bg-lux-text px-6 py-2.5 text-sm font-600 text-lux-bg transition-transform hover:-translate-y-0.5 disabled:opacity-60">
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Boxes size={15} />} {busy ? "Building world…" : "Build world"}
            </button>
          </div>
          {user?.role === "admin" && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px]" data-testid="frasberg-server-status">
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 ${server?.reachable ? "border-emerald-500/50 text-emerald-400" : "border-amber-500/50 text-amber-400"}`}>
              <Server size={12} />
              <span data-testid="frasberg-server-state">
                Frasberg server {server == null ? "…" : server.reachable ? "online — adds detail to plans" : `offline${server.detail ? ` (${server.detail})` : ""} — using keyword rules`}
              </span>
            </span>
            <button type="button" onClick={recheck} disabled={checking} data-testid="frasberg-recheck-btn"
              className="inline-flex items-center gap-1.5 rounded-full border border-lux-border px-3 py-1 text-lux-text2 hover:border-lux-accent hover:text-lux-text disabled:opacity-60">
              <RefreshCw size={12} className={checking ? "animate-spin" : ""} /> Re-check
            </button>
          </div>
          )}
          <p className="mt-3 text-[13px] text-lux-text2">
            Your prompt becomes a WorldDefinition (scenes, NPC groups, track, vehicles, rules) saved to WorldGraph, then runs on a real Frasberg engine. No AI-written code.
          </p>
        </div>

        {current && (
          <div className="glass rounded-3xl p-5" data-testid="engine-world-panel">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-2xl font-700 tracking-tight" data-testid="engine-world-name">{current.name}</h2>
                <p className="mt-1 text-[14px] text-lux-text2">{current.tagline}</p>
                <div className="mt-2 flex flex-wrap gap-2 font-mono text-[12px] uppercase tracking-wider">
                  <span className="rounded-full bg-lux-accent/15 px-3 py-1 text-lux-accent" data-testid="engine-world-engine">{current.engine_title}</span>
                  <span className="rounded-full bg-lux-surface2 px-3 py-1 text-lux-text2">{current.difficulty}</span>
                  <span className="rounded-full bg-lux-surface2 px-3 py-1 text-lux-text2" data-testid="engine-world-enriched">{current.enriched_by === "rules+frasberg" ? "rules + Frasberg server" : "rules"}</span>
                  <span className="rounded-full bg-lux-surface2 px-3 py-1 text-lux-text2">schema {current.world?.metadata?.schemaVersion}</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {user?.role === "admin" && current.enriched_by !== "rules+frasberg" && (
                  <button type="button" onClick={refine} disabled={refining} data-testid="engine-refine-btn"
                    title="Ask the Frasberg server to add detail to this world"
                    className="inline-flex items-center gap-1.5 rounded-full border border-lux-border px-4 py-2 text-sm hover:border-lux-accent disabled:opacity-60">
                    {refining ? <Loader2 size={14} className="animate-spin" /> : <Server size={14} />} Add server detail
                  </button>
                )}
                <Link to={sharePath} data-testid="engine-share-page"
                  className="inline-flex items-center gap-1.5 rounded-full border border-lux-border px-4 py-2 text-sm hover:border-lux-accent"><Link2 size={14} /> Share page</Link>
                <a href={playSrc} target="_blank" rel="noreferrer" data-testid="engine-open-full"
                  className="inline-flex items-center gap-1.5 rounded-full border border-lux-border px-4 py-2 text-sm hover:border-lux-accent"><ExternalLink size={14} /> Full screen</a>
                <button type="button" data-testid="engine-share"
                  onClick={() => { navigator.clipboard?.writeText(`${window.location.origin}${sharePath}`); toast.success("Share link copied"); }}
                  className="inline-flex items-center gap-1.5 rounded-full border border-lux-border px-4 py-2 text-sm hover:border-lux-accent"><Share2 size={14} /> Share</button>
              </div>
            </div>

            <div className="mt-4 overflow-hidden rounded-2xl border border-lux-border bg-black">
              <iframe key={playKey} src={playSrc} title={current.name} data-testid="engine-play-iframe"
                className="aspect-video w-full" allow="autoplay; fullscreen; pointer-lock; gamepad" />
            </div>

            <div className="mt-5 grid gap-4 sm:grid-cols-2" data-testid="engine-tunables">
              {tunables.map((t) => t.type === "select" ? (
                <label key={t.key} className="block text-[13px] text-lux-text2">{t.label}
                  <select value={draft[t.key] ?? t.default} data-testid={`engine-tunable-${t.key}`}
                    onChange={(e) => setDraft((d) => ({ ...d, [t.key]: e.target.value }))}
                    className="mt-1 w-full rounded-xl border border-lux-border bg-lux-surface px-3 py-2 text-sm capitalize text-lux-text">
                    {t.options.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </label>
              ) : (
                <label key={t.key} className="block">
                  <span className="flex justify-between text-[13px] text-lux-text2">
                    <span>{t.label}</span><span className="font-mono text-lux-text" data-testid={`engine-tunable-value-${t.key}`}>{draft[t.key] ?? t.default}</span>
                  </span>
                  <input type="range" min={t.min} max={t.max} step={t.step} value={draft[t.key] ?? t.default}
                    data-testid={`engine-tunable-${t.key}`}
                    onChange={(e) => setDraft((d) => ({ ...d, [t.key]: e.target.value }))}
                    className="mt-1 w-full accent-[var(--lux-accent)]" />
                </label>
              ))}
              <label className="block text-[13px] text-lux-text2">Time of day
                <select value={env.time_of_day} onChange={(e) => setEnv((v) => ({ ...v, time_of_day: e.target.value }))} data-testid="engine-time"
                  className="mt-1 w-full rounded-xl border border-lux-border bg-lux-surface px-3 py-2 text-sm text-lux-text">
                  {TIMES.map((t) => <option key={t} value={t}>{t || "Live (real clock)"}</option>)}
                </select>
              </label>
              <label className="block text-[13px] text-lux-text2">Weather
                <select value={env.weather} onChange={(e) => setEnv((v) => ({ ...v, weather: e.target.value }))} data-testid="engine-weather"
                  className="mt-1 w-full rounded-xl border border-lux-border bg-lux-surface px-3 py-2 text-sm text-lux-text">
                  {WEATHERS.map((t) => <option key={t} value={t}>{t ? t.replace("_", " ") : "Live (daily)"}</option>)}
                </select>
              </label>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" onClick={save} disabled={saving} data-testid="engine-save-btn"
                className="inline-flex items-center gap-2 rounded-full bg-lux-text px-5 py-2.5 text-sm font-600 text-lux-bg disabled:opacity-60">
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Save & replay
              </button>
              <button type="button" onClick={() => setPlayKey((k) => k + 1)} data-testid="engine-replay-btn"
                className="inline-flex items-center gap-2 rounded-full border border-lux-border px-5 py-2.5 text-sm hover:border-lux-accent"><Play size={14} /> Restart engine</button>
              <button type="button" onClick={() => setShowJson((s) => !s)} data-testid="engine-json-toggle"
                className="inline-flex items-center gap-2 rounded-full border border-lux-border px-5 py-2.5 text-sm hover:border-lux-accent">
                WorldDefinition <ChevronDown size={14} className={showJson ? "rotate-180" : ""} />
              </button>
            </div>
            {showJson && (
              <pre className="mt-4 max-h-80 overflow-auto rounded-2xl border border-lux-border bg-lux-surface p-4 font-mono text-[12px] text-lux-text2" data-testid="engine-world-json">
                {JSON.stringify(current.world, null, 2)}
              </pre>
            )}
          </div>
        )}
        {!user && (
          <p className="text-center text-[14px] text-lux-text2">
            Or play the stock engines in the <Link to="/games" className="text-lux-accent">Games library</Link>.
          </p>
        )}
      </div>
    </div>
  );
}
