import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { requestIdMiddleware } from "../../frasberg-core/request-id";
import { ownerResolver } from "../owner-resolver";

describe("error request id", () => {
  const app = express();

  app.use(requestIdMiddleware);
  app.get("/owner", ownerResolver);

  test("returns request id on error", async () => {
    const response = await request(app).get("/owner");

    expect(response.status).toBe(401);
    expect(response.body.success).toBe(false);
    expect(response.body.requestId).toBeDefined();
    expect(response.body.error.code).toBe("OWNER_NOT_FOUND");
  });
});
