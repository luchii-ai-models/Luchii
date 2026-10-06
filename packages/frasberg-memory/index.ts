export interface MemoryStore {
  recall(ownerId: string, query: string, limit?: number): Promise<string[]>;
  remember(ownerId: string, entry: string): Promise<void>;
}
