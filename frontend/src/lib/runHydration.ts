import type { ShortfallParams } from "./twinGraph";

/** The fields of a /simulate-crisis (or GET /runs/{run_id}) response that the dashboard uses. */
export interface RunResponse<P = unknown> {
  run_id: string;
  root_run_id?: string;
  executed?: boolean;
  scenario_id?: number | null;
  playbooks?: P[];
  recommended_plan_id?: string | null;
  rebuttal_occurred?: boolean;
  rebuttal_notes?: string[];
  ai_mode?: unknown;
  extracted_parameters?: {
    affected_order_id?: string | null;
    shortfall_units?: number | null;
    shortfall_source?: ShortfallParams["shortfall_source"];
    shortfall_breakdown?: ShortfallParams["shortfall_breakdown"];
    alert_stated_shortfall?: number | null;
  };
  solver_result?: {
    solve_duration_ms?: number;
    lp_status?: string;
    ranking_rule?: string;
    deadline_hours?: number;
    capacity_exhausted?: boolean;
    throughput_gap_units?: number;
  };
}

export interface RunViewState<P = unknown> {
  statusMode: "CRISIS" | "PROTECTED";
  playbooks: P[];
  selectedPlaybookId: string | null;
  activeRunId: string;
  activeOrderId: string | null;
  shortfallInfo: ShortfallParams | null;
  solveDurationMs: number;
  rebuttalOccurred: boolean;
  rebuttalNotes: string[];
  aiMode: unknown;
  solverMeta: {
    lp_status: string;
    ranking_rule: string;
    deadline_hours: number;
    capacity_exhausted: boolean;
    throughput_gap_units: number;
  };
}

/** Dashboard state for a run: used after a simulation and to restore the latest run on reload. */
export function runViewState<P>(data: RunResponse<P>): RunViewState<P> {
  const sr = data.solver_result || {};
  const ep = data.extracted_parameters;
  return {
    statusMode: data.executed ? "PROTECTED" : "CRISIS",
    playbooks: data.playbooks || [],
    selectedPlaybookId: data.recommended_plan_id || null,
    activeRunId: data.run_id,
    activeOrderId: ep?.affected_order_id ?? null,
    shortfallInfo: ep?.shortfall_source
      ? {
          shortfall_units: ep.shortfall_units ?? 0,
          shortfall_source: ep.shortfall_source,
          shortfall_breakdown: ep.shortfall_breakdown ?? null,
          alert_stated_shortfall: ep.alert_stated_shortfall ?? null,
        }
      : null,
    solveDurationMs: sr.solve_duration_ms ?? 0,
    rebuttalOccurred: !!data.rebuttal_occurred,
    rebuttalNotes: data.rebuttal_notes || [],
    aiMode: data.ai_mode || null,
    solverMeta: {
      lp_status: sr.lp_status || "",
      ranking_rule: sr.ranking_rule || "",
      deadline_hours: sr.deadline_hours ?? 0,
      capacity_exhausted: !!sr.capacity_exhausted,
      throughput_gap_units: sr.throughput_gap_units ?? 0,
    },
  };
}

/** The run whose Sourcing session and Client record belong to `data` (a sourced child maps to its root). */
export function rootRunId(data: Pick<RunResponse, "run_id" | "root_run_id">): string {
  return data.root_run_id || data.run_id;
}
