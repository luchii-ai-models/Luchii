import { describe, test, expect } from "vitest";
import { buildErrorResponse } from "../error-response";
import { ErrorCode } from "../error-codes";

describe("error response invalid inputs", () => {
  test("handles undefined code", () => {
    const result = buildErrorResponse("req_123", undefined as any, "message");

    expect(result.error.code).toBe(ErrorCode.INTERNAL_ERROR);
  });

  test("handles null message", () => {
    const result = buildErrorResponse("req_123", ErrorCode.INTERNAL_ERROR, null as any);

    expect(result.error.message).toBe("Unexpected internal error.");
  });

  test("handles empty message", () => {
    const result = buildErrorResponse("req_123", ErrorCode.INTERNAL_ERROR, "");

    expect(result.error.message).toBe("Unexpected internal error.");
  });
});
