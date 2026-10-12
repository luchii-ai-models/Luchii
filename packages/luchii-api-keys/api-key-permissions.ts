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
