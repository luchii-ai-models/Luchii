import { describe, test, expect } from "vitest";

import { buildErrorResponse } from "../error-response";
import { ErrorCode } from "../error-codes";

describe("error schema", () => {
  test("matches schema exactly", () => {
    const error = buildErrorResponse("req_123", ErrorCode.PERMISSION_DENIED, "Permission denied.");

    expect(error).toStrictEqual({
      success: false,
      requestId: "req_123",
      error: {
        code: "PERMISSION_DENIED",
        message: "Permission denied.",
      },
    });
  });
});
