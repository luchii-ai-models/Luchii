import { describe, test, expect } from "vitest";
import { generateRequestId } from "../request-id";

describe("request id uniqueness", () => {
  test("generates unique ids", () => {
    const ids = new Set<string>();

    for (let i = 0; i < 5000; i++) {
      ids.add(generateRequestId());
    }

    expect(ids.size).toBe(5000);
  });

  test("ids use the fixed req_ + 32 hex format", () => {
    expect(generateRequestId()).toMatch(/^req_[0-9a-f]{32}$/);
  });
});
