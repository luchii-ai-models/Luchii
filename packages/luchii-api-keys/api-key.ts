import { ErrorCode } from '../frasberg-core/error-codes';
import { buildErrorResponse } from '../frasberg-core/error-response';
import type { ErrorPayload } from '../frasberg-core/error-types';

export type ApiKeyStatus = 'active' | 'disabled' | 'suspended';

export interface ApiKey {
  id: string;
  ownerId: string;
  workspaceId: string;
  name: string;
  hash: string;
  status: ApiKeyStatus;
  permissions: string[];
  requestsToday: number;
  createdAt: number;
}

export const ERROR_CATALOG: Record<ErrorCode, { status: number; message: string }> = {
  KEY_NOT_PROVIDED: { status: 401, message: 'API key is required.' },
  KEY_NOT_FOUND: { status: 401, message: 'API key was not found.' },
  OWNER_NOT_FOUND: { status: 401, message: 'Owner not resolved.' },
  INVALID_OWNER_ID: { status: 400, message: 'Owner identifier format is invalid.' },
  INVALID_WORKSPACE_ID: { status: 400, message: 'Workspace identifier format is invalid.' },
  INVALID_REQUEST: { status: 400, message: 'Request body is invalid.' },
  PERMISSION_DENIED: { status: 403, message: 'Permission denied.' },
  KEY_DISABLED: { status: 403, message: 'API key is disabled.' },
  ACCOUNT_SUSPENDED: { status: 403, message: 'Account is suspended.' },
  MODEL_NOT_FOUND: { status: 404, message: 'Model was not found.' },
  WORKSPACE_NOT_FOUND: { status: 404, message: 'Workspace was not found.' },
  RATE_LIMIT_EXCEEDED: { status: 429, message: 'Rate limit exceeded.' },
  QUOTA_EXCEEDED: { status: 429, message: 'Quota exceeded.' },
  AUTH_FAILURE: { status: 500, message: 'Failed to validate API key.' },
  OWNER_RESOLUTION_FAILED: { status: 500, message: 'Failed to resolve owner.' },
  WORKSPACE_RESOLUTION_FAILED: { status: 500, message: 'Failed to resolve workspace.' },
  RATE_LIMIT_FAILURE: { status: 500, message: 'Rate limiter unavailable.' },
  INTERNAL_ERROR: { status: 500, message: 'Unexpected internal error.' },
  RATE_LIMIT_SERVICE_UNAVAILABLE: { status: 503, message: 'Rate limiting service unavailable.' },
  MODEL_UNAVAILABLE: { status: 503, message: 'Model is unavailable.' },
  RUNTIME_UNAVAILABLE: { status: 503, message: 'Runtime is unavailable.' },
  SERVICE_UNAVAILABLE: { status: 503, message: 'Service is unavailable.' },
} as const;

export type GatewayErrorCode = ErrorCode;

export type ErrorResponse = ErrorPayload;

export function gatewayErrorResponse(code: GatewayErrorCode | `${GatewayErrorCode}`, extra: { required?: string; requestId?: string } = {}): ErrorResponse {
  const { requestId, required } = extra;
  const normalizedCode = code as GatewayErrorCode;
  const payload = buildErrorResponse(requestId ?? 'unknown', normalizedCode, ERROR_CATALOG[normalizedCode].message);
  if (required) payload.error.required = required;
  return payload;
}

export class GatewayError extends Error {
  readonly status: number;
  readonly code: GatewayErrorCode;
  constructor(code: GatewayErrorCode | `${GatewayErrorCode}`, readonly extra: { required?: string } = {}) {
    const normalizedCode = code as GatewayErrorCode;
    super(normalizedCode);
    this.code = normalizedCode;
    this.status = ERROR_CATALOG[normalizedCode].status;
  }
  toBody(requestId?: string) {
    return gatewayErrorResponse(this.code, { ...this.extra, requestId });
  }
}
