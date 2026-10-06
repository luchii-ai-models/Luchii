import request from "supertest";
import express from "express";
import { describe, test, expect, beforeEach, vi } from "vitest";

const mockRedis = vi.hoisted(() => ({
  store: new Map<string, number>(),

  async eval(_script: string, _numKeys: number, key: string) {
    const value = (this.store.get(key) || 0) + 1;
    this.store.set(key, value);
    return value;
  },

  reset() {
    this.store.clear();
  },
}));

vi.mock("../redis-client", () => ({
  redis: mockRedis,
}));

import { redisRateLimit } from "../redis-rate-limit";

describe("redisRateLimit", () => {
  beforeEach(() => {
    mockRedis.reset();
  });

  const app = express();

  app.use((req: any, _, next) => {
    req.ownerId = "owner_test";
    next();
  });

  app.get("/limited", redisRateLimit(2, 60), (_, res) => {
    res.json({ success: true });
  });

  test("allows requests under limit", async () => {
    expect((await request(app).get("/limited")).status).toBe(200);
    expect((await request(app).get("/limited")).status).toBe(200);
  });

  test("blocks requests above limit", async () => {
    await request(app).get("/limited");
    await request(app).get("/limited");

    const response = await request(app).get("/limited");

    expect(response.status).toBe(429);
    expect(response.body.error.code).toBe("RATE_LIMIT_EXCEEDED");
  });
});
