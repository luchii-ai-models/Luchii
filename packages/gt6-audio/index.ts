// Audio engine gate: requires audio_native / music_generation key permission upstream.
export interface Gt6AudioJob {
  raceId: string;
  kind: "engine" | "commentary" | "score";
  durationSec: number;
}
