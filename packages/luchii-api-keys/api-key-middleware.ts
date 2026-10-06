import type { NextFunction, Request, Response } from 'express';
import { GatewayError, type ApiKey } from './api-key';
import { getApiKeyByHash } from './api-key-store';
import { hashApiKey } from './api-key-hash';
import { extractApiKey } from './api-key-validator';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      apiKey?: ApiKey;
      ownerId?: string;
      workspaceId?: string;
      requestId?: string;
    }
  }
}

export async function apiKeyMiddleware(req: Request, res: Response, next: NextFunction) {
  try {
    const raw = extractApiKey(req.headers);
    if (!raw) throw new GatewayError('KEY_NOT_PROVIDED');

    const record = await getApiKeyByHash(hashApiKey(raw), raw);
    if (!record) throw new GatewayError('KEY_NOT_FOUND');
    if (record.status === 'suspended') throw new GatewayError('ACCOUNT_SUSPENDED');
    if (record.status !== 'active') throw new GatewayError('KEY_DISABLED');

    req.apiKey = record;
    req.ownerId = record.ownerId;
    req.workspaceId = record.workspaceId;
    return next();
  } catch (err) {
    const e = err instanceof GatewayError ? err : new GatewayError('SERVICE_UNAVAILABLE');
    return res.status(e.status).json(e.toBody(req.requestId));
  }
}
