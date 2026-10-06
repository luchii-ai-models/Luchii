import type { Plan } from '../luchii-rate-limiter';

export interface PlanResolver {
  getPlan(ownerId: string): Promise<Plan>;
}
