import type { LuchiiModel } from './index';

export function fastest(candidates: LuchiiModel[], latencyMs: Partial<Record<LuchiiModel, number>>): LuchiiModel {
  const ms = (m: LuchiiModel) => latencyMs[m] ?? Number.POSITIVE_INFINITY;
  return candidates.reduce((a, b) => (ms(b) < ms(a) ? b : a));
}
