import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import Hero from "../components/Hero";
import LandingSections from "../components/LandingSections";

const MORE = [
  { title: "Gallery", desc: "Everything you've created, with remix history", route: "/creator/gallery" },
  { title: "Luchii Agent", desc: "Chat with Luchii and run multi-step creative tasks", route: "/creator/agent" },
  { title: "Classic Studio", desc: "Sound effects, dubbing, audiobooks, speech to text and more", route: "/create/classic" },
];

export default function ToolsTab() {
  return (
    <div data-testid="creator-features-tools-page">
      <Hero />
      <LandingSections />
      <section className="mx-auto max-w-[1400px] px-5 pb-24 md:px-8" data-testid="creator-more-studios">
        <h3 className="mb-5 text-sm uppercase tracking-[0.2em] text-neutral-500">More studios</h3>
        <div className="grid gap-4 sm:grid-cols-3">
          {MORE.map((t) => (
            <Link key={t.title} to={t.route} data-testid={`creator-more-${t.title.toLowerCase().replace(/\s+/g, "-")}`}
              className="group rounded-2xl border border-white/10 bg-white/[0.03] p-5 transition-colors hover:border-white/30 hover:bg-white/[0.06]">
              <div className="flex items-start justify-between">
                <span className="font-medium">{t.title}</span>
                <ArrowUpRight className="h-4 w-4 text-neutral-500 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-white" />
              </div>
              <p className="mt-2 text-sm text-neutral-400">{t.desc}</p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
