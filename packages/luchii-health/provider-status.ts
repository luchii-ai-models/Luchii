import type { RuntimeHealth } from './status';

export type ProviderStatus = 'operational' | 'degraded' | 'outage';

export function summarizeProvider(services: RuntimeHealth[]): ProviderStatus {
  if (services.length === 0 || services.every((s) => s.status === 'offline')) return 'outage';
  return services.every((s) => s.status === 'healthy') ? 'operational' : 'degraded';
}
