"use client";

import React from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import { focusOrder, ordersSummary, shortfallText, throttledLinesText } from "@/lib/twinGraph";
import { AiModeBadge } from "@/components/AiModeBadge";
import { SourcingPanel } from "@/components/SourcingPanel";
import { ClientPanel } from "@/components/ClientPanel";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Cpu,
  DollarSign,
  FileText,
  Flame,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Truck,
  Users,
  Zap,
} from "lucide-react";

export function ExecutiveStoryView() {
  const {
    statusMode,
    orders,
    productionLines,
    suppliers,
    playbooks,
    selectedPlaybookId,
    executePlaybook,
    isExecuting,
    rebuttalOccurred,
    rebuttalNotes,
    solveDurationMs,
    solverMeta,
    lastError,
    openCustomCrisisModal,
    setDashboardViewMode,
    executionReceipt,
    openReceiptModal,
    activeOrderId,
    shortfallInfo,
    factory,
    factoryName,
  } = useFactoryStore();

  const isCrisis = statusMode === "CRISIS";
  const isProtected = statusMode === "PROTECTED";
  const focus = focusOrder(orders, activeOrderId);
  const selectedPlan =
    playbooks.find((p) => p.id === selectedPlaybookId) || playbooks.find((p) => p.recommended);
  const opsPlan = playbooks.find((p) => p.id === "PLAN_A");
  const cfoPlan = playbooks.find((p) => p.id === "PLAN_B");
  const throttled = throttledLinesText(productionLines);
  const atRiskOrders = orders.filter((o) => o.status !== "ON_TRACK");
  const exposureInr = atRiskOrders.reduce((sum, o) => sum + (o.sla_penalty_inr ?? 0), 0);
  const maxTemp = productionLines.length ? Math.max(...productionLines.map((l) => l.temp_celsius)) : null;
  const totalUnits = orders.reduce((sum, o) => sum + o.required_qty, 0);
  const dailyCapacity = productionLines.reduce((sum, l) => sum + l.daily_capacity_units, 0);
  const normalTemps = productionLines.map((l) => l.temp_celsius);
  const tempRange = normalTemps.length ? `${Math.min(...normalTemps)}-${Math.max(...normalTemps)}°C` : "n/a";
  const lakh = (n: number) => `₹${(n / 100000).toFixed(2)}L`;

  return (
    <div className="w-full max-w-[1400px] mx-auto p-4 sm:p-6 flex flex-col gap-6 animate-in fade-in duration-300">
      {/* ─── 1. HERO EXECUTIVE SUMMARY BANNER ─────────────────────────────────── */}
      <div
        className={`p-6 sm:p-8 rounded-[32px] border shadow-xl transition-all ${
          isCrisis
            ? "bg-gradient-to-br from-coral/15 via-white/80 to-coral/5 border-coral/30 shadow-coral/10"
            : isProtected
            ? "bg-gradient-to-br from-emerald-500/15 via-white/80 to-emerald-500/5 border-emerald-500/30 shadow-emerald-500/10"
            : "bg-white/80 border-white/60 shadow-island"
        }`}
      >
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="flex items-start gap-4">
            <div
              className={`w-14 h-14 rounded-3xl flex items-center justify-center shrink-0 shadow-lg ${
                isCrisis
                  ? "bg-coral text-white shadow-pill-coral animate-pulse"
                  : isProtected
                  ? "bg-emerald-600 text-white"
                  : "bg-acid text-charcoal-900 shadow-pill"
              }`}
            >
              {isCrisis ? (
                <ShieldAlert className="w-7 h-7" />
              ) : isProtected ? (
                <ShieldCheck className="w-7 h-7" />
              ) : (
                <Zap className="w-7 h-7 fill-current" />
              )}
            </div>

            <div>
              <div className="flex items-center gap-2.5 flex-wrap">
                <span
                  className={`text-xs font-mono font-bold px-3 py-1 rounded-full uppercase tracking-wider ${
                    isCrisis
                      ? "bg-coral text-white"
                      : isProtected
                      ? "bg-emerald-600 text-white"
                      : "bg-forest/15 text-forest-deep"
                  }`}
                >
                  {isCrisis
                    ? "CRITICAL INCIDENT IN PROGRESS"
                    : isProtected
                    ? "RECOVERY PLAN APPROVED"
                    : "ALL SYSTEMS NOMINAL"}
                </span>

                <span className="text-xs font-mono text-charcoal-500">
                  {factory?.name || factoryName || "Loading factory…"}
                </span>
              </div>

              <h2 className="text-xl sm:text-2xl font-extrabold text-charcoal-900 tracking-tight mt-2">
                {isCrisis
                  ? `Compound Risk: ${lakh(focus?.sla_penalty_inr ?? 0)} SLA Penalty on Order #${focus?.order_id ?? "?"}`
                  : isProtected
                  ? "Recovery Plan Approved: Draft PO & Notices Generated"
                  : `${atRiskOrders.length ? `${lakh(exposureInr)} exposure across ${atRiskOrders.length} at-risk order(s)` : "No at-risk orders"} • ${throttled ? `Throttled: ${throttled}` : "All production lines running"}`}
              </h2>

              <p className="text-xs sm:text-sm text-charcoal-700 font-medium max-w-2xl mt-1 leading-relaxed">
                {isCrisis
                  ? `Inbound supply disruption${throttled ? ` combined with throttled lines: ${throttled}` : ""}. ${focus?.shortfall_units ?? 0} units short.`
                  : isProtected && selectedPlan
                  ? `${selectedPlan.id} approved: ${lakh(selectedPlan.total_mitigation_cost_inr)} spend, modelled on-time probability ${selectedPlan.confidence_pct}%. Delivery is not guaranteed until suppliers confirm.`
                  : "Run a scenario or paste a disruption alert to get ranked recovery plans. Telemetry in this demo is simulated."}
              </p>
              {isCrisis && shortfallInfo && (
                <p className="text-xs font-mono text-charcoal-600 mt-1.5" data-testid="shortfall-explanation">
                  Shortfall: {shortfallText(shortfallInfo)}
                </p>
              )}
            </div>
          </div>

          {/* Quick Metrics Capsule */}
          <div className="flex items-center gap-3 shrink-0">
            <button
              onClick={openCustomCrisisModal}
              className="flex items-center gap-2 px-5 py-3 rounded-2xl bg-charcoal-900 text-white hover:bg-charcoal-800 font-mono font-bold text-xs shadow-md transition-all active:scale-95"
            >
              <Sparkles className="w-4 h-4 text-acid" />
              <span>Custom Crisis Studio</span>
            </button>

            <button
              onClick={() => setDashboardViewMode("TWIN")}
              className="flex items-center gap-2 px-5 py-3 rounded-2xl bg-white hover:bg-white/80 border border-charcoal-900/15 font-mono font-bold text-xs text-charcoal-800 shadow-sm transition-all active:scale-95"
            >
              <span>2.5D Digital Twin</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* ─── 2. THE 3-STEP DECISION ARCHITECTURE (When Crisis or Protected) ───── */}
      {selectedPlan ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* STEP 1: The Multi-Agent Dispute */}
          <div className="island-card p-6 flex flex-col justify-between border border-white/70">
            <div>
              <div className="flex items-center justify-between text-xs font-mono mb-4">
                <span className="font-extrabold text-charcoal-900 uppercase tracking-wider flex items-center gap-2">
                  <Users className="w-4 h-4 text-forest" />
                  <span>1. Planning Scenarios</span>
                </span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-forest/10 text-forest-deep">
                  Solver-computed
                </span>
              </div>

              <div className="space-y-3">
                {/* Speed scenario */}
                <div className="p-3.5 rounded-2xl bg-rose-50/80 border border-rose-200/60">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-rose-900 flex items-center gap-1.5">
                      🦅 Speed scenario (expedite-first)
                    </span>
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-rose-200 text-rose-900">
                      SLA Survival
                    </span>
                  </div>
                  <p className="text-[11px] text-rose-950 mt-1.5 leading-relaxed">
                    {opsPlan
                      ? `${opsPlan.description} — ${lakh(opsPlan.total_mitigation_cost_inr)}, P(on-time) ${opsPlan.confidence_pct}%.`
                      : "—"}
                  </p>
                </div>

                {/* Cost scenario */}
                <div className="p-3.5 rounded-2xl bg-cyan-50/80 border border-cyan-200/60">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-cyan-900 flex items-center gap-1.5">
                      🛡️ Cost scenario (cheapest feasible)
                    </span>
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-cyan-200 text-cyan-900">
                      Capital Preservation
                    </span>
                  </div>
                  <p className="text-[11px] text-cyan-950 mt-1.5 leading-relaxed">
                    {cfoPlan
                      ? `${cfoPlan.description} — ${lakh(cfoPlan.total_mitigation_cost_inr)}, P(on-time) ${cfoPlan.confidence_pct}%.`
                      : "—"}
                  </p>
                </div>

                {/* Dispute Resolution */}
                <div className="p-2.5 rounded-xl bg-charcoal-900/5 text-[11px] font-mono text-charcoal-700 flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-forest shrink-0" />
                  <span>
                    {rebuttalOccurred && rebuttalNotes.length
                      ? rebuttalNotes.join(" → ")
                      : "No rebuttal: the cost-minimal plan raised no reliability or deadline risk."}
                  </span>
                </div>
              </div>
            </div>

            <p className="text-[10px] font-mono text-charcoal-500 mt-4 border-t border-charcoal-900/10 pt-2">
              Positions computed by the solver <AiModeBadge className="ml-1" />
            </p>
          </div>

          {/* STEP 2: The PuLP Mathematical Proof */}
          <div className="island-card p-6 flex flex-col justify-between border border-white/70">
            <div>
              <div className="flex items-center justify-between text-xs font-mono mb-4">
                <span className="font-extrabold text-charcoal-900 uppercase tracking-wider flex items-center gap-2">
                  <Scale className="w-4 h-4 text-emerald-600" />
                  <span>2. Mathematical Optimization</span>
                </span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800">
                  PuLP MILP Solver
                </span>
              </div>

              <div className="p-4 rounded-2xl bg-white border border-charcoal-900/10 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono text-charcoal-600">Recommended Plan:</span>
                  <span className="text-xs font-mono font-extrabold text-charcoal-900">
                    [{selectedPlan.id}] {selectedPlan.name}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3 pt-2 border-t border-charcoal-900/10">
                  <div>
                    <span className="text-[10px] font-mono text-charcoal-500 block">Mitigation Cost</span>
                    <span className="text-base font-extrabold font-mono text-coral">
                      ₹{selectedPlan.total_mitigation_cost_inr.toLocaleString()}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] font-mono text-charcoal-500 block">Net SLA Preserved</span>
                    <span className="text-base font-extrabold font-mono text-emerald-700">
                      ₹{selectedPlan.net_sla_saved_inr.toLocaleString()}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 pt-2 border-t border-charcoal-900/10">
                  <div>
                    <span className="text-[10px] font-mono text-charcoal-500 block">Penalty ÷ cost</span>
                    <span className="text-sm font-extrabold font-mono text-charcoal-900">
                      {selectedPlan.roi_multiplier}x
                      {selectedPlan.strategy_type === "SLA_RENEGOTIATION" && " (if client accepts)"}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] font-mono text-charcoal-500 block">Modelled P(on-time)</span>
                    <span className="text-sm font-extrabold font-mono text-forest">
                      {selectedPlan.confidence_pct}%
                      {selectedPlan.confidence_ci_low_pct != null &&
                        ` (95% CI ${selectedPlan.confidence_ci_low_pct}–${selectedPlan.confidence_ci_high_pct})`}
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-3 text-[11px] text-charcoal-600 leading-relaxed">
                ⚖️ <strong>How it was chosen:</strong> lowest expected cost (spend + (1 − P on-time) × penalty) ={" "}
                {lakh(selectedPlan.expected_cost_inr)}. Solver: {solverMeta?.lp_status || "—"} in {solveDurationMs}ms.
                Results are only as good as the vendor, cost and lead-time inputs.
                {!selectedPlan.feasible && (
                  <span className="block text-coral font-bold mt-1">
                    ⚠ Capacity exhausted: {selectedPlan.uncovered_units} units uncovered.
                  </span>
                )}
              </div>
            </div>

            <p className="text-[10px] font-mono text-charcoal-500 mt-4 border-t border-charcoal-900/10 pt-2">
              PuLP MILP (HiGHS/CBC) • 1,000-run Monte Carlo
            </p>
          </div>

          {/* STEP 3: One-Tap Human-In-The-Loop Execution */}
          <div className="island-card p-6 flex flex-col justify-between border-2 border-acid/80 bg-gradient-to-br from-white via-white to-acid/10 shadow-xl">
            <div>
              <div className="flex items-center justify-between text-xs font-mono mb-4">
                <span className="font-extrabold text-charcoal-900 uppercase tracking-wider flex items-center gap-2">
                  <Zap className="w-4 h-4 text-charcoal-950 fill-current" />
                  <span>3. Executive Action</span>
                </span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-charcoal-900 text-acid">
                  HITL APPROVED
                </span>
              </div>

              <div className="space-y-3">
                <p className="text-xs text-charcoal-700 leading-relaxed font-medium">
                  Approving generates drafts — nothing is sent automatically:
                </p>
                <ul className="text-xs text-charcoal-800 space-y-2">
                  <li className="flex items-start gap-2">
                    <span className="w-4 h-4 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">✓</span>
                    <span>
                      {selectedPlan.vendor_allocations.length
                        ? `Tally Prime XML purchase order for ${selectedPlan.vendor_allocations
                            .map((a) => a.supplier_name.split(" (")[0])
                            .join(", ")}.`
                        : "No supplier PO needed for this plan."}
                    </span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="w-4 h-4 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">✓</span>
                    <span>
                      {selectedPlan.overtime_hours
                        ? `Shift notice: ${
                            Object.entries(selectedPlan.overtime_line_hours ?? {})
                              .filter(([, h]) => h > 0)
                              .map(([line, h]) => `${line} ${h}h`)
                              .join(", ") || `${selectedPlan.overtime_hours}h`
                          } overtime.`
                        : "No overtime notice needed."}
                    </span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="w-4 h-4 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">✓</span>
                    <span>Client notice for {focus?.client || "the client"} stating the modelled on-time probability.</span>
                  </li>
                </ul>
                <SourcingPanel />
                <ClientPanel />
              </div>
            </div>

            <div className="mt-6 pt-4 border-t border-charcoal-900/10 space-y-2">
              {isProtected || executionReceipt ? (
                <button
                  onClick={openReceiptModal}
                  className="w-full py-4 rounded-2xl font-mono font-extrabold text-xs bg-emerald-600 hover:bg-emerald-700 text-white shadow-lg transition-all active:scale-95 flex items-center justify-center gap-2"
                >
                  <FileText className="w-4 h-4" />
                  <span>View Draft Tally PO & Notices</span>
                </button>
              ) : (
                <button
                  onClick={() => executePlaybook(selectedPlan.id)}
                  disabled={isExecuting || !selectedPlan.feasible}
                  className="w-full py-4 rounded-2xl font-mono font-extrabold text-xs bg-acid hover:bg-acid-hover text-charcoal-950 shadow-pill transition-all active:scale-95 flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  <Zap className="w-4 h-4 fill-current" />
                  <span>{isExecuting ? "Generating drafts..." : `⚡ APPROVE ${selectedPlan.id.replace("_", " ")}`}</span>
                </button>
              )}
              {lastError ? (
                <p role="alert" className="text-[11px] font-mono text-center text-coral font-bold">
                  {lastError}
                </p>
              ) : (
                <p className="text-[10px] font-mono text-center text-charcoal-500">Human approval required</p>
              )}
            </div>
          </div>
        </div>
      ) : (
        /* Nominal State: 3 High-Level Plant Cards */
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="island-card p-6 border border-white/60">
            <div className="flex items-center justify-between text-xs font-mono text-charcoal-600">
              <span className="font-bold uppercase">Contract Orders</span>
              <span className="text-forest font-bold">{orders.length} ACTIVE</span>
            </div>
            <div className="text-3xl font-extrabold font-mono text-charcoal-900 mt-2">
              {totalUnits} Units
            </div>
            <p className="text-xs text-charcoal-600 mt-1">
              {ordersSummary(orders)}. All on schedule.
            </p>
          </div>

          <div className="island-card p-6 border border-white/60">
            <div className="flex items-center justify-between text-xs font-mono text-charcoal-600">
              <span className="font-bold uppercase">Robotic Lines</span>
              <span className="text-forest font-bold">{dailyCapacity} u/day</span>
            </div>
            <div className="text-3xl font-extrabold font-mono text-charcoal-900 mt-2">
              {productionLines.length} Lines Active
            </div>
            <p className="text-xs text-charcoal-600 mt-1">
              {productionLines.map((l) => l.name).join(", ")} temperatures {tempRange}{maxTemp !== null ? ` (max ${maxTemp}°C)` : ""}.
            </p>
          </div>

          <div className="island-card p-6 border border-white/60">
            <div className="flex items-center justify-between text-xs font-mono text-charcoal-600">
              <span className="font-bold uppercase">Multi-Agent Control</span>
              <span className="text-forest font-bold">{atRiskOrders.length} AT RISK</span>
            </div>
            <div className="text-3xl font-extrabold font-mono text-charcoal-900 mt-2">
              {atRiskOrders.length} At-Risk Orders
            </div>
            <p className="text-xs text-charcoal-600 mt-1">
              Ready to rank recovery plans when a disruption is reported.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
