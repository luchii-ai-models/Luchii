import { describe, expect, test } from 'vitest';
import { ErrorCode } from '../error-codes';

describe('ErrorCode enum', () => {
  test('contains stable authentication codes', () => {
    expect(ErrorCode.KEY_NOT_FOUND).toBe('KEY_NOT_FOUND');
    expect(ErrorCode.KEY_NOT_PROVIDED).toBe('KEY_NOT_PROVIDED');
    expect(ErrorCode.KEY_DISABLED).toBe('KEY_DISABLED');
  });

  test('contains stable permission and internal codes', () => {
    expect(ErrorCode.PERMISSION_DENIED).toBe('PERMISSION_DENIED');
    expect(ErrorCode.ACCOUNT_SUSPENDED).toBe('ACCOUNT_SUSPENDED');
    expect(ErrorCode.INTERNAL_ERROR).toBe('INTERNAL_ERROR');
  });

  test('keeps the complete public error catalog stable', () => {
    expect(Object.values(ErrorCode)).toEqual(expect.arrayContaining([
      'KEY_NOT_FOUND', 'KEY_NOT_PROVIDED', 'KEY_DISABLED',
      'OWNER_NOT_FOUND', 'INVALID_OWNER_ID', 'WORKSPACE_NOT_FOUND', 'INVALID_WORKSPACE_ID',
      'PERMISSION_DENIED', 'ACCOUNT_SUSPENDED', 'RATE_LIMIT_EXCEEDED', 'QUOTA_EXCEEDED',
      'RATE_LIMIT_FAILURE', 'RATE_LIMIT_SERVICE_UNAVAILABLE', 'MODEL_NOT_FOUND',
      'MODEL_UNAVAILABLE', 'RUNTIME_UNAVAILABLE', 'SERVICE_UNAVAILABLE', 'INTERNAL_ERROR',
      'AUTH_FAILURE',
    ]));
  });
});