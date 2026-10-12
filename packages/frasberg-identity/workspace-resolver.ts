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

const WORKSPACE_REGEX = /^(ws_[a-zA-Z0-9_-]{3,128}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

export async function workspaceResolver(req: Request, res: Response, next: NextFunction) {
  try {
    const header = req.headers['x-workspace-id'];
    const workspaceId = req.apiKey?.workspaceId ?? (Array.isArray(header) ? header[0] : header);
    if (workspaceId == null) throw new GatewayError('WORKSPACE_NOT_FOUND');

    const normalized = String(workspaceId).trim();
    if (normalized.length > 128 || !WORKSPACE_REGEX.test(normalized)) throw new GatewayError('INVALID_WORKSPACE_ID');

    req.workspaceId = normalized;
    return next();
  } catch (err) {
    const e = err instanceof GatewayError ? err : new GatewayError('WORKSPACE_RESOLUTION_FAILED');
    return res.status(e.status).json(e.toBody(req.requestId));
  }
}
