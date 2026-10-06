import type { NextFunction, Request, Response } from 'express';
import { randomUUID } from 'node:crypto';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      requestId?: string;
    }
  }
}

const REQUEST_ID_REGEX = /^req_[a-zA-Z0-9_-]{8,128}$/;

export function generateRequestId() {
  return `req_${randomUUID().replace(/-/g, '')}`;
}

export function requestIdMiddleware(req: Request, res: Response, next: NextFunction) {
  const incoming = req.headers['x-request-id'];
  const requestId = typeof incoming === 'string' && REQUEST_ID_REGEX.test(incoming) ? incoming : generateRequestId();

  req.requestId = requestId;
  res.setHeader('x-request-id', requestId);
  next();
}
