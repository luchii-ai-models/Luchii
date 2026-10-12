import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import FrasbergStarfieldLayout from "./layouts/FrasbergStarfieldLayout";
import { brand } from "./mock";

export const CREATOR_TABS = [
  { id: "create", label: "Create" },
  { id: "tools", label: "Features & Tools" },
  { id: "models", label: "Models" },
];

export default function CreatorShell({ active, children }) {
  return (
    <FrasbergStarfieldLayout>
      <div className="min-h-screen text-white" data-testid="frasberg-creator">
        <header className="sticky top-0 z-40 border-b border-white/10 bg-[#05060A]/80 backdrop-blur-xl">
          <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-5 py-3 md:px-8">
            <Link to="/dashboard" data-testid="creator-back-link" className="text-neutral-400 transition-colors hover:text-white" aria-label="Back to dashboard">
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <Link to="/create" data-testid="creator-home-link" className="flex shrink-0 items-center gap-2">
              <img src={brand.logo} alt="Frasberg Creator logo" className="h-8 w-8 rounded-full object-contain" />
              <span className="text-lg font-semibold tracking-tight">{brand.name}</span>
            </Link>
            <nav className="flex gap-1 overflow-x-auto" data-testid="creator-tabs">
              {CREATOR_TABS.map((t) => (
                <Link key={t.id} to={`/create?tab=${t.id}`} data-testid={`creator-tab-${t.id}`}
                  className={`whitespace-nowrap rounded-full px-4 py-1.5 text-sm transition-colors ${active === t.id ? "bg-white text-black" : "text-neutral-300 hover:bg-white/10 hover:text-white"}`}>
                  {t.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        {children}
      </div>
    </FrasbergStarfieldLayout>
  );
}
