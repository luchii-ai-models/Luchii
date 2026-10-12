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
