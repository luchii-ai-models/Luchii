import { describe, test, expect } from "vitest";
import { ErrorCode } from "../error-codes";
import { ERROR_CATALOG } from "../../luchii-api-keys/api-key";

describe("error code integrity", () => {
  test("every key equals its value", () => {
    for (const [key, value] of Object.entries(ErrorCode)) {
      expect(value).toBe(key);
    }
  });

  test("every code has a status and message in the catalog", () => {
    for (const code of Object.values(ErrorCode)) {
      expect(ERROR_CATALOG[code]).toBeDefined();
      expect(ERROR_CATALOG[code].message.length).toBeGreaterThan(0);
      expect(ERROR_CATALOG[code].status).toBeGreaterThanOrEqual(400);
    }
  });
});
