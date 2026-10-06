import request from "supertest";
import express from "express";
import { vi, describe, test, expect } from "vitest";
import { requestIdMiddleware } from "../../frasberg-core/request-id";

vi.mock("../redis-client", () => ({
  redis: {
    eval: vi.fn(() => new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 10))),
  },
}));

import { redisRateLimit } from "../redis-rate-limit";

describe("fail closed admin route", () => {
  const app = express();
  app.use(requestIdMiddleware);

  app.use((req: any, _, next) => {
    req.ownerId = "owner_admin";
    next();
  });

  app.get("/admin", redisRateLimit(1000, 60, { failClosed: true }), (_, res) => {
    res.json({ success: true });
  });

  test("returns 503 when redis is unavailable or times out", async () => {
    const response = await request(app).get("/admin");

    expect(response.status).toBe(503);
    expect(response.body.error.code).toBe("RATE_LIMIT_SERVICE_UNAVAILABLE");
    expect(response.body.requestId).toBe(response.headers["x-request-id"]);
  });
});
