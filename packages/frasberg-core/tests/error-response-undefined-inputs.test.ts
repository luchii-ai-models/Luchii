import { describe, test, expect } from "vitest";
import { buildErrorResponse } from "../error-response";
import { ErrorCode } from "../error-codes";

describe("undefined error inputs", () => {
  test("handles undefined details", () => {
    const result = buildErrorResponse("req_123", ErrorCode.INTERNAL_ERROR, "Message", undefined);

    expect(result.error).not.toHaveProperty("details");
  });

  test("keeps falsy but defined details", () => {
    expect(buildErrorResponse("req_123", ErrorCode.INTERNAL_ERROR, "Message", 0).error.details).toBe(0);
    expect(buildErrorResponse("req_123", ErrorCode.INTERNAL_ERROR, "Message", null).error.details).toBeNull();
  });
});
