import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { errorMiddleware } from "../error-middleware";
import { requestIdMiddleware } from "../request-id";
import { successResponse } from "../response";
import { GatewayError } from "../../luchii-api-keys/api-key";

describe("success response", () => {
  test("matches the standard success contract", () => {
    expect(successResponse("req_123", { ok: true })).toStrictEqual({
      success: true,
      requestId: "req_123",
      data: { ok: true },
    });
  });
});

describe("gateway errors through the error middleware", () => {
  const app = express();

  app.use(requestIdMiddleware);
  app.get("/denied", () => {
    throw new GatewayError("PERMISSION_DENIED", { required: "music.generate" });
  });
  app.use(errorMiddleware);

  test("keeps status, code and required permission", async () => {
    const response = await request(app).get("/denied");

    expect(response.status).toBe(403);
    expect(response.body.error).toMatchObject({ code: "PERMISSION_DENIED", required: "music.generate" });
    expect(response.body.requestId).toBe(response.headers["x-request-id"]);
  });
});
