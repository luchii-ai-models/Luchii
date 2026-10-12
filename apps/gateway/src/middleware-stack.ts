import type { Express } from 'express';
import { json } from 'express';
import { requestIdMiddleware } from '@frasberg-core/request-id';
import { errorMiddleware } from '@frasberg-core/error-middleware';
import { apiKeyMiddleware } from '@luchii-api-keys/api-key-middleware';
import { permissionMiddleware } from '@luchii-api-keys/permission-middleware';
import { ownerResolver } from '@frasberg-identity/owner-resolver';
import { workspaceResolver } from '@frasberg-identity/workspace-resolver';
import { redisRateLimit } from '@luchii-rate-limiter/redis-rate-limit';
import { createLuchiiRouter } from './luchii-router';
import { requestLogger } from './request-logger';
import type { RuntimeClient } from './runtime-client';
import { buildErrorResponse } from '@frasberg-core/error-response';
import { ErrorCode } from '@frasberg-core/error-codes';

export function applyGatewayStack(app: Express, runtime?: RuntimeClient) {
  app.use(requestIdMiddleware);
  app.use(requestLogger);
  app.use(json({ limit: '1mb' }));
  app.use(apiKeyMiddleware);
  app.use(ownerResolver);
  app.use(workspaceResolver);
  app.use(redisRateLimit(1000, 60, {
    failClosed: (req) => /^\/(?:api\/)?(?:admin|checkout)(?:\/|$)/i.test(req.path),
  }));
  app.use(permissionMiddleware);
  app.use(createLuchiiRouter(runtime));
  app.use((req, res) => {
    res.status(404).json(buildErrorResponse(req.requestId ?? 'unknown', ErrorCode.MODEL_NOT_FOUND, 'Route was not found.'));
  });
  app.use(errorMiddleware);
}
