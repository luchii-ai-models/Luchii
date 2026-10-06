import { GatewayError } from '../../../packages/luchii-api-keys/api-key';
import type { LuchiiModel } from '../../../packages/luchii-model-router';

export interface RuntimeCall {
  model: LuchiiModel;
  path: string;
  body: unknown;
  requestId: string;
}

export type RuntimeClient = (call: RuntimeCall) => Promise<unknown>;

// OpenAI-compatible chat lives under /v1/chat/completions upstream.
const UPSTREAM_PATHS: Record<string, string> = { '/v1/chat': '/v1/chat/completions' };

export function createRuntimeClient(
  env: { url?: string; apiKey?: string } = {
    url: process.env.LUCHII_UPSTREAM_URL,
    apiKey: process.env.LUCHII_UPSTREAM_API_KEY,
  },
  timeoutMs = 40_000,
): RuntimeClient {
  return async ({ model, path, body, requestId }) => {
    if (!env.url || !env.apiKey) throw new GatewayError('RUNTIME_UNAVAILABLE');
    const root = env.url.split('/v1/')[0].replace(/\/$/, '');

    const requestBody: Record<string, unknown> = { ...(body as Record<string, unknown>), model };
    if (path === '/v1/chat' && typeof requestBody.input === 'string' && !Array.isArray(requestBody.messages)) {
      requestBody.messages = [{ role: 'user', content: requestBody.input }];
      delete requestBody.input;
    }

    let res: Response;
    try {
      res = await fetch(root + (UPSTREAM_PATHS[path] ?? path), {
        method: 'POST',
        headers: {
          // The caller's own key is never forwarded; the gateway authenticates upstream itself.
          authorization: `Bearer ${env.apiKey}`,
          'content-type': 'application/json',
          'x-request-id': requestId,
          'x-luchii-router': '1',
        },
        body: JSON.stringify(requestBody),
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch {
      throw new GatewayError('RUNTIME_UNAVAILABLE');
    }

    if (!res.ok) throw new GatewayError('MODEL_UNAVAILABLE');
    const contentLength = Number(res.headers.get('content-length') ?? 0);
    if (contentLength > 10_000_000) throw new GatewayError('MODEL_UNAVAILABLE');
    const text = await res.text();
    if (Buffer.byteLength(text) > 10_000_000) throw new GatewayError('MODEL_UNAVAILABLE');
    try {
      return JSON.parse(text) as unknown;
    } catch {
      throw new GatewayError('MODEL_UNAVAILABLE');
    }
  };
}
