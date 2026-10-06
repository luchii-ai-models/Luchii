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
