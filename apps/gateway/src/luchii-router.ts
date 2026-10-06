import { NextFunction, Request, Response, Router } from 'express';
import { successResponse } from '../../../packages/frasberg-core/response';
import { LuchiiModelRouter } from '../../../packages/luchii-model-router';
import { createRuntimeClient, type RuntimeClient } from './runtime-client';

const modelRouter = new LuchiiModelRouter();

export function createLuchiiRouter(runtime: RuntimeClient = createRuntimeClient()) {
  const router = Router();

  router.post('/v1/*', async (req: Request, res: Response, next: NextFunction) => {
    try {
      const body = req.body ?? {};
      const input = typeof body.input === 'string' ? body.input : '';
      const model = modelRouter.route(input);
      const requestId = req.requestId ?? '';

      const result = await runtime({ model, path: req.path, body, requestId });
      res.json(successResponse(requestId, { model, result }));
    } catch (err) {
      next(err);
    }
  });

  return router;
}
