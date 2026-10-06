export interface RuntimeHealth {
  service: string;

  status:
    | "healthy"
    | "degraded"
    | "offline";

  latencyMs: number;
}
