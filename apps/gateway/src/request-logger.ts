import type { NextFunction, Request, Response } from 'express';
import { redactObject } from '../../../packages/frasberg-core/redact';

export function requestLogger(req: Request, res: Response, next: NextFunction) {
  const started = Date.now();

  res.on('finish', () => {
    const payload = redactObject({
      requestId: req.requestId,
      ownerId: req.ownerId,
      workspaceId: req.workspaceId,
      method: req.method,
      path: req.path,
      headers: req.headers,
      statusCode: res.statusCode,
      durationMs: Date.now() - started,
    });

    console.log(JSON.stringify(payload));
  });

  next();
}
