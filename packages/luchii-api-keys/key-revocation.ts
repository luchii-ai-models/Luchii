import { GatewayError } from './api-key';
import type { ApiKeyStore } from './api-key-store';
import { emitKeyEvent } from './key-events';

export async function revokeApiKey(store: ApiKeyStore, keyId: string): Promise<void> {
  const key = await store.findById(keyId);
  if (!key) throw new GatewayError('KEY_NOT_FOUND');
  await store.save({ ...key, status: 'disabled' });
  emitKeyEvent('revoked', key.id, key.ownerId);
}
