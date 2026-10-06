export interface GT6PhysicsState {
  position: [number, number, number];
  velocity: [number, number, number];
}

export function stepPhysics(s: GT6PhysicsState, dt: number): GT6PhysicsState {
  return {
    position: [s.position[0] + s.velocity[0] * dt, s.position[1] + s.velocity[1] * dt, s.position[2] + s.velocity[2] * dt],
    velocity: s.velocity,
  };
}
