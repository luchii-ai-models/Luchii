import type { LuchiiModel } from './index';

// Relative cost units per request.
export const MODEL_COST: Record<LuchiiModel, number> = {
  'luchii-chat': 1,
  'luchii-vision': 3,
  'luchii-music': 2,
  'gt6-runtime': 4,
};

export function cheapest(candidates: LuchiiModel[]): LuchiiModel {
  return candidates.reduce((a, b) => (MODEL_COST[b] < MODEL_COST[a] ? b : a));
}
