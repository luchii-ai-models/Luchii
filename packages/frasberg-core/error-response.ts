import { ErrorCode } from './error-codes';
import type { ErrorPayload } from './error-types';

const FALLBACK_MESSAGE = 'Unexpected internal error.';

// Bad inputs from untyped callers fall back to a generic internal error instead of an incomplete payload.
export function buildErrorResponse(
  requestId: string,
  code?: ErrorCode | null,
  message?: string | null,
  details?: unknown,
): ErrorPayload {
  return {
    success: false,
    requestId,
    error: {
      code: typeof code === 'string' && code.trim().length > 0 ? code : ErrorCode.INTERNAL_ERROR,
      message: typeof message === 'string' && message.trim().length > 0 ? message : FALLBACK_MESSAGE,
      ...(details !== undefined ? { details } : {}),
    },
  };
}
