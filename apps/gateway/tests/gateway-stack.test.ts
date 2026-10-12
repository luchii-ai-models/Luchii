import request from "supertest";
import express from "express";
import { vi, describe, test, expect, beforeEach } from "vitest";

const redis = vi.hoisted(() => ({
  count: 0,
  fail: false,
  async eval() {
    if (this.fail) throw new Error("redis offline");
    return ++this.count;
  },
}));

vi.mock("../../../packages/luchii-rate-limiter/redis-client", () => ({ redis }));

import { applyGatewayStack } from "../src/middleware-stack";
import { createRuntimeClient } from "../src/runtime-client";
import { generateApiKey } from "../../../packages/luchii-api-keys/generate-key";
import { InMemoryApiKeyStore, setApiKeyStore } from "../../../packages/luchii-api-keys/api-key-store";

describe("gateway stack", () => {
  const app = express();
  const store = new InMemoryApiKeyStore();
  const { raw, hash } = generateApiKey();
  const { raw: suspendedRaw, hash: suspendedHash } = generateApiKey();

  const base = { ownerId: "owner_123", workspaceId: "ws_primary", requestsToday: 0, createdAt: 0 };
  const runtime = vi.fn(async () => ({ audioUrl: "https://example.test/a.mp3" }));

  beforeEach(() => {
    redis.count = 0;
    redis.fail = false;
  });

  setApiKeyStore(store);
  void store.save({ ...base, id: "k1", name: "music", hash, status: "active", permissions: ["music.generate"] });
  void store.save({ ...base, id: "k2", name: "sus", hash: suspendedHash, status: "suspended", permissions: ["*"] });

  applyGatewayStack(app, runtime);

  const call = (path: string, key?: string) => {
    const r = request(app).post(path).send({ input: "write a song" });
    return key ? r.set("x-api-key", key) : r;
  };

  test("401 KEY_NOT_PROVIDED without a key, with request id", async () => {
    const res = await call("/v1/music/generate");

    expect(res.status).toBe(401);
    expect(res.body.error.code).toBe("KEY_NOT_PROVIDED");
    expect(res.body.requestId).toBe(res.headers["x-request-id"]);
  });

  test("401 KEY_NOT_FOUND for an unknown key", async () => {
    const res = await call("/v1/music/generate", "luc_live_unknown");

    expect(res.status).toBe(401);
    expect(res.body.error.code).toBe("KEY_NOT_FOUND");
  });

  test("403 ACCOUNT_SUSPENDED", async () => {
    const res = await call("/v1/music/generate", suspendedRaw);

    expect(res.status).toBe(403);
    expect(res.body.error.code).toBe("ACCOUNT_SUSPENDED");
  });

  test("403 PERMISSION_DENIED names the required permission", async () => {
    const res = await call("/v1/chat", raw);

    expect(res.status).toBe(403);
    expect(res.body.error).toMatchObject({ code: "PERMISSION_DENIED", required: "chat.generate" });
  });

  test("403 for unmapped routes", async () => {
    const res = await call("/v1/unknown", raw);

    expect(res.status).toBe(403);
  });

  test("200 routes to a model and returns the runtime result", async () => {
    const res = await call("/v1/music/generate", raw);

    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({
      success: true,
      data: { model: "luchii-music", result: { audioUrl: "https://example.test/a.mp3" } },
    });
    expect(runtime).toHaveBeenCalledWith(expect.objectContaining({ path: "/v1/music/generate", model: "luchii-music" }));
  });

  test("503 RUNTIME_UNAVAILABLE when no upstream is configured", async () => {
    const bare = express();
    applyGatewayStack(bare, createRuntimeClient({}));

    const res = await request(bare).post("/v1/music/generate").set("x-api-key", raw).send({ input: "a song" });

    expect(res.status).toBe(503);
    expect(res.body.error.code).toBe("RUNTIME_UNAVAILABLE");
  });

  test("429 RATE_LIMIT_EXCEEDED", async () => {
    redis.count = 1000;
    const res = await call("/v1/music/generate", raw);

    expect(res.status).toBe(429);
    expect(res.body.error.code).toBe("RATE_LIMIT_EXCEEDED");
  });

  test("public API fails open during Redis outage", async () => {
    redis.fail = true;
    const res = await call("/v1/music/generate", raw);

    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test("admin and checkout paths fail closed during Redis outage", async () => {
    redis.fail = true;
    const admin = await call("/api/admin/metrics", raw);

    expect(admin.status).toBe(503);
    expect(admin.body.error.code).toBe("RATE_LIMIT_SERVICE_UNAVAILABLE");
    expect(admin.body.requestId).toBe(admin.headers["x-request-id"]);

    const checkout = await call("/checkout/session", raw);

    expect(checkout.status).toBe(503);
    expect(checkout.body.error.code).toBe("RATE_LIMIT_SERVICE_UNAVAILABLE");
  });
});
