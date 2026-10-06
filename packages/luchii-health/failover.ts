import { GatewayError } from '../luchii-api-keys/api-key';
import type { RuntimeHealth } from './status';

// Returns the first non-offline service; 503 RUNTIME_UNAVAILABLE when none remain.
export function pickHealthy(candidates: RuntimeHealth[]): RuntimeHealth {
  const pick =
    candidates.find((c) => c.status === 'healthy') ?? candidates.find((c) => c.status === 'degraded');
  if (!pick) throw new GatewayError('RUNTIME_UNAVAILABLE');
  return pick;
}
