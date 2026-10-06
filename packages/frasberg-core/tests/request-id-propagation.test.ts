import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { requestIdMiddleware } from "../request-id";

describe("request id propagation", () => {
  const app = express();

  app.use(requestIdMiddleware);

  app.get("/trace", (req: any, res) => {
    res.json({ requestId: req.requestId });
  });

  test("propagates generated id", async () => {
    const response = await request(app).get("/trace");

    expect(response.headers["x-request-id"]).toBeDefined();
    expect(response.body.requestId).toBe(response.headers["x-request-id"]);
  });

  test("uses caller id", async () => {
    const response = await request(app).get("/trace").set("x-request-id", "req_external_123");

    expect(response.body.requestId).toBe("req_external_123");
    expect(response.headers["x-request-id"]).toBe("req_external_123");
  });
});
