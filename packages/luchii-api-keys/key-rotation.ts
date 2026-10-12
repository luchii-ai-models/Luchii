import { randomUUID } from 'node:crypto';
import { GatewayError } from './api-key';
import type { ApiKeyStore } from './api-key-store';
import { emitKeyEvent } from './key-events';
import { generateApiKey } from './generate-key';
import { revokeApiKey } from './key-revocation';

// Issues a replacement key with the same owner/permissions and revokes the old one.
export async function rotateApiKey(store: ApiKeyStore, keyId: string) {
  const old = await store.findById(keyId);
  if (!old) throw new GatewayError('KEY_NOT_FOUND');

  const { raw, hash } = generateApiKey();
  const fresh = { ...old, id: randomUUID(), hash, status: 'active' as const, requestsToday: 0, createdAt: Date.now() };
  await store.save(fresh);
  await revokeApiKey(store, old.id);
  emitKeyEvent('rotated', fresh.id, fresh.ownerId);
  return { raw, key: fresh };
}
