import { describe, test, expect } from "vitest";
import { buildErrorResponse } from "../error-response";
import { ErrorCode } from "../error-codes";

describe("fallback error messages", () => {
  test.each([
    ["undefined", undefined],
    ["empty", ""],
    ["whitespace", "   "],
  ])("uses fallback when message is %s", (_name, message) => {
    const result = buildErrorResponse("req_123", ErrorCode.INTERNAL_ERROR, message as any);

    expect(result.error.message).toBe("Unexpected internal error.");
  });

  test("keeps a real message", () => {
    expect(buildErrorResponse("req_123", ErrorCode.PERMISSION_DENIED, "Nope.").error.message).toBe("Nope.");
  });
});
