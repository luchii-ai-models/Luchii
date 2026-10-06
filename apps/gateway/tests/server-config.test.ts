import { describe, expect, test } from 'vitest';
import { loadConfig } from '../src/server';

const valid = {
  MONGO_URL: 'mongodb://localhost:27017',
  DB_NAME: 'frasberg',
  REDIS_URL: 'redis://localhost:6379',
  LUCHII_UPSTREAM_URL: 'https://runtime.example/v1/chat',
  LUCHII_UPSTREAM_API_KEY: 'server-secret',
  ALLOW_LEGACY_RAW_API_KEYS: 'false',
};

describe('gateway config', () => {
  test('requires explicit secret compatibility mode and production upstream URL', () => {
    expect(() => loadConfig(valid)).not.toThrow();
    expect(() => loadConfig({ ...valid, ALLOW_LEGACY_RAW_API_KEYS: undefined })).toThrow(/ALLOW_LEGACY_RAW_API_KEYS/);
    expect(() => loadConfig({ ...valid, LUCHII_UPSTREAM_URL: 'http://runtime.example/v1/chat' })).toThrow(/HTTPS/);
  });
});
