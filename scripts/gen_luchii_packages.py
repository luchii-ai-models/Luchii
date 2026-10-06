import os

ROOT = "/app"
F = {}


def add(p, c):
    F[p] = c.strip() + "\n"


# ---- frasberg-agents: the single runtime ----
add("packages/frasberg-agents/emergent-agent.ts", """
export class EmergentAgent {
  constructor(
    private router,
    private memory,
    private identity,
    private orchestrator
  ) {}

  async execute(input: string) {
    const model = this.router.route(input);

    return {
      model,
      response: await this.orchestrator.run(input)
    };
  }
}
""")
add("packages/frasberg-agents/index.ts", 'export * from "./emergent-agent";')

# ---- luchii-api-keys ----
add("packages/luchii-api-keys/api-key.ts", """
export interface ApiKey {
  id: string;
  ownerId: string;
  workspaceId: string;
  name: string;
  hash: string;
  status:
    | "active"
    | "disabled"
    | "suspended";
  permissions: string[];
  requestsToday: number;
  createdAt: number;
}
""")
add("packages/luchii-api-keys/api-key-hash.ts", """
import crypto from "crypto";

export function hashApiKey(rawKey: string): string {
  return crypto.createHash("sha256").update(rawKey).digest("hex");
}
""")
add("packages/luchii-api-keys/api-key-store.ts", """
import { ApiKey } from "./api-key";

export class ApiKeyStore {
  private readonly byHash = new Map<string, ApiKey>();

  save(key: ApiKey) {
    this.byHash.set(key.hash, key);
  }

  findByHash(hash: string): ApiKey | undefined {
    return this.byHash.get(hash);
  }

  remove(hash: string) {
    this.byHash.delete(hash);
  }
}
""")
add("packages/luchii-api-keys/api-key-validator.ts", """
import { ApiKey } from "./api-key";
import { ApiKeyStore } from "./api-key-store";
import { hashApiKey } from "./api-key-hash";

export type ValidationResult =
  | { ok: true; key: ApiKey }
  | { ok: false; status: number; error: string; message: string };

// RULE: never say "invalid_key" unless the key hash truly does not exist.
export function validateApiKey(store: ApiKeyStore, rawKey: string | undefined): ValidationResult {
  if (!rawKey) {
    return { ok: false, status: 401, error: "key_not_found", message: "Missing bearer token" };
  }
  const key = store.findByHash(hashApiKey(rawKey));
  if (!key) {
    return { ok: false, status: 401, error: "key_not_found", message: "API key not found" };
  }
  if (key.status === "disabled") {
    return { ok: false, status: 403, error: "key_disabled", message: "This API key is disabled" };
  }
  if (key.status === "suspended") {
    return { ok: false, status: 403, error: "key_suspended", message: "This API key is suspended" };
  }
  return { ok: true, key };
}
""")
add("packages/luchii-api-keys/api-key-permissions.ts", """
import { ApiKey } from "./api-key";

export type PermissionResult =
  | { ok: true }
  | { ok: false; status: 403; error: "permission_denied"; required: string };

// 403 = permission missing — tell the user exactly WHICH permission.
export function requirePermission(key: ApiKey, required: string): PermissionResult {
  if (key.permissions.includes(required) || key.permissions.includes("*")) {
    return { ok: true };
  }
  return { ok: false, status: 403, error: "permission_denied", required };
}
""")
add("packages/luchii-api-keys/api-key-usage.ts", """
import { ApiKey } from "./api-key";

export type UsageResult =
  | { ok: true }
  | { ok: false; status: 429; error: "rate_limit_exceeded"; limit: number };

export function trackUsage(key: ApiKey, dailyLimit: number): UsageResult {
  if (key.requestsToday >= dailyLimit) {
    return { ok: false, status: 429, error: "rate_limit_exceeded", limit: dailyLimit };
  }
  key.requestsToday += 1;
  return { ok: true };
}
""")
add("packages/luchii-api-keys/api-key-middleware.ts", """
import { ApiKeyStore } from "./api-key-store";
import { validateApiKey } from "./api-key-validator";
import { requirePermission } from "./api-key-permissions";
import { trackUsage } from "./api-key-usage";

// Gateway flow: Request -> API Key -> Validate -> Owner -> Workspace -> Plan
//            -> Permissions -> Rate Limits -> Luchii Router -> Model
// Precise errors only: 401 key_not_found, 403 permission_denied, 429 rate_limit_exceeded, 503 service_unavailable.
export function apiKeyMiddleware(
  store: ApiKeyStore,
  options: { required?: string; dailyLimit?: number } = {},
) {
  return (req, res, next) => {
    const auth: string = req.headers["authorization"] ?? "";
    const raw = auth.startsWith("Bearer ") ? auth.slice(7) : undefined;

    const validated = validateApiKey(store, raw);
    if (!validated.ok) {
      return res.status(validated.status).json({ error: validated.error, message: validated.message });
    }

    if (options.required) {
      const perm = requirePermission(validated.key, options.required);
      if (!perm.ok) {
        return res.status(403).json({ error: "permission_denied", required: perm.required });
      }
    }

    const usage = trackUsage(validated.key, options.dailyLimit ?? 10000);
    if (!usage.ok) {
      return res.status(429).json({ error: "rate_limit_exceeded", limit: usage.limit });
    }

    req.apiKey = validated.key;
    req.owner = validated.key.ownerId;
    req.workspace = validated.key.workspaceId;
    next();
  };
}
""")
add("packages/luchii-api-keys/index.ts", """
export * from "./api-key";
export * from "./api-key-store";
export * from "./api-key-validator";
export * from "./api-key-hash";
export * from "./api-key-permissions";
export * from "./api-key-usage";
export * from "./api-key-middleware";
""")

