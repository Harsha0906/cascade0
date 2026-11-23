import { describe, expect, it } from "vitest";
import { errorText } from "./api";

describe("errorText", () => {
  it("passes a string detail through verbatim", () => {
    expect(errorText(409, { detail: "Factory id 'x' is taken; choose another" })).toBe("Factory id 'x' is taken; choose another");
  });
  it("flattens FastAPI validation lists", () => {
    expect(errorText(422, { detail: [{ loc: ["body", "name"], msg: "Field required" }] })).toBe("name: Field required");
  });
  it("falls back to the status", () => {
    expect(errorText(500, null)).toBe("Request failed (HTTP 500)");
  });
});
