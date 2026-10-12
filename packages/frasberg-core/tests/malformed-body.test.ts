import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { errorMiddleware } from "../error-middleware";
import { requestIdMiddleware } from "../request-id";

describe("malformed request bodies", () => {
  const app = express();

  app.use(requestIdMiddleware);
  app.use(express.json());
  app.post("/echo", (req, res) => res.json(req.body));
  app.use(errorMiddleware);

  test("invalid JSON becomes a 400 INVALID_REQUEST with a request id", async () => {
    const response = await request(app).post("/echo").set("content-type", "application/json").send("{ not json");

    expect(response.status).toBe(400);
    expect(response.body.success).toBe(false);
    expect(response.body.error.code).toBe("INVALID_REQUEST");
    expect(response.body.requestId).toBe(response.headers["x-request-id"]);
    expect(JSON.stringify(response.body)).not.toContain("not json");
  });
});
