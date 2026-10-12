// GT6 worlds persist in the Frasberg WorldGraph (POST /api/v1/worldgraph).
export interface Gt6World {
  worldId: string;
  trackId: string;
  vehicleClassIds: string[];
  lapCount: number;
}
