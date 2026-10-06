import type { NextFunction, Request, Response } from 'express';
import { GatewayError, type ApiKey } from '../luchii-api-keys/api-key';

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

const OWNER_REGEX = /^((owner|org|usr)_[a-zA-Z0-9_-]{3,128}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

export async function ownerResolver(req: Request, res: Response, next: NextFunction) {
  try {
    const header = req.headers['x-owner-id'];
    const ownerId = req.apiKey?.ownerId ?? (Array.isArray(header) ? header[0] : header);
    if (ownerId == null) throw new GatewayError('OWNER_NOT_FOUND');

    const normalized = String(ownerId).trim();
    if (normalized.length > 128 || !OWNER_REGEX.test(normalized)) throw new GatewayError('INVALID_OWNER_ID');

    req.ownerId = normalized;
    return next();
  } catch (err) {
    const e = err instanceof GatewayError ? err : new GatewayError('OWNER_RESOLUTION_FAILED');
    return res.status(e.status).json(e.toBody(req.requestId));
  }
}
