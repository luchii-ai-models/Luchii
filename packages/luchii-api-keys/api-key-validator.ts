import { GatewayError, type ApiKey } from './api-key';
import { hashApiKey } from './api-key-hash';
import type { ApiKeyStore } from './api-key-store';

export function extractApiKey(headers: Record<string, string | string[] | undefined>): string | undefined {
  const direct = headers['x-api-key'] ?? headers['xi-api-key'];
  const value = direct ?? headers['authorization'];
  const str = Array.isArray(value) ? value[0] : value;
  return str ? str.replace(/^Bearer /, '') : undefined;
}

export async function validateApiKey(store: ApiKeyStore, raw: string | undefined): Promise<ApiKey> {
  if (!raw) throw new GatewayError('KEY_NOT_PROVIDED');
  const key = await store.findByHash(hashApiKey(raw));
  if (!key) throw new GatewayError('KEY_NOT_FOUND');
  if (key.status === 'suspended') throw new GatewayError('ACCOUNT_SUSPENDED');
  if (key.status !== 'active') throw new GatewayError('KEY_DISABLED');
  return key;
}
