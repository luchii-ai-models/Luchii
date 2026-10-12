import { describe, expect, it, vi } from 'vitest';
import { buildApp } from '../src/app';
import { FrasbergGateway } from '@frasberg/shared';
import { DynamoRuntimeStateStore } from '../src/runtime-state-store';

function app(permissions: string[]) {
  return buildApp({
    apiKeys: [{ id: 'k', secret: 's', permissions: permissions as any }],
    fetchImpl: vi.fn() as unknown as typeof fetch,
    frasbergGateway: {} as unknown as FrasbergGateway,
  });
}
const auth = { authorization: 'Bearer s' };

describe('emergent/gt6 routes', () => {
  it('returns 404 for an unknown race', async () => {
    const r = await app(['jobs:read']).inject({ method: 'GET', url: '/api/gt6/nope/broadcast', headers: auth });
    expect(r.statusCode).toBe(404);
  });
  it('denies without permission', async () => {
    const r = await app(['chat']).inject({ method: 'GET', url: '/api/gt6/nope/broadcast', headers: auth });
    expect(r.statusCode).toBe(403);
  });

  it('does not grant planner permissions from request body', async () => {
    const music = vi.fn(async () => ({ id: 'music-job' }));
    const app = buildApp({
      apiKeys: [{ id: 'video-key', secret: 'video-secret', permissions: ['video', 'jobs:read'], tenants: ['tenant-video'] }],
      runtimeStateStore: new DynamoRuntimeStateStore(''),
      fetchImpl: vi.fn() as unknown as typeof fetch,
      frasbergGateway: {
        video: vi.fn(), music, image: vi.fn(), voice: vi.fn(), stt: vi.fn(), tts: vi.fn(), audio: vi.fn(), job: vi.fn(),
      } as unknown as FrasbergGateway,
    });

    const created = await app.inject({
      method: 'POST',
      url: '/api/emergent',
      headers: { authorization: 'Bearer video-secret' },
      payload: {
        intent: { wantsMusic: true },
        permissions: { music_generation: true, image_generation: true },
        maxCostWeight: 1000,
        raceConfig: {
          raceId: 'same-race',
          track: { id: 't1', name: 'Track', lengthKm: 5, weather: 'clear', trackTempC: 24, surfaceGrip: 1 },
          cars: [], driverProfiles: [], lapCount: 1,
        },
      },
    });

    expect(created.statusCode).toBe(200);
    expect(music).not.toHaveBeenCalled();
    await app.close();
  });

  it('persists races and worldgraph updates only within the authenticated tenant', async () => {
    const shared = new DynamoRuntimeStateStore('');
    const app = buildApp({
      apiKeys: [
        { id: 'key-a', secret: 'secret-a', permissions: ['video', 'jobs:read'], tenants: ['tenant-a'] },
        { id: 'key-b', secret: 'secret-b', permissions: ['video', 'jobs:read'], tenants: ['tenant-b'] },
      ],
      runtimeStateStore: shared,
      fetchImpl: vi.fn() as unknown as typeof fetch,
      frasbergGateway: {} as unknown as FrasbergGateway,
    });
    const payload = {
      intent: {},
      worldgraphUpdate: { id: 'world-1', payload: { name: 'Tenant A world' } },
      raceConfig: {
        raceId: 'shared-race-id',
        track: { id: 't1', name: 'Track', lengthKm: 5, weather: 'clear', trackTempC: 24, surfaceGrip: 1 },
        cars: [], driverProfiles: [], lapCount: 1,
      },
    };
    const created = await app.inject({
      method: 'POST', url: '/api/emergent', headers: { authorization: 'Bearer secret-a' }, payload,
    });
    expect(created.statusCode).toBe(200);
    expect(created.json().worldgraph).toMatchObject({ id: 'world-1', name: 'Tenant A world' });

    const sameTenant = await app.inject({
      method: 'GET', url: '/api/gt6/shared-race-id/broadcast', headers: { authorization: 'Bearer secret-a' },
    });
    const otherTenant = await app.inject({
      method: 'GET', url: '/api/gt6/shared-race-id/broadcast', headers: { authorization: 'Bearer secret-b' },
    });
    expect(sameTenant.statusCode).toBe(200);
    expect(otherTenant.statusCode).toBe(404);
    await app.close();
  });
});
