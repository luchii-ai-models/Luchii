export class AgentMemory {
  private readonly entries = new Map<string, unknown[]>();

  remember(ownerId: string, entry: unknown) {
    const list = this.entries.get(ownerId) ?? [];
    list.push(entry);
    this.entries.set(ownerId, list);
  }

  recall(ownerId: string, limit = 20): unknown[] {
    return (this.entries.get(ownerId) ?? []).slice(-limit);
  }
}
