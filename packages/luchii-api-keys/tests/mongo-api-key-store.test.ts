import { describe, expect, test, vi } from 'vitest';
import { MongoApiKeyStore } from '../mongo-api-key-store';

function collectionWith(document: Record<string, unknown> | null) {
  return {
    findOne: vi.fn(async () => document),
    createIndex: vi.fn(async () => 'ok'),
    updateOne: vi.fn(async () => ({ acknowledged: true })),
  } as any;
}

describe('MongoApiKeyStore', () => {
  test('maps active legacy keys, scopes, expiry, and workspace identity', async () => {
    const collection = collectionWith({
      id: 'key-1',
      key: 'frb_live_legacy',
      user_id: '550e8400-e29b-41d4-a716-446655440000',
      name: 'legacy',
      status: 'active',
      permissions: { music_generation: 'access', frasberg_agents: 'no_access' },
      created: '2025-01-01T00:00:00.000Z',
      expires_at: '2999-01-01T00:00:00.000Z',
    });
    const store = new MongoApiKeyStore(collection, { allowLegacyRawKeys: true });

    const key = await store.findByHash('hash', 'frb_live_legacy');

    expect(collection.findOne).toHaveBeenCalledWith({ $or: [{ key_hash: 'hash' }, { hash: 'hash' }, { key: 'frb_live_legacy' }] });
    expect(key).toMatchObject({
      id: 'key-1',
      ownerId: '550e8400-e29b-41d4-a716-446655440000',
      workspaceId: expect.stringMatching(/^ws_/),
      permissions: ['music.generate', 'chat.generate'],
      status: 'active',
    });
  });

  test('never queries the raw credential unless legacy mode is enabled', async () => {
    const collection = collectionWith(null);
    const store = new MongoApiKeyStore(collection);

    await store.findByHash('hash', 'frb_live_legacy');

    expect(collection.findOne).toHaveBeenCalledWith({ $or: [{ key_hash: 'hash' }, { hash: 'hash' }] });
  });

  test('maps revoked and expired keys to disabled', async () => {
    const revoked = new MongoApiKeyStore(collectionWith({ id: 'revoked', user_id: 'owner_1', status: 'revoked' }));
    const expired = new MongoApiKeyStore(collectionWith({ id: 'expired', user_id: 'owner_1', status: 'active', expires_at: '2000-01-01T00:00:00Z' }));

    expect((await revoked.findById('revoked'))?.status).toBe('disabled');
    expect((await expired.findById('expired'))?.status).toBe('disabled');
  });
});
