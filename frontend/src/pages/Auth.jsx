import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth, formatApiErrorDetail } from "../context/AuthContext";
import Starfield from "../components/site/Starfield";
import Seo from "../components/site/Seo";

export default function Auth() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/chat";
  const resetToken = params.get("token") || "";
  const initialMode = params.get("mode") === "signup" ? "signup" : params.get("mode") === "reset" ? "reset" : "login";
  const [mode, setMode] = useState(initialMode);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (mode === "forgot") {
        const res = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/auth/forgot-password`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, origin_url: window.location.origin }),
        });
        const d = await res.json();
        toast.success(d.message || "If that email has an account, a reset link is on its way.");
        setMode("login");
        return;
      }
      if (mode === "reset") {
        const res = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/auth/reset-password`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: resetToken, password }),
        });
        const d = await res.json();
        if (!res.ok) throw Object.assign(new Error(), { response: { data: d } });
        toast.success(d.message || "Password updated — sign in with your new password.");
        setPassword("");
        setMode("login");
        return;
      }
      if (mode === "signup") await register(name, email, password);
      else await login(email, password);
      toast.success(mode === "signup" ? "Welcome to Luchii" : "Welcome back");
      navigate(next);
    } catch (err) {
      if (mode === "signup" && err.response?.status === 409) {
        setMode("login");
        setError("This email already has a Luchii account — sign in below.");
      } else {
        setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative z-10 min-h-screen bg-lux-bg text-lux-text" data-testid="auth-page">
      <Seo title="Sign in — Luchii by Frasberg" description="Create your free Frasberg account to chat with Luchii, unlock image and video creation, and manage API keys." />
      <div className="pointer-events-none absolute inset-0 opacity-50"><Starfield /></div>

      <div className="relative mx-auto flex min-h-screen max-w-md flex-col justify-center px-5 py-16">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
        >
          <Link to="/" className="mb-8 inline-flex items-center gap-2 font-mono text-[15px] text-lux-text2 hover:text-lux-text" data-testid="auth-home-link">
            <ArrowLeft size={14} /> Back to Luchii
          </Link>

          <div className="glass rounded-3xl border border-lux-border p-8 shadow-2xl">
            <div className="flex items-center gap-3">
              <img src="/frasberg-mark-circle.png" alt="Frasberg" className="h-10 w-10 rounded-full" />
              <div>
                <h1 className="font-display text-2xl font-700 tracking-tight">
                  {mode === "signup" ? "Create your account" : mode === "forgot" ? "Reset your password" : mode === "reset" ? "Choose a new password" : "Sign in"}
                </h1>
                <p className="text-[15px] text-lux-text2">
                  {mode === "forgot" ? "We'll email you a reset link" : mode === "reset" ? "Make it at least 6 characters" : "Unlimited free chat with Luchii"}
                </p>
              </div>
            </div>

            <form onSubmit={submit} className="mt-7 space-y-4">
              {mode === "signup" && (
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  data-testid="auth-name-input"
                  className="w-full rounded-full border border-lux-border bg-lux-surface px-5 py-3 text-sm outline-none focus:border-lux-accent"
                />
              )}
              <input
                type="email"
                required={mode !== "reset"}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                data-testid="auth-email-input"
                className={`w-full rounded-full border border-lux-border bg-lux-surface px-5 py-3 text-sm outline-none focus:border-lux-accent ${mode === "reset" ? "hidden" : ""}`}
              />
              <input
                type="password"
                required={mode !== "forgot"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "reset" ? "New password (min 6 characters)" : "Password (min 6 characters)"}
                data-testid="auth-password-input"
                className={`w-full rounded-full border border-lux-border bg-lux-surface px-5 py-3 text-sm outline-none focus:border-lux-accent ${mode === "forgot" ? "hidden" : ""}`}
              />
              {error && <p className="px-2 text-[15px] text-red-400" data-testid="auth-error">{error}</p>}
              <button
                type="submit"
                disabled={busy}
                data-testid="auth-submit-btn"
                className="flex w-full items-center justify-center gap-2 rounded-full bg-lux-text px-5 py-3 text-sm font-600 text-lux-bg transition-transform duration-200 hover:-translate-y-0.5 disabled:opacity-50"
              >
                {busy && <Loader2 size={15} className="animate-spin" />}
                {mode === "signup" ? "Create account" : mode === "forgot" ? "Email me a reset link" : mode === "reset" ? "Set new password" : "Sign in"}
              </button>
              {mode === "login" && (
                <button
                  type="button"
                  onClick={() => { setMode("forgot"); setError(""); }}
                  data-testid="auth-forgot-link"
                  className="w-full text-center text-[14px] text-lux-text2 hover:text-lux-text"
                >
                  Forgot your password?
                </button>
              )}
              {mode === "forgot" && (
                <p className="px-2 text-center text-[13.5px] text-lux-text2">
                  Forgot which email you signed up with? Write to <a href="mailto:support@frasberg.com" className="text-lux-accent">support@frasberg.com</a> and we'll find your account.
                </p>
              )}
            </form>

            <button
              onClick={() => { setMode(mode === "signup" ? "login" : "signup"); setError(""); }}
              data-testid="auth-toggle-mode"
              className="mt-5 w-full text-center text-[15px] text-lux-text2 hover:text-lux-text"
            >
              {mode === "signup" ? "Already have an account? Sign in" : mode === "login" ? "New to Luchii? Create a free account" : "Back to sign in"}
            </button>
          </div>
        </motion.div>
      </div>
    </main>
  );
}
