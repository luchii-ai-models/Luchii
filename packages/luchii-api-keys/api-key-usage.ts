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
