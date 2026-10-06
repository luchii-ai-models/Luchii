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
