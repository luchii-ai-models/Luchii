import { describe, expect, test } from "vitest";
import { buildErrorResponse } from "../error-response";

describe("error response", () => {
  test("omits undefined details", () => {
    const result = buildErrorResponse("req_123", "TEST_ERROR", "Test message");

    expect(result.error).not.toHaveProperty("details");
  });

  test("includes details when present", () => {
    const result = buildErrorResponse("req_123", "TEST_ERROR", "Test message", { model: "luchii-core" });

    expect(result.error.details).toEqual({ model: "luchii-core" });
  });
});
