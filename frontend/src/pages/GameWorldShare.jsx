import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Moon, Sun, ArrowLeft, Play, Share2, Sparkles, Loader2, X, Maximize2, Users, Car, Flag } from "lucide-react";
import { toast } from "sonner";
import { useTheme } from "../context/ThemeContext";
import Starfield from "../components/site/Starfield";
import Seo from "../components/site/Seo";
import Footer from "../components/site/Footer";

const BASE = process.env.REACT_APP_BACKEND_URL;
const API = `${BASE}/api/game-builder`;

function fmt(v) {
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return String(v);
}

export default function GameWorldShare() {
  const { theme, toggle } = useTheme();
  const { worldId } = useParams();
  const [w, setW] = useState(undefined);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    fetch(`${API}/public/${worldId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setW)
      .catch(() => setW(null));
  }, [worldId]);

  const share = () => {
    navigator.clipboard?.writeText(window.location.href).catch(() => {});
    toast.success("Share link copied");
  };
  const playSrc = w ? `${BASE}${w.play_url}` : "";
  const env = w?.environment || {};

  return (
    <main className="relative z-10 min-h-screen bg-lux-bg text-lux-text" data-testid="world-share-page">
      <Seo title={`${w?.name || "Game world"} — Frasberg Game Builder`}
        description={w?.tagline || "A game world built with the Frasberg Game Builder."} />
      <div className="pointer-events-none absolute inset-0 opacity-40"><Starfield /></div>

      <header className="glass sticky top-0 z-40 border-b border-lux-border">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4 sm:px-8">
          <Link to="/game-builder" className="flex items-center gap-2.5" data-testid="world-share-back">
            <ArrowLeft size={16} className="text-lux-text2" />
            <img src="/luchii-mark-circle.png" alt="Luchii" className="h-8 w-8 rounded-full" />
            <span className="font-display text-lg font-700 tracking-tight">Frasberg Game Builder</span>
          </Link>
          <button onClick={toggle} aria-label="Toggle theme" data-testid="world-share-theme"
            className="grid h-10 w-10 place-items-center rounded-full border border-lux-border transition-colors hover:border-lux-accent hover:text-lux-accent">
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>

      <div className="relative mx-auto max-w-6xl px-5 py-10 sm:px-8">
        {w === undefined ? (
          <div className="grid place-items-center py-24"><Loader2 size={24} className="animate-spin text-lux-accent" /></div>
        ) : w === null ? (
          <div className="rounded-2xl border border-lux-border bg-lux-surface/60 p-10 text-center" data-testid="world-share-not-found">
            <p className="font-display text-xl font-700">This game world doesn't exist anymore</p>
            <Link to="/game-builder" className="mt-4 inline-block rounded-full bg-lux-accent px-6 py-3 text-sm font-600 text-lux-bg">Build your own</Link>
          </div>
        ) : (
          <>
            {/* Cover */}
            <section className="relative overflow-hidden rounded-3xl border border-lux-border" data-testid="world-share-cover">
              <img src={`${BASE}${w.cover_url}`} alt={w.name} className="h-[420px] w-full object-cover sm:h-[480px]" data-testid="world-share-cover-img" />
              <div className="absolute inset-0 bg-gradient-to-t from-black via-black/55 to-black/10" />
              <div className="absolute inset-x-0 bottom-0 p-6 sm:p-10">
                <p className="font-mono text-[13px] uppercase tracking-[0.25em] text-cyan-300" data-testid="world-share-engine">
                  {w.engine_title} · {w.genre}
                </p>
                <h1 className="mt-2 font-display text-4xl font-700 leading-tight tracking-tight text-white sm:text-6xl" data-testid="world-share-title">
                  {w.name}
                </h1>
                {w.tagline && <p className="mt-3 max-w-2xl text-[16px] leading-relaxed text-white/80" data-testid="world-share-tagline">{w.tagline}</p>}
                <div className="mt-4 flex flex-wrap gap-2 font-mono text-[12px] uppercase tracking-wider">
                  {[w.difficulty, env.time_of_day, env.weather && env.weather.replace("_", " "),
                    `${w.plays || 0} play${w.plays === 1 ? "" : "s"}`, `by ${w.creator}`].filter(Boolean).map((t) => (
                    <span key={t} className="rounded-full border border-white/20 bg-white/10 px-3 py-1 text-white/85 backdrop-blur">{t}</span>
                  ))}
                </div>
                <div className="mt-6 flex flex-wrap gap-3">
                  <button type="button" onClick={() => setPlaying(true)} data-testid="world-share-play"
                    className="inline-flex items-center gap-2 rounded-full bg-white px-8 py-3.5 text-[15px] font-700 text-black transition-transform hover:-translate-y-0.5">
                    <Play size={17} fill="currentColor" /> Play
                  </button>
                  <button type="button" onClick={share} data-testid="world-share-copy"
                    className="inline-flex items-center gap-2 rounded-full border border-white/30 bg-white/10 px-6 py-3.5 text-[15px] font-600 text-white backdrop-blur transition-colors hover:bg-white/20">
                    <Share2 size={15} /> Share
                  </button>
                </div>
              </div>
            </section>

            {/* World details */}
            <section className="mt-8 grid gap-6 md:grid-cols-[1.4fr_1fr]">
              <div className="glass rounded-3xl p-6" data-testid="world-share-settings">
                <p className="font-mono text-[13px] uppercase tracking-[0.2em] text-lux-text2">Engine settings</p>
                <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {w.highlights.map((h) => (
                    <div key={h.key} className="rounded-2xl border border-lux-border bg-lux-surface/60 px-4 py-3" data-testid={`world-share-setting-${h.key}`}>
                      <p className="text-[12px] text-lux-text2">{h.label}</p>
                      <p className="mt-0.5 font-display text-lg font-700 capitalize">{fmt(h.value)}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="glass space-y-4 rounded-3xl p-6" data-testid="world-share-world">
                <p className="font-mono text-[13px] uppercase tracking-[0.2em] text-lux-text2">In this world</p>
                {w.track && (
                  <p className="flex items-start gap-2 text-[15px]"><Flag size={16} className="mt-0.5 text-lux-accent" />
                    <span>{w.track.name} · {(w.track.lengthMeters / 1000).toFixed(1)} km{w.race_rules ? ` · ${w.race_rules.name}` : ""}</span></p>
                )}
                {w.vehicles?.length > 0 && (
                  <p className="flex items-start gap-2 text-[15px]"><Car size={16} className="mt-0.5 text-lux-accent" /><span>{w.vehicles.join(", ")}</span></p>
                )}
                {w.npc_groups?.length > 0 && (
                  <p className="flex items-start gap-2 text-[15px]"><Users size={16} className="mt-0.5 text-lux-accent" /><span>{w.npc_groups.join(", ")}</span></p>
                )}
                <p className="text-[13px] leading-relaxed text-lux-text2">
                  Built from a prompt into a WorldGraph world and played on a real Frasberg engine. No AI-written code.
                </p>
              </div>
            </section>

            <div className="mt-8 rounded-2xl border border-lux-border bg-lux-surface/60 p-6 text-center">
              <Sparkles size={18} className="mx-auto text-lux-accent" />
              <p className="mt-2 font-display text-lg font-600">Describe a game, play it in seconds</p>
              <Link to="/game-builder" data-testid="world-share-build-cta"
                className="mt-4 inline-block rounded-full bg-lux-text px-6 py-3 text-sm font-600 text-lux-bg transition-transform hover:-translate-y-0.5">
                Build your own world
              </Link>
            </div>
          </>
        )}
      </div>

      {playing && w && (
        <div className="fixed inset-0 z-[90] bg-black" data-testid="world-share-player">
          <iframe src={playSrc} title={w.name} className="h-full w-full" allow="autoplay; fullscreen; pointer-lock; gamepad" data-testid="world-share-iframe" />
          <div className="absolute bottom-4 left-1/2 flex -translate-x-1/2 gap-2">
            <a href={playSrc} target="_blank" rel="noreferrer" aria-label="Open full screen" data-testid="world-share-fullscreen"
              className="grid h-10 w-10 place-items-center rounded-full bg-white/15 text-white backdrop-blur hover:bg-white/25"><Maximize2 size={16} /></a>
            <button type="button" onClick={() => setPlaying(false)} aria-label="Close game" data-testid="world-share-close"
              className="grid h-10 w-10 place-items-center rounded-full bg-white/15 text-white backdrop-blur hover:bg-white/25"><X size={18} /></button>
          </div>
        </div>
      )}
      <Footer />
    </main>
  );
}
