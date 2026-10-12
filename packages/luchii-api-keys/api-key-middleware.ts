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
