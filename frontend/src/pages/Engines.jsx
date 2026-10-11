import React from "react";
import { Link } from "react-router-dom";
import { Cpu, ArrowUpRight } from "lucide-react";
import Navbar from "../components/Navbar";
import Footer from "../components/Footer";
import EngineRuntime from "../components/EngineRuntime";
import EngineRules from "../components/EngineRules";

export default function Engines() {
  return (
    <div className="min-h-screen bg-[#05060A] text-white">
      <Navbar />
      <main className="max-w-6xl mx-auto px-5 md:px-8 pt-28 pb-24" data-testid="engines-page">
        <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-neutral-300 mb-5">
          <Cpu className="w-3.5 h-3.5 text-[#00F0FF]" /> Frasberg Engine Runtime
        </div>
        <h1 className="font-display font-bold tracking-tight text-4xl md:text-5xl">
          Every <span className="text-[#00F0FF]">Frasberg engine</span>, live
        </h1>
        <p className="mt-3 text-neutral-400 text-sm md:text-base max-w-2xl">
          The Frasberg runtime engines from <code className="text-neutral-200">frasberg-secure-runtime</code>, running on this platform. Each engine builds its parts from the state you give it, links them into a graph, wraps them in an envelope and scores how much of its input was present.
        </p>
        <div className="mt-5 flex flex-wrap gap-2 text-xs">
          <code className="rounded-full border border-white/10 bg-black/50 px-3 py-1.5 text-neutral-300">GET /api/engines/runtime</code>
          <code className="rounded-full border border-white/10 bg-black/50 px-3 py-1.5 text-neutral-300">POST /api/engines/&#123;id&#125;/execute</code>
          <code className="rounded-full border border-white/10 bg-black/50 px-3 py-1.5 text-neutral-300">POST /api/engines/chain</code>
          <code className="rounded-full border border-white/10 bg-black/50 px-3 py-1.5 text-neutral-300">GET /api/engines/rules</code>
        </div>
        <div className="mt-12"><EngineRuntime /></div>
        <EngineRules />
        <div className="mt-14 rounded-2xl border border-white/10 bg-white/[0.02] p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <p className="text-sm text-neutral-400">Looking for image, video, music and voice? Those run on the Luchii models.</p>
          <Link to="/models" data-testid="engines-models-link" className="inline-flex items-center gap-1 text-sm font-semibold text-[#00F0FF] hover:underline">
            See Luchii Models <ArrowUpRight className="w-4 h-4" />
          </Link>
        </div>
      </main>
      <Footer />
    </div>
  );
}
