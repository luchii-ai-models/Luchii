// Video is the primary heavy modality — keep clips short unless long-form is requested.
export interface Gt6VideoJob {
  raceId: string;
  kind: "replay" | "preview" | "summary";
  durationSec: number;
}
