import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { FrasbergError, errorMiddleware } from "../error-middleware";
import { ErrorCode } from "../error-codes";

describe("known error custom messages", () => {
  const app = express();

  app.get("/custom", () => {
    throw new FrasbergError(429, ErrorCode.QUOTA_EXCEEDED, "Workspace token quota exceeded.");
  });

  app.use(errorMiddleware);

  test("preserves custom known message", async () => {
    const response = await request(app).get("/custom");

    expect(response.status).toBe(429);
    expect(response.body.error.message).toBe("Workspace token quota exceeded.");
  });
});
