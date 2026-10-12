import { GatewayError } from '../luchii-api-keys/api-key';
import type { ApiKey } from '../luchii-api-keys/api-key';
import { assertPermission } from '../luchii-api-keys/api-key-permissions';
import type { ApiKeyStore } from '../luchii-api-keys/api-key-store';
import { recordUsage } from '../luchii-api-keys/api-key-usage';
import { extractApiKey, validateApiKey } from '../luchii-api-keys/api-key-validator';
import type { PlanResolver } from '../frasberg-checkout';
import type { IdentityResolver } from '../frasberg-identity';
import { enforceRateLimit } from '../luchii-rate-limiter';
import { LuchiiModelRouter, type LuchiiModel } from '../luchii-model-router';

export interface GatewayDeps {
  keys: ApiKeyStore;
  identity: IdentityResolver;
  plans: PlanResolver;
  router: LuchiiModelRouter;
}

export interface GatewayResult {
  key: ApiKey;
  model: LuchiiModel;
}

const MODEL_PERMISSION: Record<LuchiiModel, string> = {
  'luchii-chat': 'chat.generate',
  'luchii-vision': 'image.generate',
  'luchii-music': 'music.generate',
  'gt6-runtime': 'gt6.run',
};

// Request -> key -> validate -> owner -> workspace -> plan -> permissions -> rate limit -> router -> model
export async function runGatewayFlow(
  deps: GatewayDeps,
  headers: Record<string, string | string[] | undefined>,
  input: string,
): Promise<GatewayResult> {
  let key = await validateApiKey(deps.keys, extractApiKey(headers));
  if (!(await deps.identity.getOwner(key.ownerId))) throw new GatewayError('OWNER_NOT_FOUND');
  if (!(await deps.identity.getWorkspace(key.workspaceId))) throw new GatewayError('WORKSPACE_NOT_FOUND');
  const plan = await deps.plans.getPlan(key.ownerId);
  const model = deps.router.route(input);
  assertPermission(key.permissions, MODEL_PERMISSION[model]);
  key = await recordUsage(deps.keys, key);
  enforceRateLimit(plan, key.requestsToday);
  return { key, model };
}
