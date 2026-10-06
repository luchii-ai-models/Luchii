import type { LuchiiModel } from '../luchii-model-router';

export interface AgentRouter {
  route(input: string): LuchiiModel;
}

export interface AgentMemory {
  recall(ownerId: string, query: string, limit?: number): Promise<string[]>;
  remember(ownerId: string, entry: string): Promise<void>;
}

export interface AgentIdentity {
  getOwner(ownerId: string): Promise<{ id: string } | null>;
}

export interface AgentOrchestrator {
  run(input: string): Promise<unknown>;
}

// Single runtime entry point for all Frasberg agents.
export class EmergentAgent {
  constructor(
    private router: AgentRouter,
    private memory: AgentMemory,
    private identity: AgentIdentity,
    private orchestrator: AgentOrchestrator,
  ) {}

  async execute(input: string) {
    const model = this.router.route(input);
    return {
      model,
      response: await this.orchestrator.run(input),
    };
  }
}
