import { describe, test, expect } from "vitest";
import { ErrorCode } from "../error-codes";

describe("error code edge cases", () => {
  test("all codes are unique", () => {
    const values = Object.values(ErrorCode);

    expect(new Set(values).size).toBe(values.length);
  });

  test("codes are uppercase", () => {
    for (const value of Object.values(ErrorCode)) {
      expect(value).toBe(value.toUpperCase());
    }
  });

  test("no empty values", () => {
    for (const value of Object.values(ErrorCode)) {
      expect(value.length).toBeGreaterThan(0);
    }
  });
});
