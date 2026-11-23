import { formatInr, formatInrShort, plural } from "./format";

/** Order statuses that are not a problem: on track, or a recovery plan is already approved. */
export const HEALTHY_STATUSES = ["ON_TRACK", "RECOVERY_IN_PROGRESS", "EXTENSION_REQUESTED", "RISK_ACCEPTED", "SLA_PROTECTED"];

export interface RiskOrder {
  order_id: string;
  status: string;
  sla_penalty_inr: number;
  shortfall_units?: number;
}

export interface RiskSummary {
  count: number;
  penaltyInr: number;
}

export function riskSummary(orders: RiskOrder[]): RiskSummary {
  const at = orders.filter((o) => !HEALTHY_STATUSES.includes(o.status));
  return { count: at.length, penaltyInr: at.reduce((s, o) => s + (o.sla_penalty_inr ?? 0), 0) };
}

/** The headline of the status card. */
export function statusHeadline(r: RiskSummary): string {
  if (r.count === 0) return "All good";
  return `${plural(r.count, "order")} at risk`;
}

export function statusDetail(r: RiskSummary): string {
  if (r.count === 0) return "No order is at risk right now.";
  return `${formatInr(r.penaltyInr)} penalty if ${r.count === 1 ? "it ships" : "they ship"} late.`;
}

export interface PlanLike {
  id: string;
  name: string;
  strategy_type: string;
  total_mitigation_cost_inr: number;
  expected_cost_inr: number;
  confidence_pct: number;
  overtime_hours: number;
  overtime_line_hours?: Record<string, number>;
  vendor_allocations: { supplier_name: string; units_allocated: number }[];
  feasible: boolean;
  uncovered_units: number;
}

const short = (n: string) => n.split(" (")[0];

/** One plain sentence on what you would do under this plan. */
export function planSummary(p: PlanLike): string {
  if (p.strategy_type === "SLA_RENEGOTIATION" && !p.vendor_allocations.length && !p.overtime_hours) {
    return "Ask the customer for more time and accept the delay.";
  }
  const parts: string[] = [];
  for (const a of p.vendor_allocations) parts.push(`buy ${plural(a.units_allocated, "unit")} from ${short(a.supplier_name)}`);
  if (p.overtime_hours > 0) {
    const lines = Object.entries(p.overtime_line_hours ?? {}).filter(([, h]) => h > 0);
    parts.push(
      lines.length
        ? `run overtime (${lines.map(([l, h]) => `${l} ${h} h`).join(", ")})`
        : `run ${p.overtime_hours} h of overtime`,
    );
  }
  if (!parts.length) return "No extra spend needed.";
  const s = parts.join(" and ");
  return s.charAt(0).toUpperCase() + s.slice(1) + ".";
}

/** Friendly plan title; the backend's technical names stay in Advanced. */
export function planTitle(p: PlanLike, index: number): string {
  switch (p.strategy_type) {
    case "AIR_CHARTER_MAX_OT": return "Fastest plan";
    case "REGIONAL_BALANCED_OT": return "Balanced plan";
    case "TARGETED_OT_ONLY": return "Overtime only";
    case "SLA_RENEGOTIATION": return "Ask for more time";
    case "NO_ACTION": return "Do nothing";
    default: return p.name || `Plan ${index + 1}`;
  }
}

export function onTimeChance(p: PlanLike): string {
  return `${Math.round(p.confidence_pct)}%`;
}

export function costLine(p: PlanLike): string {
  return formatInrShort(p.total_mitigation_cost_inr);
}

export type FlowStep = "impact" | "plans" | "ask" | "approve";
export const FLOW_STEPS: { id: FlowStep; label: string }[] = [
  { id: "impact", label: "Impact" },
  { id: "plans", label: "Plans" },
  { id: "ask", label: "Ask suppliers" },
  { id: "approve", label: "Approve" },
];

export function stepIndex(s: FlowStep): number {
  return FLOW_STEPS.findIndex((x) => x.id === s);
}
