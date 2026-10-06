import type { RuntimeHealth } from './status';

export async function checkService(service: string, url: string, degradedMs = 1500, timeoutMs = 5000): Promise<RuntimeHealth> {
  const started = Date.now();
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
    const latencyMs = Date.now() - started;
    if (!res.ok) return { service, status: 'offline', latencyMs };
    return { service, status: latencyMs > degradedMs ? 'degraded' : 'healthy', latencyMs };
  } catch {
    return { service, status: 'offline', latencyMs: Date.now() - started };
  }
}
