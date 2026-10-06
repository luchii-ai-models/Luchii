import type { ApiKey } from './api-key';
import type { ApiKeyStore } from './api-key-store';

export async function recordUsage(store: ApiKeyStore, key: ApiKey): Promise<ApiKey> {
  const updated = { ...key, requestsToday: key.requestsToday + 1 };
  await store.save(updated);
  return updated;
}
