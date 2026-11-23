import { describe, expect, it } from "vitest";
import { rootRunId, runViewState } from "./runHydration";

const response = {
  run_id: "RUN-1-S1",
  root_run_id: "RUN-1",
  executed: false,
  playbooks: [{ id: "PLAN_A" }, { id: "PLAN_B" }],
  recommended_plan_id: "PLAN_B",
  rebuttal_occurred: true,
  rebuttal_notes: ["note"],
  ai_mode: { overall: "fallback" },
  extracted_parameters: {
    affected_order_id: "EV-402",
    shortfall_units: 150,
    shortfall_source: "inventory" as const,
    shortfall_breakdown: { explanation: "x" },
    alert_stated_shortfall: 150,
  },
  solver_result: {
    solve_duration_ms: 12,
    lp_status: "Optimal",
    ranking_rule: "r",
    deadline_hours: 38,
    capacity_exhausted: false,
    throughput_gap_units: 0,
  },
};

describe("runViewState", () => {
  it("restores the plans, the selection and the run id", () => {
    const s = runViewState(response);
    expect(s.activeRunId).toBe("RUN-1-S1");
    expect(s.playbooks).toHaveLength(2);
    expect(s.selectedPlaybookId).toBe("PLAN_B");
    expect(s.activeOrderId).toBe("EV-402");
    expect(s.statusMode).toBe("CRISIS");
    expect(s.shortfallInfo).toEqual({
      shortfall_units: 150,
      shortfall_source: "inventory",
      shortfall_breakdown: { explanation: "x" },
      alert_stated_shortfall: 150,
    });
    expect(s.solverMeta.deadline_hours).toBe(38);
    expect(s.solveDurationMs).toBe(12);
    expect(s.rebuttalOccurred).toBe(true);
  });

  it("an executed run is shown as protected", () => {
    expect(runViewState({ ...response, executed: true }).statusMode).toBe("PROTECTED");
  });

  it("tolerates a minimal response", () => {
    const s = runViewState({ run_id: "RUN-2" });
    expect(s.playbooks).toEqual([]);
    expect(s.selectedPlaybookId).toBeNull();
    expect(s.shortfallInfo).toBeNull();
    expect(s.solverMeta.lp_status).toBe("");
  });
});

describe("rootRunId", () => {
  it("maps a sourced child to its root and a root to itself", () => {
    expect(rootRunId(response)).toBe("RUN-1");
    expect(rootRunId({ run_id: "RUN-2" })).toBe("RUN-2");
  });
});
