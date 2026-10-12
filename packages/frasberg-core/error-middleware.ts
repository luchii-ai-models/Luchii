import type { NextFunction, Request, Response } from 'express';
import { GatewayError } from '../luchii-api-keys/api-key';
import { ErrorCode } from './error-codes';
import { buildErrorResponse } from './error-response';

export class FrasbergError extends Error {
  constructor(
    public status: number,
    public code: ErrorCode,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

// Express recognises error middleware by its 4-argument signature.
export function errorMiddleware(error: unknown, req: Request, res: Response, _next: NextFunction) {
  const requestId = req.requestId ?? 'unknown';

  if (error instanceof FrasbergError) {
    return res.status(error.status).json(buildErrorResponse(requestId, error.code, error.message, error.details));
  }
  if (error instanceof GatewayError) {
    return res.status(error.status).json(error.toBody(requestId));
  }
  if (error instanceof SyntaxError && 'status' in error && error.status === 400) {
    return res.status(400).json(buildErrorResponse(requestId, ErrorCode.INVALID_REQUEST, 'Request body is invalid.'));
  }
  return res.status(500).json(buildErrorResponse(requestId, ErrorCode.INTERNAL_ERROR, 'Unexpected internal error.'));
}
