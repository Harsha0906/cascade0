import { describe, expect, it } from "vitest";
import { hasErrors, isEmail, parseNum, slugify, validateFactory, validateLine, validateMember, validateOrder, validateSupplier } from "./forms";

describe("parsing", () => {
  it("parses Indian-formatted numbers", () => {
    expect(parseNum("25,00,000")).toBe(2500000);
    expect(parseNum("₹ 1,200")).toBe(1200);
    expect(parseNum("")).toBeNull();
    expect(parseNum("abc")).toBeNull();
  });
  it("slugifies names", () => {
    expect(slugify("Apex Volt (Blr-2)")).toBe("apex-volt-blr-2");
  });
  it("checks emails", () => {
    expect(isEmail("a@b.co")).toBe(true);
    expect(isEmail("a@b")).toBe(false);
  });
});

describe("validators", () => {
  it("factory needs the basics", () => {
    const e = validateFactory({ name: "", stock_item_code: "bad code", stock_item_name: "Pack", qa_dispatch_hours: "-1", safety_stock_units: "0.5", production_hours_in_window: "0" });
    expect(Object.keys(e).sort()).toEqual(["name", "production_hours_in_window", "qa_dispatch_hours", "safety_stock_units", "stock_item_code"]);
    expect(hasErrors(validateFactory({ name: "A", stock_item_code: "X1", stock_item_name: "Pack", qa_dispatch_hours: "4", safety_stock_units: "0", production_hours_in_window: "48" }))).toBe(false);
  });
  it("line allows blank overtime", () => {
    expect(hasErrors(validateLine({ name: "Line A", rated_units_per_hour: "40" }))).toBe(false);
    expect(validateLine({ name: "", rated_units_per_hour: "" })).toHaveProperty("rated_units_per_hour");
  });
  it("supplier history must be paired and consistent", () => {
    const base = { name: "S", route: "Chennai", sourcing_role: "BACKUP", risk_profile: "low", max_units: "100", lead_hours: "24" };
    expect(hasErrors(validateSupplier(base))).toBe(false);
    expect(validateSupplier({ ...base, past_orders: "10" })).toHaveProperty("on_time");
    expect(validateSupplier({ ...base, past_orders: "10", on_time: "11" }).on_time).toMatch(/can't be more/);
    expect(validateSupplier({ ...base, min_lead_hours: "30" })).toHaveProperty("min_lead_hours");
    expect(validateSupplier({ ...base, risk_profile: "" })).toHaveProperty("risk_profile");
  });
  it("order needs customer, quantity, deadline and penalty", () => {
    expect(Object.keys(validateOrder({})).sort()).toEqual(["client", "hours_remaining", "required_qty", "sla_penalty_inr"]);
  });
  it("member needs email and role", () => {
    expect(Object.keys(validateMember({ email: "x" })).sort()).toEqual(["email", "role"]);
  });
});
