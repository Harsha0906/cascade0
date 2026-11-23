import { describe, expect, it } from "vitest";
import { formatHours, formatInr, formatInrShort, groupIndian, plural, roleLabel } from "./format";

describe("Indian number format", () => {
  it("groups in lakhs and crores", () => {
    expect(groupIndian(999)).toBe("999");
    expect(groupIndian(1000)).toBe("1,000");
    expect(groupIndian(2500000)).toBe("25,00,000");
    expect(groupIndian(123456789)).toBe("12,34,56,789");
  });
  it("formats rupees and negatives", () => {
    expect(formatInr(2500000)).toBe("₹25,00,000");
    expect(formatInr(-4500)).toBe("-₹4,500");
    expect(formatInr(null)).toBe("—");
  });
  it("shortens big amounts", () => {
    expect(formatInrShort(2500000)).toBe("₹25 lakh");
    expect(formatInrShort(12000000)).toBe("₹1.2 crore");
    expect(formatInrShort(45000)).toBe("₹45,000");
  });
  it("plural and hours", () => {
    expect(plural(1, "order")).toBe("1 order");
    expect(plural(1200, "unit")).toBe("1,200 units");
    expect(formatHours(5)).toBe("in 5 h");
    expect(formatHours(72)).toBe("in 3 days");
    expect(formatHours(-2)).toBe("2 h overdue");
  });
  it("names roles plainly", () => {
    expect(roleLabel("EXPEDITE")).toBe("Express");
  });
});
