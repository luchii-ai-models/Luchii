import { describe, test, expect } from "vitest";
import { buildErrorResponse } from "../error-response";

describe("invalid error code types", () => {
  test.each([
    ["undefined", undefined],
    ["empty", ""],
    ["null", null],
    ["number", 42],
    ["object", {}],
  ])("falls back to INTERNAL_ERROR for %s code", (_name, code) => {
    const result = buildErrorResponse("req_123", code as any, "Message");

    expect(result.error.code).toBe("INTERNAL_ERROR");
  });
});
