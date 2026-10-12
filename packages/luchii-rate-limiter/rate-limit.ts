import type { NextFunction, Request, Response } from 'express';
import { GatewayError } from '../luchii-api-keys/api-key';

const buckets = new Map<string, { count: number; resetAt: number }>();

export function rateLimit(limit = 1000, windowMs = 60_000) {
  return (req: Request, res: Response, next: NextFunction) => {
    const ownerId = req.ownerId;
    if (!ownerId) {
      const e = new GatewayError('OWNER_NOT_FOUND');
      return res.status(e.status).json(e.toBody(req.requestId));
    }

    const now = Date.now();
    let bucket = buckets.get(ownerId);
    if (!bucket || bucket.resetAt < now) {
      bucket = { count: 0, resetAt: now + windowMs };
      buckets.set(ownerId, bucket);
    }

    bucket.count++;
    if (bucket.count > limit) {
      const e = new GatewayError('RATE_LIMIT_EXCEEDED');
      return res.status(e.status).json(e.toBody(req.requestId));
    }
    next();
  };
}
