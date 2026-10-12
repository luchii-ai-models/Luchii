import { GatewayError } from '../luchii-api-keys/api-key';
import type { LuchiiModel } from './index';

export const FALLBACKS: Record<LuchiiModel, LuchiiModel[]> = {
  'luchii-chat': [],
  'luchii-vision': ['luchii-chat'],
  'luchii-music': [],
  'gt6-runtime': [],
};

export function resolveWithFallback(model: LuchiiModel, isAvailable: (m: LuchiiModel) => boolean): LuchiiModel {
  const chosen = [model, ...FALLBACKS[model]].find(isAvailable);
  if (!chosen) throw new GatewayError('MODEL_UNAVAILABLE');
  return chosen;
}
