import request from "supertest";
import express from "express";
import { vi, describe, test, expect } from "vitest";

vi.mock("../redis-client", () => ({
  redis: {
    eval: vi.fn().mockRejectedValue(new Error("redis offline")),
  },
}));

import { redisRateLimit } from "../redis-rate-limit";

describe("redis fallback", () => {
  const app = express();

  app.use((req: any, _, next) => {
    req.ownerId = "owner_1";
    next();
  });

  app.get("/test", redisRateLimit(), (_, res) => {
    res.json({ success: true });
  });

  test("continues processing when redis fails", async () => {
    const response = await request(app).get("/test");

    expect(response.status).toBe(200);
  });
});
