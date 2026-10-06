export type LuchiiModel = 'luchii-chat' | 'luchii-vision' | 'luchii-music' | 'gt6-runtime';

export * from './cost-routing';
export * from './latency-routing';
export * from './model-fallback';

export class LuchiiModelRouter {
  route(input: string): LuchiiModel {
    const t = input.toLowerCase();
    if (/\b(music|song|melody|soundtrack)\b/.test(t)) return 'luchii-music';
    if (/\b(image|video|picture|render)\b/.test(t)) return 'luchii-vision';
    if (/\b(race|track|physics|gt6)\b/.test(t)) return 'gt6-runtime';
    return 'luchii-chat';
  }
}
