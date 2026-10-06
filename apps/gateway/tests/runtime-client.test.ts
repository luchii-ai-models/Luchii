import { afterEach, describe, expect, test, vi } from 'vitest';
import { createRuntimeClient } from '../src/runtime-client';

afterEach(() => vi.unstubAllGlobals());

describe('runtime client', () => {
  test('converts chat input and forwards only the gateway credential', async () => {
    const fetchMock = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) =>
      new Response(JSON.stringify({ choices: [{ message: { content: 'hello' } }] }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const runtime = createRuntimeClient({ url: 'https://runtime.example/v1/chat', apiKey: 'server-secret' });

    await runtime({
      model: 'luchii-chat',
      path: '/v1/chat',
      body: { input: 'hello', private: 'not forwarded as auth' },
      requestId: 'req_test',
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe('https://runtime.example/v1/chat/completions');
    expect(new Headers(init?.headers).get('authorization')).toBe('Bearer server-secret');
    expect(new Headers(init?.headers).get('x-request-id')).toBe('req_test');
    expect(JSON.parse(String(init?.body))).toMatchObject({
      model: 'luchii-chat',
      messages: [{ role: 'user', content: 'hello' }],
    });
    expect(JSON.parse(String(init?.body))).not.toHaveProperty('input');
  });

  test('converts network and malformed upstream responses to safe 503 errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('socket secret')));
    const runtime = createRuntimeClient({ url: 'https://runtime.example/v1/chat', apiKey: 'server-secret' });

    await expect(runtime({ model: 'luchii-chat', path: '/v1/chat', body: {}, requestId: 'req' }))
      .rejects.toMatchObject({ code: 'RUNTIME_UNAVAILABLE', status: 503 });

    vi.stubGlobal('fetch', vi.fn(async () => new Response('not-json', { status: 200 })));
    await expect(runtime({ model: 'luchii-chat', path: '/v1/chat', body: {}, requestId: 'req' }))
      .rejects.toMatchObject({ code: 'MODEL_UNAVAILABLE', status: 503 });
  });
});
