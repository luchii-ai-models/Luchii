export interface LuchiiRequest {
  model: string;
  input: string;
  ownerId: string;
}

export interface LuchiiResponse {
  model: string;
  output: string;
  latencyMs: number;
}

export const LUCHII_MODELS = ["luchii-70b", "luchii-vision", "luchii-music", "gt6-runtime"] as const;
