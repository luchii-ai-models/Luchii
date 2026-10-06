export type LuchiiModel =
  | "luchii-70b"
  | "luchii-vision"
  | "luchii-music"
  | "gt6-runtime";

export class ModelRouter {
  route(input: string): LuchiiModel {
    const text = input.toLowerCase();
    if (/(image|photo|picture|render|see|look)/.test(text)) return "luchii-vision";
    if (/(music|beat|song|melody|remix)/.test(text)) return "luchii-music";
    if (/(race|lap|physics|track|simulat)/.test(text)) return "gt6-runtime";
    return "luchii-70b";
  }
}
