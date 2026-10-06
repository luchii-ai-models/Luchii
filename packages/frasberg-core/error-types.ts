import type { ErrorCode } from './error-codes';

export interface ErrorPayload {
  success: false;
  requestId: string;
  error: {
    code: ErrorCode;
    message: string;
    details?: unknown;
    required?: string;
  };
}
