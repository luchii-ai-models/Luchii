import React, { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { Activity, RefreshCw, Loader2, Cpu, Download, Gift, Rocket, Square, ExternalLink, Server } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import Navbar from "../components/Navbar";
import Footer from "../components/Footer";
import { useAuth } from "../context/AuthContext";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const TONE = {
  online: { dot: "bg-emerald-400", text: "text-emerald-300", label: "Online" },
  degraded: { dot: "bg-amber-400", text: "text-amber-300", label: "Degraded" },
  offline: { dot: "bg-rose-500", text: "text-rose-300", label: "Offline" },
};

const EngineCard = ({ e }) => {
  const t = TONE[e.status] || TONE.offline;
  return (
    <div data-testid={`engine-card-${e.id}`} className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-display font-semibold text-lg">{e.name}</div>
          <div className="text-xs text-neutral-500">{e.powers}</div>
        </div>
        <span data-testid={`engine-status-${e.id}`} className={`inline-flex items-center gap-2 text-sm font-medium ${t.text}`}>
          <span className={`w-2.5 h-2.5 rounded-full ${t.dot} ${e.status === "online" ? "animate-pulse" : ""}`} />
          {t.label}
        </span>
      </div>
      <div data-testid={`engine-detail-${e.id}`} className="text-sm text-neutral-300 break-words">{e.detail}</div>
      <div className="text-xs text-neutral-500">{(e.latency_ms / 1000).toFixed(1)}s response</div>
    </div>
  );
};

const KAGGLE_TONE = { running: "text-emerald-300", queued: "text-amber-300", new_script: "text-amber-300",
  complete: "text-neutral-400", error: "text-rose-300", none: "text-neutral-500", unknown: "text-neutral-500" };

function KagglePanel({ authHeader, onChange }) {
  const [k, setK] = useState(null);
  const [act, setAct] = useState(null);
  const load = useCallback(() => axios.get(`${API}/gpu-admin/kaggle`, { headers: authHeader }).then(({ data }) => setK(data)).catch(() => {}), [authHeader]);
  useEffect(() => { load(); const t = setInterval(() => document.visibilityState === "visible" && load(), 20000); return () => clearInterval(t); }, [load]);

  const launch = async () => {
    setAct("launch");
    try {
      const { data } = await axios.post(`${API}/gpu-admin/kaggle/launch`, null, { headers: authHeader });
      if (data.launched) toast.success("Free Kaggle GPU is starting. It comes online in about 6–10 minutes.");
      else toast.message(data.reason || "Nothing to start");
      load(); onChange?.();
    } catch (e) { toast.error(e?.response?.data?.detail || "Could not start the Kaggle GPU"); } finally { setAct(null); }
  };
  const stop = async () => {
    setAct("stop");
    try {
      const { data } = await axios.post(`${API}/gpu-admin/stop`, null, { headers: authHeader });
      toast.success(data.stop_requested ? "Stop sent. The worker finishes its current clip, then shuts down." : "No GPU worker is online");
      load(); onChange?.();
    } catch { toast.error("Could not stop the GPU worker"); } finally { setAct(null); }
  };

  if (!k) return null;
  if (!k.configured) {
    return (
      <div className="mt-5 rounded-2xl border border-white/10 bg-white/[0.03] p-5 text-sm text-neutral-400" data-testid="kaggle-panel">
        Free Kaggle GPU is not connected. Add <code>KAGGLE_API_TOKEN</code> and <code>KAGGLE_USERNAME</code> to the backend to start GPUs on demand.
      </div>
    );
  }
  return (
    <div className="mt-5 rounded-2xl border border-[#00F0FF]/25 bg-[#00F0FF]/5 p-5" data-testid="kaggle-panel">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-semibold text-white"><Gift className="w-4 h-4 text-[#00F0FF]" /> Free Kaggle GPU · on demand</div>
          <p className="text-xs text-neutral-400 mt-1">
            Account <b className="text-neutral-200">{k.username}</b> · Tesla T4 · starts automatically on the first video request and shuts down after {k.max_idle_min} idle minutes
          </p>
          <p className="text-sm mt-2" data-testid="kaggle-status">
            Kaggle session: <b className={KAGGLE_TONE[k.status] || "text-neutral-300"}>{k.status === "none" ? "never started" : k.status}</b>
            {k.boot && <span className="text-neutral-400"> · {k.boot.label}{k.boot.detail ? ` (${k.boot.detail})` : ""}</span>}
            {k.message && <span className="text-rose-300"> · {k.message}</span>}
          </p>
          <p className="text-[11px] text-neutral-500 mt-1">{k.launches_7d} launch{k.launches_7d === 1 ? "" : "es"} this week · Kaggle gives 30 free GPU hours a week</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button data-testid="kaggle-launch-btn" onClick={launch} disabled={!!act}
            className="rounded-full bg-[#00F0FF] text-black hover:bg-[#00d4de] font-semibold">
            {act === "launch" ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Rocket className="w-4 h-4 mr-2" />} Start GPU now
          </Button>
          <Button data-testid="kaggle-stop-btn" onClick={stop} disabled={!!act} variant="outline"
            className="rounded-full border-white/15 bg-transparent text-white hover:bg-white/10">
            {act === "stop" ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Square className="w-4 h-4 mr-2" />} Stop
          </Button>
          <a href={k.url} target="_blank" rel="noreferrer" data-testid="kaggle-open-link"
            className="inline-flex items-center h-9 rounded-full border border-white/15 px-4 text-sm text-neutral-200 hover:bg-white/10">
            <ExternalLink className="w-4 h-4 mr-2" /> Kaggle notebook
          </a>
        </div>
      </div>
    </div>
  );
}

const AWS_TONE = { running: "text-emerald-300", pending: "text-amber-300", stopping: "text-amber-300", stopped: "text-neutral-400" };

function AwsPanel({ authHeader, onChange }) {
  const [a, setA] = useState(null);
  const [act, setAct] = useState(null);
  const load = useCallback(() => axios.get(`${API}/gpu-admin/aws`, { headers: authHeader }).then(({ data }) => setA(data)).catch(() => {}), [authHeader]);
  useEffect(() => { load(); const t = setInterval(() => document.visibilityState === "visible" && load(), 20000); return () => clearInterval(t); }, [load]);

  const call = async (name, path, ok) => {
    setAct(name);
    try {
      const { data } = await axios.post(`${API}/gpu-admin/aws/${path}`, null, { headers: authHeader });
      if (data.ok === false || data.stopped === false) toast.message(data.reason || "Nothing to do");
      else toast.success(ok);
      load(); onChange?.();
    } catch (e) { toast.error(e?.response?.data?.detail || "AWS request failed"); } finally { setAct(null); }
  };

  if (!a) return null;
  if (!a.configured) {
    return (
      <div className="mt-5 rounded-2xl border border-white/10 bg-white/[0.03] p-5 text-sm text-neutral-400" data-testid="aws-panel">
        AWS GPU is not connected. Add <code>AWS_ACCESS_KEY_ID</code> and <code>AWS_SECRET_ACCESS_KEY</code> to the backend to run a dedicated GPU.
      </div>
    );
  }
  const st = a.instance?.state || "none";
  const quotaLow = a.quota != null && a.quota < a.quota_needed;
  return (
    <div className="mt-5 rounded-2xl border border-emerald-400/25 bg-emerald-400/5 p-5" data-testid="aws-panel">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-semibold text-white"><Server className="w-4 h-4 text-emerald-300" /> AWS GPU · {a.mode === "always_on" ? "always on" : "on demand"}</div>
          <p className="text-xs text-neutral-400 mt-1">
            {a.instance_type} (NVIDIA A10G 24GB) · {a.region} · serves {a.models.join(", ")} · first choice for every video, Kaggle is the backup
          </p>
          <p className="text-sm mt-2 break-words" data-testid="aws-status">
            Server: <b className={AWS_TONE[st] || "text-neutral-500"}>{st === "none" ? "not created yet" : st}</b>
            {a.instance && <span className="text-neutral-500"> · {a.instance.instance_id}{a.instance.az ? ` · ${a.instance.az}` : ""}</span>}
            {a.boot && <span className="text-neutral-400"> · {a.boot.label}{a.boot.detail ? ` (${a.boot.detail})` : ""}</span>}
            {a.paused && <span className="text-amber-300"> · paused by admin</span>}
          </p>
          {quotaLow && (
            <p className="text-xs text-amber-300 mt-1" data-testid="aws-quota">
              GPU quota is {a.quota} vCPU, needs {a.quota_needed}.
              {a.quota_request ? ` Increase request: ${a.quota_request.status}${a.quota_request.case_id ? ` (support case ${a.quota_request.case_id})` : ""}. The server starts by itself once AWS approves it.` : " Request an increase in AWS Service Quotas."}
            </p>
          )}
          {a.error && !quotaLow && <p className="text-xs text-rose-300 mt-1 break-words" data-testid="aws-error">{a.error}</p>}
        </div>
        <div className="flex flex-wrap gap-2 shrink-0">
          <Button data-testid="aws-start-btn" onClick={() => call("start", "start", "AWS GPU is starting. First boot takes about 15–25 minutes, later starts about 3–5.")} disabled={!!act}
            className="rounded-full bg-emerald-400 text-black hover:bg-emerald-300 font-semibold">
            {act === "start" ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Rocket className="w-4 h-4 mr-2" />} Start
          </Button>
          <Button data-testid="aws-stop-btn" onClick={() => call("stop", "stop", "AWS GPU is stopping. It stays off until you press Start.")} disabled={!!act} variant="outline"
            className="rounded-full border-white/15 bg-transparent text-white hover:bg-white/10">
            {act === "stop" ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Square className="w-4 h-4 mr-2" />} Stop
          </Button>
        </div>
      </div>
    </div>
  );
}

function GpuPanel({ authHeader }) {
  const [gpu, setGpu] = useState(null);
  const [dl, setDl] = useState(false);
  const load = useCallback(() => axios.get(`${API}/gpu-admin/overview`, { headers: authHeader }).then(({ data }) => setGpu(data)).catch(() => {}), [authHeader]);
  useEffect(() => { load(); const t = setInterval(() => document.visibilityState === "visible" && load(), 15000); return () => clearInterval(t); }, [load]);

  const download = async () => {
    setDl(true);
    try {
      const res = await axios.get(`${API}/gpu-admin/notebook`, { headers: authHeader, responseType: "blob",
        params: { gateway: `${process.env.REACT_APP_BACKEND_URL}/api/gpu`, models: "frasberg-motion-free" } });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = "frasberg-free-gpu-worker.ipynb"; a.click();
      URL.revokeObjectURL(url);
      toast.success("Notebook downloaded. Upload it to Kaggle or Colab and run all cells.");
    } catch { toast.error("Could not build the notebook"); } finally { setDl(false); }
  };

  const online = gpu?.workers.filter((w) => w.online) || [];
  return (
    <section className="mt-14" data-testid="gpu-panel">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <h2 className="font-display font-bold text-2xl flex items-center gap-2"><Cpu className="w-5 h-5 text-[#00F0FF]" /> Frasberg GPU</h2>
          <p className="text-sm text-neutral-400 mt-1" data-testid="gpu-summary">
            {gpu ? `${online.length} worker${online.length === 1 ? "" : "s"} online · ${gpu.jobs.queued} queued · ${gpu.jobs.running} rendering · ${gpu.jobs.completed} done · ${gpu.jobs.failed} failed` : "Loading…"}
          </p>
        </div>
        <Button data-testid="gpu-notebook-btn" onClick={download} disabled={dl}
          className="rounded-full bg-[#00F0FF] text-black hover:bg-[#00d4de] font-semibold">
          {dl ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Download className="w-4 h-4 mr-2" />} Free GPU worker notebook
        </Button>
      </div>

      <AwsPanel authHeader={authHeader} onChange={load} />
      <KagglePanel authHeader={authHeader} onChange={load} />

      <div className="mt-5 rounded-2xl border border-white/10 bg-white/[0.02] p-5 text-sm text-neutral-300" data-testid="gpu-free-howto">
        <div className="flex items-center gap-2 font-semibold text-white"><Gift className="w-4 h-4 text-[#00F0FF]" /> Manual option: run the worker yourself</div>
        <ol className="mt-2 list-decimal list-inside space-y-1 text-neutral-400">
          <li>Download the notebook above. It already contains this gateway URL and your worker secret, so keep it private.</li>
          <li>On <b className="text-neutral-200">kaggle.com</b>, go to New Notebook → File → Import Notebook, set Accelerator to <b className="text-neutral-200">GPU T4 x1</b> and Internet to On, then click Run All. Kaggle gives 30 free GPU hours a week. You can also use Colab's free T4.</li>
          <li><b className="text-neutral-200">Frasberg Motion Free</b> turns online in the Video Creator within about a minute. The first run downloads around 10GB of weights.</li>
        </ol>
      </div>

      <div className="mt-5 grid sm:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="gpu-engines">
        {gpu?.engines.map((e) => (
          <div key={e.id} data-testid={`gpu-engine-${e.id}`} className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-sm">{e.name}</span>
              <span className={`text-xs ${e.status === "online" ? "text-emerald-300" : e.status === "on-demand" ? "text-[#00F0FF]" : "text-neutral-500"}`}>{e.status === "online" ? `${e.workers_online} online${e.warm ? " · warm" : ""}` : e.status === "on-demand" ? "on demand" : "offline"}</span>
            </div>
            <p className="text-[11px] text-neutral-500 mt-1">{e.built_on} · needs {e.min_vram_gb}GB+ VRAM · {e.queue_depth} queued</p>
          </div>
        ))}
      </div>

      <div className="mt-5 rounded-xl border border-white/10 overflow-hidden" data-testid="gpu-workers">
        {gpu && !gpu.workers.length && <p className="p-4 text-sm text-neutral-500" data-testid="gpu-no-workers">No GPU workers have connected in the last hour.</p>}
        {gpu?.workers.map((w) => (
          <div key={w.worker_id} data-testid={`gpu-worker-${w.worker_id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 border-b border-white/5 text-sm last:border-0">
            <span className={`w-2 h-2 rounded-full ${w.online ? "bg-emerald-400" : "bg-neutral-600"}`} />
            <span className="font-mono text-xs">{w.worker_id}</span>
            <span className="text-neutral-400 text-xs">{w.gpu || "unknown GPU"}{w.vram_gb ? ` · ${w.vram_gb}GB` : ""}</span>
            <span className="text-neutral-500 text-xs">{w.models.join(", ")}</span>
            <span className="text-neutral-500 text-xs md:ml-auto">{w.busy ? "rendering" : w.loaded_model ? `warm: ${w.loaded_model}` : "idle"} · seen {new Date(w.last_seen).toLocaleTimeString()}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function EngineStatus() {
  const { user, authHeader } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/engines/status`, { params: { refresh }, headers: authHeader });
      setData(data);
      setDenied(false);
    } catch {
      setDenied(true);
    } finally {
      setLoading(false);
    }
  }, [authHeader]);

  useEffect(() => { if (user) load(); else { setDenied(true); setLoading(false); } }, [user, load]);

  if (denied) {
    return (
      <div className="min-h-screen bg-[#05060A] text-white">
        <Navbar />
        <main className="max-w-xl mx-auto px-5 pt-40 pb-24 text-center" data-testid="engine-status-denied">
          <h1 className="font-display font-bold text-3xl">Admins only</h1>
          <p className="mt-3 text-neutral-400">Log in with an admin account to view engine status.</p>
        </main>
        <Footer />
      </div>
    );
  }

  const online = data?.engines.filter((e) => e.status === "online").length ?? 0;

  return (
    <div className="min-h-screen bg-[#05060A] text-white">
      <Navbar />
      <main className="max-w-5xl mx-auto px-5 md:px-8 pt-28 pb-24" data-testid="engine-status-page">
        <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-neutral-300 mb-5">
          <Activity className="w-3.5 h-3.5 text-[#00F0FF]" /> Live engine status
        </div>
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
          <div>
            <h1 className="font-display font-bold tracking-tight text-4xl md:text-5xl">
              Frasberg Creator <span className="text-[#00F0FF]">engines</span>
            </h1>
            <p data-testid="engine-summary" className="mt-3 text-neutral-400 text-sm md:text-base">
              {data ? `${online} of ${data.engines.length} engines online · checked ${new Date(data.checked_at).toLocaleTimeString()}` : "Running live checks on every engine…"}
            </p>
          </div>
          <Button data-testid="engine-refresh-btn" onClick={() => load(true)} disabled={loading}
            className="rounded-full bg-[#00F0FF] text-black hover:bg-[#00d4de] font-semibold">
            {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
            {loading ? "Checking…" : "Re-check now"}
          </Button>
        </div>
        <div className="mt-10 grid sm:grid-cols-2 gap-4">
          {data?.engines.map((e) => <EngineCard key={e.id} e={e} />)}
        </div>
        <GpuPanel authHeader={authHeader} />
      </main>
      <Footer />
    </div>
  );
}
