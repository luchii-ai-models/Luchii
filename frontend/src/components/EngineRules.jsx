import React, { useEffect, useState } from "react";
import axios from "axios";
import { ShieldCheck, BookOpen } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const NAME = { image: "Image", video: "Video", music: "Music", voice: "Voice", stt: "Speech to Text", audio: "Audio", "game-logic": "Game Logic" };
const ORDER = ["image", "video", "music", "voice", "stt", "audio", "game-logic"];

export default function EngineRules() {
  const [data, setData] = useState(null);
  useEffect(() => { axios.get(`${API}/engines/rules`).then(({ data: d }) => setData(d)).catch(() => {}); }, []);
  if (!data) return null;
  const engines = ORDER.map((k) => data.engines[k]).filter(Boolean);
  return (
    <section className="mt-16" data-testid="engine-rules">
      <h2 className="font-display font-bold text-2xl flex items-center gap-2"><ShieldCheck className="w-5 h-5 text-[#00F0FF]" /> Engine rules</h2>
      <p className="text-sm text-neutral-400 mt-1 max-w-3xl">
        The rules from the Frasberg engine prompts, applied to the real Luchii engines. <b className="text-neutral-200">Enforced</b> rules are checked by the API on every request; <b className="text-neutral-200">reference</b> rules describe intended behaviour.
      </p>
      <div className="mt-5 grid md:grid-cols-2 gap-3">
        {engines.map((e) => {
          const rules = e.sections.flatMap((s) => s.rules.map((r) => ({ ...r, heading: s.heading })));
          const enforced = rules.filter((r) => r.status === "enforced").length;
          return (
            <div key={e.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-5" data-testid={`engine-rules-${e.id}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-display font-semibold text-white">{NAME[e.id] || e.id} engine</div>
                <div className="flex gap-1.5">
                  {e.permission && <span className="text-[10px] rounded-full border border-[#00F0FF]/30 bg-[#00F0FF]/10 px-2 py-0.5 text-[#00F0FF]">{e.permission}</span>}
                  <span className="text-[10px] rounded-full border border-white/10 px-2 py-0.5 text-neutral-400">{enforced}/{rules.length} enforced</span>
                </div>
              </div>
              <div className="text-xs text-neutral-500 mt-1">{e.platform_engine}{e.default_duration ? ` · default ${e.default_duration}s` : ""}</div>
              <ul className="mt-3 space-y-2">
                {rules.slice(0, e.id === "game-logic" ? 6 : 12).map((r, i) => (
                  <li key={i} className="text-sm text-neutral-300 flex gap-2">
                    <span className={`mt-0.5 shrink-0 text-[9px] uppercase tracking-wider rounded px-1.5 py-0.5 h-fit ${r.status === "enforced" ? "bg-emerald-400/15 text-emerald-300" : "bg-white/5 text-neutral-500"}`}>
                      {r.status === "enforced" ? "enforced" : "reference"}
                    </span>
                    <span className="min-w-0">
                      {r.text}
                      {r.how && <span className="block text-[11px] text-neutral-500 mt-0.5">{r.how}</span>}
                    </span>
                  </li>
                ))}
                {e.id === "game-logic" && rules.length > 6 && (
                  <li className="text-xs text-neutral-500 flex items-center gap-1"><BookOpen className="w-3.5 h-3.5" /> +{rules.length - 6} more simulation rules (reference)</li>
                )}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}
