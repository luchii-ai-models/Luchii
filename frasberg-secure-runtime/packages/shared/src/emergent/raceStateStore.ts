import { RaceState } from '../gt6/simulation-state';

export interface ReplayFrame {
  timestamp: number;
  cars: RaceState['cars'];
}

const MAX_RACES = 200;
const MAX_FRAMES = 2000;
const states = new Map<string, RaceState>();
const frames = new Map<string, ReplayFrame[]>();

export function saveRaceState(state: RaceState, ownerId = 'system') {
  const key = raceKey(ownerId, state.raceId);
  states.delete(key);
  states.set(key, state);
  const list = frames.get(key) ?? [];
  list.push({ timestamp: state.timestampMs, cars: state.cars });
  if (list.length > MAX_FRAMES) list.splice(0, list.length - MAX_FRAMES);
  frames.set(key, list);
  while (states.size > MAX_RACES) {
    const oldest = states.keys().next().value as string;
    states.delete(oldest);
    frames.delete(oldest);
  }
}

export function loadRaceState(raceId: string, ownerId = 'system'): RaceState | undefined {
  return states.get(raceKey(ownerId, raceId));
}

export function getReplayFrames(raceId: string, ownerId = 'system'): ReplayFrame[] {
  return frames.get(raceKey(ownerId, raceId)) ?? [];
}

function raceKey(ownerId: string, raceId: string): string {
  return JSON.stringify([ownerId, raceId]);
}
