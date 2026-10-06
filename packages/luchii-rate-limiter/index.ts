import { GatewayError } from '../luchii-api-keys/api-key';

export * from './rate-limit';

export interface Plan {
  id: string;
  dailyRequests: number;
}

export function enforceRateLimit(plan: Plan, requestsToday: number): void {
  if (requestsToday > plan.dailyRequests) throw new GatewayError('RATE_LIMIT_EXCEEDED');
}