# ---- luchii-health ----
add("packages/luchii-health/status.ts", """
export interface RuntimeHealth {
  service: string;

  status:
    | "healthy"
    | "degraded"
    | "offline";

  latencyMs: number;
}
""")
add("packages/luchii-health/health-check.ts", """
import { RuntimeHealth } from "./status";

export async function checkService(
  service: string,
  url: string,
  fetchImpl: typeof fetch = globalThis.fetch,
): Promise<RuntimeHealth> {
  const start = Date.now();
  try {
    const res = await fetchImpl(url, { signal: AbortSignal.timeout(4000) });
    return {
      service,
      status: res.ok ? "healthy" : "degraded",
      latencyMs: Date.now() - start,
    };
  } catch {
    return { service, status: "offline", latencyMs: Date.now() - start };
  }
}
""")
add("packages/luchii-health/monitor.ts", """
import { RuntimeHealth } from "./status";
import { checkService } from "./health-check";

export function startMonitor(
  targets: { service: string; url: string }[],
  onReport: (report: RuntimeHealth[]) => void,
  intervalMs = 30000,
) {
  const tick = async () => {
    const report = await Promise.all(targets.map((t) => checkService(t.service, t.url)));
    onReport(report);
  };
  tick();
  const timer = setInterval(tick, intervalMs);
  return () => clearInterval(timer);
}
""")
add("packages/luchii-health/failover.ts", """
import { RuntimeHealth } from "./status";

// 503 means YOUR infrastructure (ECS restarting, gateway down, runtime crashed,
// Luchii offline, queue saturated) — return service_unavailable, never invalid_key.
export function pickHealthy(report: RuntimeHealth[]): RuntimeHealth | undefined {
  return (
    report.find((r) => r.status === "healthy") ??
    report.find((r) => r.status === "degraded")
  );
}

export function serviceUnavailable() {
  return { status: 503, body: { error: "service_unavailable" } };
}
""")
add("packages/luchii-health/index.ts", """
export * from "./status";
export * from "./health-check";
export * from "./monitor";
export * from "./failover";
""")

# ---- luchii-model-router / luchii-core / luchii-rate-limiter ----
add("packages/luchii-model-router/index.ts", """
export type LuchiiModel =
  | "luchii-70b"
  | "luchii-vision"
  | "luchii-music"
  | "gt6-runtime";

export class ModelRouter {
  route(input: string): LuchiiModel {
    const text = input.toLowerCase();
    if (/(image|photo|picture|render|see|look)/.test(text)) return "luchii-vision";
    if (/(music|beat|song|melody|remix)/.test(text)) return "luchii-music";
    if (/(race|lap|physics|track|simulat)/.test(text)) return "gt6-runtime";
    return "luchii-70b";
  }
}
""")
add("packages/luchii-core/index.ts", """
export interface LuchiiRequest {
  model: string;
  input: string;
  ownerId: string;
}

export interface LuchiiResponse {
  model: string;
  output: string;
  latencyMs: number;
}

export const LUCHII_MODELS = ["luchii-70b", "luchii-vision", "luchii-music", "gt6-runtime"] as const;
""")
add("packages/luchii-rate-limiter/index.ts", """
export class RateLimiter {
  private readonly hits = new Map<string, number[]>();

  constructor(private readonly maxPerMinute = 60) {}

  check(keyId: string): { ok: true } | { ok: false; status: 429; error: "rate_limit_exceeded"; retryAfterSec: number } {
    const now = Date.now();
    const window = (this.hits.get(keyId) ?? []).filter((t) => now - t < 60000);
    if (window.length >= this.maxPerMinute) {
      return { ok: false, status: 429, error: "rate_limit_exceeded", retryAfterSec: Math.ceil((60000 - (now - window[0])) / 1000) };
    }
    window.push(now);
    this.hits.set(keyId, window);
    return { ok: true };
  }
}
""")

