import React, { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { UserX, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "./ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const KINDS = ["image", "video", "music"];
const DURATIONS = [["", "Permanent"], ["24h", "24 hours"], ["7d", "7 days"]];

function lifts(at) {
  if (!at) return "Permanent";
  const h = Math.max(0, (new Date(at) - Date.now()) / 3600000);
  return `Lifts in ${h >= 24 ? `${Math.round(h / 24)}d` : h >= 1 ? `${Math.round(h)}h` : `${Math.max(1, Math.round(h * 60))}m`} · ${new Date(at).toLocaleString()}`;
}

function KindToggles({ value, onChange, prefix }) {
  return (
    <div className="flex gap-1.5">
      {KINDS.map((k) => {
        const on = value.includes(k);
        return (
          <button key={k} type="button" data-testid={`${prefix}-${k}`} aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== k) : [...value, k])}
            className={`h-8 px-3 rounded-full text-xs capitalize border transition-colors ${on ? "border-amber-400/60 bg-amber-400/15 text-amber-200" : "border-white/10 bg-white/5 text-neutral-400 hover:text-white"}`}>
            {k}
          </button>
        );
      })}
    </div>
  );
}

export default function UserBlocks({ headers, onChange }) {
  const [blocks, setBlocks] = useState([]);
  const [email, setEmail] = useState("");
  const [kinds, setKinds] = useState([]);
  const [duration, setDuration] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => axios.get(`${API}/engines/user-blocks`, { headers }).then(({ data }) => setBlocks(data.blocks)).catch(() => {}), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const save = async (em, ks, dur) => {
    setBusy(true);
    try {
      const { data } = await axios.put(`${API}/engines/user-blocks`, { email: em, kinds: ks, duration: dur || null }, { headers });
      toast.success(data.kinds.length ? `${data.email}: ${data.kinds.join(", ")} blocked · ${lifts(data.expires_at)}` : `${data.email} unblocked`);
      setEmail(""); setKinds([]); setDuration(""); load(); onChange?.();
    } catch (e) { toast.error(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || "Could not save"); } finally { setBusy(false); }
  };

  return (
    <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.03] p-4" data-testid="user-blocks">
      <div className="text-sm font-semibold text-white flex items-center gap-2"><UserX className="w-4 h-4 text-amber-300" /> Block a user</div>
      <p className="text-[11px] text-neutral-500 mt-0.5">Stops one account from creating the chosen types. Everyone else is unaffected.</p>
      <form className="mt-3 flex flex-col md:flex-row gap-2 md:items-center" onSubmit={(e) => { e.preventDefault(); if (email.trim()) save(email.trim(), kinds, duration); }}>
        <input data-testid="user-blocks-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="user@email.com"
          className="w-full md:w-72 h-10 rounded-lg border border-white/10 bg-black/50 px-3 text-sm text-white outline-none focus:border-[#00F0FF]/60" />
        <KindToggles value={kinds} onChange={setKinds} prefix="user-blocks-kind" />
        <select data-testid="user-blocks-duration" value={duration} onChange={(e) => setDuration(e.target.value)}
          className="h-10 rounded-lg border border-white/10 bg-black/50 px-3 text-sm text-white outline-none focus:border-[#00F0FF]/60">
          {DURATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <Button type="submit" data-testid="user-blocks-save" disabled={busy || !email.trim()}
          className="h-10 rounded-full bg-[#00F0FF] text-black hover:bg-[#00d4de] font-semibold md:ml-auto">
          {busy && <Loader2 className="w-4 h-4 mr-1 animate-spin" />} Save
        </Button>
      </form>
      <div className="mt-3 divide-y divide-white/5" data-testid="user-blocks-list">
        {blocks.map((b) => (
          <div key={b.user_id} className="py-2 flex flex-col md:flex-row md:items-center gap-2" data-testid={`user-block-${b.email}`}>
            <div className="min-w-0">
              <div className="text-sm text-white truncate">{b.email || b.user_id}</div>
              <div className="text-[11px] text-neutral-500">{b.name}{b.updated_by ? ` · by ${b.updated_by.replace("admin:", "")}` : ""}</div>
              <div className={`text-[11px] ${b.expires_at ? "text-[#00F0FF]" : "text-neutral-500"}`} data-testid={`user-block-${b.email}-expires`}>{lifts(b.expires_at)}</div>
            </div>
            <div className="md:ml-auto flex items-center gap-2">
              <KindToggles value={b.kinds} onChange={(ks) => save(b.email, ks, b.expires_at ? "keep" : null)} prefix={`user-block-${b.email}-kind`} />
              <button type="button" data-testid={`user-block-${b.email}-unblock`} disabled={busy} onClick={() => save(b.email, [])}
                className="text-xs text-neutral-400 hover:text-white underline">Unblock</button>
            </div>
          </div>
        ))}
        {!blocks.length && <div className="py-2 text-xs text-neutral-500">No users blocked.</div>}
      </div>
    </div>
  );
}
