import type { NextFunction, Request, Response } from 'express';
import { GatewayError } from './api-key';
import { hasPermission } from './api-key-permissions';

export function requirePermission(permission: string) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!hasPermission(req.apiKey?.permissions ?? [], permission)) {
      const e = new GatewayError('PERMISSION_DENIED', { required: permission });
      return res.status(e.status).json(e.toBody(req.requestId));
    }
    next();
  };
}

export const ROUTE_PERMISSIONS: Record<string, string> = {
  '/v1/chat': 'chat.generate',
  '/v1/image/generate': 'image.generate',
  '/v1/music/generate': 'music.generate',
  '/v1/gt6/run': 'gt6.run',
  '/v1/agents/execute': 'agents.execute',
  '/v1/memory/read': 'memory.read',
  '/v1/memory/write': 'memory.write',
};

// Routes without a mapping are denied.
export function permissionMiddleware(req: Request, res: Response, next: NextFunction) {
  const required = ROUTE_PERMISSIONS[req.path];
  if (!required) {
    const e = new GatewayError('PERMISSION_DENIED');
    return res.status(e.status).json(e.toBody(req.requestId));
  }
  return requirePermission(required)(req, res, next);
}
