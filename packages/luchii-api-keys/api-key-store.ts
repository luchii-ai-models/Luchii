import { ApiKey } from "./api-key";

export class ApiKeyStore {
  private readonly byHash = new Map<string, ApiKey>();

  save(key: ApiKey) {
    this.byHash.set(key.hash, key);
  }

  findByHash(hash: string): ApiKey | undefined {
    return this.byHash.get(hash);
  }

  remove(hash: string) {
    this.byHash.delete(hash);
  }
}
