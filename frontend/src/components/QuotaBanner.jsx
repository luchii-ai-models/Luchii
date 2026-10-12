import React, { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { PartyPopper, Zap, X, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "./ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function QuotaBanner({ headers }) {
  const [a, setA] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => axios.get(`${API}/gpu-admin/aws`, { headers }).then(({ data }) => setA(data)).catch(() => {}), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); const t = setInterval(() => document.visibilityState === "visible" && load(), 30000); return () => clearInterval(t); }, [load]);

  const alwaysOn = async () => {
    setBusy(true);
    try {
      const { data } = await axios.put(`${API}/gpu-admin/aws/settings`, { mode: "always_on" }, { headers });
      toast.success(data.start?.ok === false ? `Always on. ${data.start.reason}` : "Always on: the AWS GPU is starting and stays running 24/7.");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not switch to always-on"); } finally { setBusy(false); }
  };
  const dismiss = async () => {
    try { await axios.post(`${API}/gpu-admin/aws/quota/dismiss`, null, { headers }); load(); } catch { /* keep banner */ }
  };

  if (!a?.quota_alert) return null;
  return (
    <div data-testid="quota-banner" className="mb-8 rounded-2xl border border-emerald-400/40 bg-emerald-400/10 p-5 flex flex-col md:flex-row md:items-center gap-4">
      <PartyPopper className="w-6 h-6 text-emerald-300 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-white">AWS approved your GPU limit</div>
        <p className="text-sm text-neutral-300 mt-0.5" data-testid="quota-banner-text">
          Quota is now {a.quota} vCPU (needs {a.quota_needed}). Switch to always-on for instant clips on the {a.instance_type}
          {a.hourly_usd ? ` · about $${Math.round(a.hourly_usd * 730)}/mo` : ""}.
        </p>
      </div>
      <div className="flex gap-2 shrink-0">
        <Button data-testid="quota-banner-always-on" onClick={alwaysOn} disabled={busy}
          className="rounded-full bg-emerald-400 text-black hover:bg-emerald-300 font-semibold">
          {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Zap className="w-4 h-4 mr-2" />} Switch to always-on
        </Button>
        <button type="button" data-testid="quota-banner-dismiss" onClick={dismiss} aria-label="Dismiss"
          className="rounded-full p-2 text-neutral-400 hover:bg-white/10 hover:text-white"><X className="w-4 h-4" /></button>
      </div>
    </div>
  );
}
