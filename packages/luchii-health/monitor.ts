import { checkService } from './health-check';
import type { RuntimeHealth } from './status';

export class HealthMonitor {
  private latest = new Map<string, RuntimeHealth>();

  constructor(private targets: Record<string, string>) {}

  async poll(): Promise<RuntimeHealth[]> {
    const results = await Promise.all(Object.entries(this.targets).map(([name, url]) => checkService(name, url)));
    results.forEach((r) => this.latest.set(r.service, r));
    return results;
  }

  get(service: string): RuntimeHealth | undefined {
    return this.latest.get(service);
  }
}
