import React, { useMemo } from "react";
import { History, GitBranch, Globe } from "lucide-react";

const label = (it) => {
  if (it.kind === "source") return "Original photo";
  if (it.kind === "generate") return "Original";
  if (it.kind === "upscale") return "4K upscale";
  if (it.kind === "cutout") return "Cut-out";
  return it.instruction || it.prompt || "Remix";
};

/** Every version of a photo's Painter-X chain. The path to the open version is lit, other branches are dimmed. */
export default function RemixHistory({ data, currentId, onOpen, busy }) {
  const { items, path, stepOf } = useMemo(() => {
    const list = data?.items || [];
    const byId = Object.fromEntries(list.map((x) => [x.id, x]));
    const p = new Set();
    for (let cur = byId[currentId]; cur && !p.has(cur.id); cur = byId[cur.parent_id]) p.add(cur.id);
    const st = {};
    list.forEach((x) => { st[x.id] = x.parent_id && st[x.parent_id] !== undefined ? st[x.parent_id] + 1 : (x.step ?? 0); });
    return { items: list, path: p, stepOf: st };
  }, [data, currentId]);

  if (items.length < 2) return null;
  const branches = items.length - path.size;

  return (
    <section data-testid="remix-history" className="rounded-2xl border border-white/10 bg-[#1E2327]/70 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1 pb-2">
        <h3 className="flex items-center gap-2 text-sm font-medium text-neutral-200">
          <History className="w-4 h-4 text-[#00F0FF]" /> Remix history
          <span className="text-xs font-normal text-neutral-500" data-testid="remix-history-count">{items.length} versions</span>
        </h3>
        <p className="text-[11px] text-neutral-500">
          Tap any version to step back to it, then Remix to branch from there.
          {branches > 0 && <span className="inline-flex items-center gap-1 ml-1 text-neutral-400"><GitBranch className="w-3 h-3" /> {branches} on other branches</span>}
        </p>
      </div>
      <ol className="flex items-stretch gap-2 overflow-x-auto pb-1 [scrollbar-width:thin]">
        {items.map((it) => {
          const on = it.id === currentId;
          const inPath = path.has(it.id);
          const step = stepOf[it.id];
          return (
            <li key={it.id} className="shrink-0">
              <button type="button" disabled={busy} onClick={() => onOpen(it)} data-testid={`remix-history-item-${it.id}`}
                aria-current={on ? "step" : undefined}
                className={`group w-28 text-left rounded-xl border p-1.5 transition-all disabled:cursor-wait ${on ? "border-[#00F0FF] bg-[#00F0FF]/10" : inPath ? "border-white/15 bg-white/[0.03] hover:border-[#00F0FF]/50" : "border-white/5 opacity-50 hover:opacity-90"}`}>
                <div className="relative aspect-square rounded-lg overflow-hidden bg-black/40">
                  {it.mini_base64 && <img src={it.mini_base64} alt={label(it)} className="w-full h-full object-cover" />}
                  <span className={`absolute top-1 left-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${on ? "bg-[#00F0FF] text-black" : "bg-black/75 text-white"}`}>
                    {step === 0 ? "Start" : `Step ${step}`}
                  </span>
                  {it.public && <Globe className="absolute top-1 right-1 w-3.5 h-3.5 text-[#00F0FF]" aria-label="Public" />}
                </div>
                <p className="mt-1 px-0.5 text-[11px] leading-tight text-neutral-300 line-clamp-2" title={label(it)}>{label(it)}</p>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
