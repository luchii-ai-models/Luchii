import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { requestIdMiddleware } from "../request-id";

describe("malformed request ids", () => {
  const app = express();

  app.use(requestIdMiddleware);

  app.get("/test", (req: any, res) => {
    res.json({ requestId: req.requestId });
  });

  const malformed = [
    ["path traversal", "../../../etc/passwd"],
    ["markup", "<script>"],
    ["oversized", "req_" + "A".repeat(200)],
    ["missing prefix", "external_123456"],
    ["too short", "req_abc"],
    ["whitespace", "req_has space_123"],
  ];

  test.each(malformed)("replaces %s", async (_name, value) => {
    const response = await request(app).get("/test").set("x-request-id", value);

    expect(response.body.requestId).not.toBe(value);
    expect(response.body.requestId).toMatch(/^req_[a-zA-Z0-9_-]{8,128}$/);
    expect(response.headers["x-request-id"]).toBe(response.body.requestId);
  });

  test("keeps a well-formed id", async () => {
    const response = await request(app).get("/test").set("x-request-id", "req_external_123");

    expect(response.body.requestId).toBe("req_external_123");
  });
});
