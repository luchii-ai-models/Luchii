import { describe, test, expect } from "vitest";
import { buildErrorResponse } from "../error-response";
import { ErrorCode } from "../error-codes";

describe("error response required fields", () => {
  const build = () => buildErrorResponse("req_123", ErrorCode.INTERNAL_ERROR, "Test message");

  test("always includes success", () => {
    expect(build().success).toBe(false);
  });

  test("always includes request id", () => {
    expect(build().requestId).toBe("req_123");
  });

  test("always includes code", () => {
    expect(build().error.code).toBe("INTERNAL_ERROR");
  });

  test("always includes message", () => {
    expect(build().error.message).toBe("Test message");
  });
});
