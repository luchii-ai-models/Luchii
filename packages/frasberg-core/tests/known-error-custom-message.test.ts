import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { FrasbergError, errorMiddleware } from "../error-middleware";
import { ErrorCode } from "../error-codes";

describe("custom known error messages", () => {
  const app = express();

  app.get("/quota", () => {
    throw new FrasbergError(429, ErrorCode.QUOTA_EXCEEDED, "Monthly quota exhausted.");
  });

  app.use(errorMiddleware);

  test("preserves known message", async () => {
    const response = await request(app).get("/quota");

    expect(response.status).toBe(429);
    expect(response.body.error.code).toBe("QUOTA_EXCEEDED");
    expect(response.body.error.message).toBe("Monthly quota exhausted.");
  });
});
