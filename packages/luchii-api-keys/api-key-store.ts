import type { ApiKey } from './api-key';

export interface ApiKeyStore {
  findByHash(hash: string, legacyRaw?: string): Promise<ApiKey | null>;
  findById(id: string): Promise<ApiKey | null>;
  save(key: ApiKey): Promise<void>;
}

export class InMemoryApiKeyStore implements ApiKeyStore {
  private keys = new Map<string, ApiKey>();

  async findByHash(hash: string) {
    return this.keys.get(hash) ?? null;
  }

  async findById(id: string) {
    return [...this.keys.values()].find((k) => k.id === id) ?? null;
  }

  async save(key: ApiKey) {
    this.keys.set(key.hash, key);
  }
}

let activeStore: ApiKeyStore | undefined;

export function setApiKeyStore(store: ApiKeyStore): void {
  activeStore = store;
}

export function getApiKeyByHash(hash: string, legacyRaw?: string): Promise<ApiKey | null> {
  if (!activeStore) throw new Error('API key store has not been configured');
  return activeStore.findByHash(hash, legacyRaw);
}
