import { describe, test, expect, vi } from "vitest";

import { requestLogger } from "../../../apps/gateway/src/request-logger";

describe("logger redaction", () => {
  test("does not log secret values", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});

    const req: any = {
      requestId: "req_123",
      ownerId: "owner_1",
      workspaceId: "ws_prod",
      path: "/v1/chat",
      method: "POST",
      headers: {
        "x-api-key": "luc_live_secret",
        authorization: "Bearer luc_live_secret",
        cookie: "session=abc",
        "content-type": "application/json",
      },
    };

    const res: any = {
      statusCode: 200,
      on: (event: string, callback: () => void) => {
        if (event === "finish") callback();
      },
    };

    requestLogger(req, res, () => {});

    const logOutput = JSON.stringify(spy.mock.calls);

    expect(logOutput).not.toContain("luc_live_secret");
    expect(logOutput).not.toContain("Bearer ");
    expect(logOutput).not.toContain("session=abc");
    expect(logOutput).toContain("[REDACTED]");
    expect(logOutput).toContain("req_123");

    spy.mockRestore();
  });
});
