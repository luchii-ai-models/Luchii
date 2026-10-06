import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { requestIdMiddleware } from "../request-id";

describe("request id length limits", () => {
  const app = express();

  app.use(requestIdMiddleware);

  app.get("/ping", (req: any, res) => {
    res.json({ requestId: req.requestId });
  });

  test("rejects oversized request id", async () => {
    const oversized = "req_" + "x".repeat(500);
    const response = await request(app).get("/ping").set("x-request-id", oversized);

    expect(response.body.requestId).not.toBe(oversized);
    expect(response.body.requestId).toMatch(/^req_/);
    expect(response.body.requestId.length).toBeLessThanOrEqual(132);
  });

  test("accepts valid request id", async () => {
    const response = await request(app).get("/ping").set("x-request-id", "req_valid12345");

    expect(response.body.requestId).toBe("req_valid12345");
  });

  test("generated ids are req_ plus 32 hex characters", async () => {
    const response = await request(app).get("/ping");

    expect(response.body.requestId).toMatch(/^req_[0-9a-f]{32}$/);
  });
});
