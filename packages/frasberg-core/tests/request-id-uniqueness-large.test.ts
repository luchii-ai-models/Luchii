import { describe, test, expect } from "vitest";
import { generateRequestId } from "../request-id";

describe("request id uniqueness at scale", () => {
  test("10000 generated ids are unique", () => {
    const ids = new Set<string>();

    for (let i = 0; i < 10000; i++) {
      ids.add(generateRequestId());
    }

    expect(ids.size).toBe(10000);
  });
});
