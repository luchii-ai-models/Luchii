import { checkService } from './health-check';
import type { RuntimeHealth } from './status';

export function checkRuntime(name: string, url: string): Promise<RuntimeHealth> {
  return checkService(name, url);
}
