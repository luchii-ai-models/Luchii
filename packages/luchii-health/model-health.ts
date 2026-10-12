import type { LuchiiModel } from '../luchii-model-router';
import { checkService } from './health-check';
import type { RuntimeHealth } from './status';

export interface ModelHealth extends RuntimeHealth {
  model: LuchiiModel;
}

export async function checkModels(endpoints: Partial<Record<LuchiiModel, string>>): Promise<ModelHealth[]> {
  const entries = Object.entries(endpoints) as [LuchiiModel, string][];
  return Promise.all(entries.map(async ([model, url]) => ({ model, ...(await checkService(model, url)) })));
}
