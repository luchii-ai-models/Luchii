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
