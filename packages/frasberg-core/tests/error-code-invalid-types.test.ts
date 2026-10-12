import { describe, test, expect } from "vitest";
import { buildErrorResponse } from "../error-response";

describe("fallback error codes", () => {
  test.each([
    ["undefined", undefined],
    ["null", null],
    ["number", 42],
    ["boolean", true],
    ["array", ["PERMISSION_DENIED"]],
    ["empty string", ""],
    ["whitespace string", "   "],
  ])("%s code falls back", (_name, code) => {
    const result = buildErrorResponse("req_123", code as any, "Message");

    expect(result.error.code).toBe("INTERNAL_ERROR");
  });

  test("non-string message falls back", () => {
    const result = buildErrorResponse("req_123", "PERMISSION_DENIED" as any, { text: "x" } as any);

    expect(result.error.message).toBe("Unexpected internal error.");
  });
});