# ---- frasberg core/identity/checkout/memory ----
add("packages/frasberg-core/index.ts", """
export const FRASBERG_PLATFORM = "frasberg";
export interface Owner {
  id: string;
  email: string;
  plan: string;
}
export interface Workspace {
  id: string;
  ownerId: string;
  name: string;
}
""")
add("packages/frasberg-identity/index.ts", """
// Frasberg API Keys authenticate users. x-owner-id is read-only context — never overridden.
export function resolveOwner(headers: Record<string, string | undefined>, keyOwnerId: string): string {
  const header = headers["x-owner-id"];
  if (header && header !== keyOwnerId) {
    throw Object.assign(new Error("x-owner-id does not match authenticated owner"), { status: 403 });
  }
  return keyOwnerId;
}
""")
add("packages/frasberg-checkout/index.ts", """
export interface CheckoutSession {
  id: string;
  ownerId: string;
  planId: string;
  status: "open" | "complete" | "expired";
  createdAt: number;
}
""")
add("packages/frasberg-memory/index.ts", """
export class AgentMemory {
  private readonly entries = new Map<string, unknown[]>();

  remember(ownerId: string, entry: unknown) {
    const list = this.entries.get(ownerId) ?? [];
    list.push(entry);
    this.entries.set(ownerId, list);
  }

  recall(ownerId: string, limit = 20): unknown[] {
    return (this.entries.get(ownerId) ?? []).slice(-limit);
  }
}
""")

# ---- gt6-* ----
add("packages/gt6-physics/index.ts", """
export { updateCarPhysics, stepPhysics } from "../../config/emergent/physics-core";
export type { PhysicsParams } from "../../config/emergent/physics-core";
""")
add("packages/gt6-ai/index.ts", """
export { decideDriverAction, stepAI } from "../../config/emergent/ai-drivers";
export type { DriverProfile, DriverPersonality } from "../../config/emergent/ai-drivers";
""")
add("packages/gt6-race/index.ts", """
export { createInitialRaceState } from "../../config/emergent/simulation-state";
export type { RaceState, CarState, TrackState } from "../../config/emergent/simulation-state";
""")
add("packages/gt6-audio/index.ts", """
// Audio engine gate: requires audio_native / music_generation key permission upstream.
export interface Gt6AudioJob {
  raceId: string;
  kind: "engine" | "commentary" | "score";
  durationSec: number;
}
""")
add("packages/gt6-video/index.ts", """
// Video is the primary heavy modality — keep clips short unless long-form is requested.
export interface Gt6VideoJob {
  raceId: string;
  kind: "replay" | "preview" | "summary";
  durationSec: number;
}
""")
add("packages/gt6-world/index.ts", """
// GT6 worlds persist in the Frasberg WorldGraph (POST /api/v1/worldgraph).
export interface Gt6World {
  worldId: string;
  trackId: string;
  vehicleClassIds: string[];
  lapCount: number;
}
""")

# ---- apps/* roots ----
add("apps/gateway/index.ts", """
// Gateway flow: Request -> API Key -> Validate -> Owner -> Workspace -> Plan
//            -> Permissions -> Rate Limits -> Luchii Router -> Model
export { apiKeyMiddleware } from "../../packages/luchii-api-keys/api-key-middleware";
export { ModelRouter } from "../../packages/luchii-model-router";
""")
add("apps/api/index.ts", """
export { EmergentAgent } from "../../packages/frasberg-agents/emergent-agent";
export * from "../../packages/luchii-core";
""")
add("apps/checkout/index.ts", 'export * from "../../packages/frasberg-checkout";')
add("apps/runtime/index.ts", """
export * from "../../packages/gt6-physics";
export * from "../../packages/gt6-ai";
export * from "../../packages/gt6-race";
""")
add("apps/studio/index.ts", '// Studio UI lives at /app/studio/src — viewers for Behavior, Pattern, Structure engines.')

print(f"writing {len(F)} files")
for rel, content in F.items():
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
print("done")
