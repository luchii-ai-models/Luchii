import type { NextFunction, Request, Response } from 'express';
import { GatewayError } from '../luchii-api-keys/api-key';
import { redis } from './redis-client';

const INCREMENT_WINDOW = "local count = redis.call('INCR', KEYS[1]); if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]); end; return count";
let lastRedisWarning = 0;

export interface RateLimitOptions {
  // Public APIs fail open; admin and checkout routes should set this to true.
  failClosed?: boolean | ((req: Request) => boolean);
}

export function redisRateLimit(limit = 1000, windowSeconds = 60, options: RateLimitOptions = {}) {
  return async (req: Request, res: Response, next: NextFunction) => {
    if (!req.ownerId) {
      const e = new GatewayError('OWNER_NOT_FOUND');
      return res.status(e.status).json(e.toBody(req.requestId));
    }

    let count: number;
    try {
      const key = `rate:${req.ownerId}`;
      count = Number(await redis.eval(INCREMENT_WINDOW, 1, key, windowSeconds));
    } catch (error) {
      if (Date.now() - lastRedisWarning >= 60_000) {
        lastRedisWarning = Date.now();
        console.error('Rate limiter unavailable', error instanceof Error ? error.name : 'unknown error');
      }
      const failClosed = typeof options.failClosed === 'function' ? options.failClosed(req) : options.failClosed;
      if (failClosed) {
        const e = new GatewayError('RATE_LIMIT_SERVICE_UNAVAILABLE');
        return res.status(e.status).json(e.toBody(req.requestId));
      }
      return next();
    }

    if (count > limit) {
      const e = new GatewayError('RATE_LIMIT_EXCEEDED');
      return res.status(e.status).json(e.toBody(req.requestId));
    }
    return next();
  };
}
