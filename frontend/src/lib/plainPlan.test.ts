import { describe, expect, it } from "vitest";
import { planSummary, planTitle, riskSummary, statusDetail, statusHeadline, stepIndex, type PlanLike } from "./plainPlan";

const plan = (over: Partial<PlanLike> = {}): PlanLike => ({
  id: "PLAN_B", name: "x", strategy_type: "COST_OPTIMAL", total_mitigation_cost_inr: 100000, expected_cost_inr: 1,
  confidence_pct: 87.4, overtime_hours: 0, vendor_allocations: [], feasible: true, uncovered_units: 0, ...over,
});

describe("status card", () => {
  it("is all good with no risky orders", () => {
    const r = riskSummary([{ order_id: "1", status: "ON_TRACK", sla_penalty_inr: 5 }, { order_id: "2", status: "SLA_PROTECTED", sla_penalty_inr: 9 }]);
    expect(statusHeadline(r)).toBe("All good");
  });
  it("counts at-risk orders and their penalty", () => {
    const r = riskSummary([{ order_id: "1", status: "AT_RISK", sla_penalty_inr: 2500000 }]);
    expect(statusHeadline(r)).toBe("1 order at risk");
    expect(statusDetail(r)).toBe("₹25,00,000 penalty if it ships late.");
  });
});

describe("plan wording", () => {
  it("summarises suppliers and overtime in one sentence", () => {
    const s = planSummary(plan({
      vendor_allocations: [{ supplier_name: "Chennai Metals (backup)", units_allocated: 1200 }],
      overtime_hours: 4, overtime_line_hours: { "Line B": 4 },
    }));
    expect(s).toBe("Buy 1,200 units from Chennai Metals and run overtime (Line B 4 h).");
  });
  it("describes asking the customer", () => {
    expect(planSummary(plan({ strategy_type: "SLA_RENEGOTIATION" }))).toMatch(/more time/);
  });
  it("uses plain titles", () => {
    expect(planTitle(plan({ strategy_type: "AIR_CHARTER_MAX_OT" }), 0)).toBe("Fastest plan");
    expect(stepIndex("approve")).toBe(3);
  });
});
