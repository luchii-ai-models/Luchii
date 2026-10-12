import React from "react";
import { CheckSquare, Square, Trash2, X } from "lucide-react";

export function SelectBar({ selecting, setSelecting, selected, allIds, setSelected, onDelete, busy }) {
  if (!selecting) {
    return (
      <button data-testid="gallery-select-toggle" onClick={() => setSelecting(true)}
        className="inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm border border-white/10 bg-white/5 text-neutral-300 hover:bg-white/10">
        <CheckSquare className="w-4 h-4" /> Select
      </button>
    );
  }
  const all = selected.size === allIds.length && allIds.length > 0;
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="gallery-select-bar">
      <span className="text-sm text-neutral-300" data-testid="gallery-selected-count">{selected.size} selected</span>
      <button data-testid="gallery-select-all" onClick={() => setSelected(new Set(all ? [] : allIds))}
        className="rounded-full px-3 py-1.5 text-sm border border-white/10 bg-white/5 hover:bg-white/10">
        {all ? "Clear" : "Select all"}
      </button>
      <button data-testid="gallery-bulk-delete" disabled={!selected.size || busy} onClick={onDelete}
        className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm bg-red-500/90 text-white hover:bg-red-500 disabled:opacity-40">
        <Trash2 className="w-4 h-4" /> Delete selected
      </button>
      <button data-testid="gallery-select-cancel" onClick={() => { setSelecting(false); setSelected(new Set()); }}
        className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-sm text-neutral-400 hover:text-white">
        <X className="w-4 h-4" /> Cancel
      </button>
    </div>
  );
}

export function SelectMark({ id, checked, onToggle }) {
  return (
    <button data-testid={`gallery-select-${id}`} onClick={(e) => { e.stopPropagation(); onToggle(id); }}
      className={`absolute inset-0 z-20 flex items-start justify-end p-2 transition-colors ${checked ? "bg-[#00F0FF]/20 ring-2 ring-inset ring-[#00F0FF]" : "bg-black/10 hover:bg-black/20"}`}>
      {checked ? <CheckSquare className="w-6 h-6 text-[#00F0FF]" /> : <Square className="w-6 h-6 text-white/80" />}
    </button>
  );
}
