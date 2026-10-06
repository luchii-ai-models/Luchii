import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { FrasbergError, errorMiddleware } from "../error-middleware";
import { ErrorCode } from "../error-codes";
import { requestIdMiddleware } from "../request-id";

describe("typed error middleware", () => {
  const app = express();
  app.use(requestIdMiddleware);

  app.get("/test", () => {
    throw new FrasbergError(403, ErrorCode.PERMISSION_DENIED, "Permission denied.");
  });

  app.get("/boom", () => {
    throw new Error("db password leaked here");
  });

  app.use(errorMiddleware);

  test("returns typed error", async () => {
    const response = await request(app).get("/test");

    expect(response.status).toBe(403);
    expect(response.body.error.code).toBe("PERMISSION_DENIED");
    expect(response.body.requestId).toBe(response.headers["x-request-id"]);
  });

  test("propagates caller request IDs into error responses", async () => {
    const response = await request(app).get("/test").set("x-request-id", "req_external_999");

    expect(response.body.requestId).toBe("req_external_999");
    expect(response.headers["x-request-id"]).toBe("req_external_999");
  });

  test("hides internals of unexpected errors", async () => {
    const response = await request(app).get("/boom");

    expect(response.status).toBe(500);
    expect(response.body.error.code).toBe("INTERNAL_ERROR");
    expect(JSON.stringify(response.body)).not.toContain("password");
    expect(response.body.error.message).toBe("Unexpected internal error.");
    expect(response.body.requestId).toBe(response.headers["x-request-id"]);
  });
});
