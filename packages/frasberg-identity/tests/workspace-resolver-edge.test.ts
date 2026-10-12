import request from "supertest";
import express from "express";
import { describe, test, expect } from "vitest";

import { workspaceResolver } from "../workspace-resolver";

describe("workspace resolver edge cases", () => {
  const app = express();

  app.get("/workspace", workspaceResolver, (req: any, res) => {
    res.json({ workspaceId: req.workspaceId });
  });

  test("accepts valid workspace", async () => {
    const response = await request(app).get("/workspace").set("x-workspace-id", "ws_production");

    expect(response.status).toBe(200);
  });

  test("trims whitespace", async () => {
    const response = await request(app).get("/workspace").set("x-workspace-id", " ws_primary ");

    expect(response.status).toBe(200);
    expect(response.body.workspaceId).toBe("ws_primary");
  });

  test("rejects empty string", async () => {
    const response = await request(app).get("/workspace").set("x-workspace-id", " ");

    expect(response.status).toBe(400);
  });

  test("rejects encoded attack payload", async () => {
    const response = await request(app).get("/workspace").set("x-workspace-id", "ws_%3Cscript%3E");

    expect(response.status).toBe(400);
    expect(response.body.error.code).toBe("INVALID_WORKSPACE_ID");
  });
});
