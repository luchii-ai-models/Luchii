import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { FrasbergError, errorMiddleware } from "../error-middleware";
import { ErrorCode } from "../error-codes";

describe("known error message preservation", () => {
  const app = express();

  app.get("/invalid", () => {
    throw new FrasbergError(400, ErrorCode.INVALID_REQUEST, "Field 'name' is required.", { field: "name" });
  });

  app.use(errorMiddleware);

  test("preserves message and details for known errors", async () => {
    const response = await request(app).get("/invalid");

    expect(response.status).toBe(400);
    expect(response.body.error.message).toBe("Field 'name' is required.");
    expect(response.body.error.details).toEqual({ field: "name" });
  });
});
