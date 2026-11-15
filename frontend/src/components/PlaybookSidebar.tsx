"use client";

import React from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import { CheckCircle2, ShieldCheck, Sparkles, Zap } from "lucide-react";

export function PlaybookSidebar() {
  const {
    playbooks,
    selectedPlaybookId,
    executePlaybook,
    isExecuting,
    statusMode,
  } = useFactoryStore();

  const isProtected = statusMode === "PROTECTED";

  if (playbooks.length === 0) {
    return (
      <aside className="w-full lg:w-[420px] rounded-[32px] island-card-static p-5 flex flex-col gap-4 shadow-island border border-white/50">
        <div className="pb-3 border-b border-charcoal-900/10">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-extrabold text-charcoal-900 tracking-tight flex items-center gap-1.5">
              <div className="p-1.5 rounded-xl bg-charcoal-900 text-acid">
                <Zap className="w-3.5 h-3.5" />
              </div>
              <span>Audited Recovery Playbooks</span>
            </h2>
            <span className="text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-full bg-white/50 text-charcoal-700 border border-white/70">
              Standby
            </span>
          </div>
          <p className="text-[11px] text-charcoal-600 font-medium leading-relaxed">
            Mathematical ranking via PuLP MILP optimizer & 1,000 Monte Carlo runs.
          </p>
        </div>

        <div className="flex-1 flex flex-col items-center justify-center py-16 px-4 text-center border-2 border-dashed border-charcoal-900/15 rounded-[24px] bg-white/10">
          <div className="w-12 h-12 rounded-2xl bg-white/40 border border-white/60 flex items-center justify-center mb-3 text-charcoal-700">
            <Zap className="w-6 h-6" />
          </div>
          <h3 className="text-xs font-mono font-bold text-charcoal-900 uppercase tracking-wider mb-1">
            PuLP Solver Standing By
          </h3>
          <p className="text-[11px] text-charcoal-700 leading-relaxed max-w-xs">
            Trigger a crisis from the top bar or mobile field controller to initiate real-time mathematical optimization.
          </p>
        </div>
      </aside>
    );
  }

  const activePlanId = selectedPlaybookId || (playbooks.find((p) => p.recommended)?.id ?? playbooks[0]?.id);

  return (
    <aside className="w-full lg:w-[420px] rounded-[32px] island-card-static p-5 flex flex-col gap-4 shadow-island border border-white/50">
      {/* ─── Header ────────────────────────────────────────────────────────── */}
      <div className="pb-3 border-b border-charcoal-900/10">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-sm font-extrabold text-charcoal-900 tracking-tight flex items-center gap-2">
            <div className="p-1.5 rounded-xl bg-charcoal-900 text-acid">
              <Zap className="w-3.5 h-3.5" />
            </div>
            <span>Audited Recovery Playbooks</span>
          </h2>
          <span className="text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-full bg-acid text-charcoal-950 border border-acid shadow-pill">
            ✓ LP Verified
          </span>
        </div>
        <p className="text-[11px] text-charcoal-600 font-medium leading-relaxed">
          Mathematically ranked by PuLP MILP cost optimizer & 1,000 Monte Carlo runs.
        </p>
      </div>

      {/* ─── Playbook Cards List ────────────────────────────────────────────── */}
      <div className="flex-1 space-y-3.5 overflow-y-auto pr-1">
        {playbooks.map((plan) => {
          const isWinner = plan.recommended;
          const isSelected = plan.id === activePlanId;

          return (
            <div
              key={plan.id}
              className={`rounded-[24px] p-4.5 transition-all duration-300 relative island-card ${
                isWinner
                  ? "!border-white/80 !bg-white/40 shadow-island ring-2 ring-white/60"
                  : isSelected
                  ? "!border-white/60 !bg-white/30"
                  : "!bg-white/20 hover:!bg-white/30"
              }`}
            >
              {/* Top Badge & ID */}
              <div className="flex items-center justify-between gap-2 mb-2">
                <span
                  className={`text-[10px] font-mono font-extrabold uppercase px-2.5 py-0.5 rounded-full ${
                    isWinner
                      ? "bg-acid text-charcoal-950 border border-acid shadow-pill"
                      : "bg-white/50 text-charcoal-800 border border-white/70"
                  }`}
                >
                  {plan.badge_label || plan.id}
                </span>

                <span className="text-xs font-mono font-extrabold text-forest-deep px-2 py-0.5 rounded-full bg-white/40 border border-white/60">
                  {plan.roi_multiplier}x ROI
                </span>
              </div>

              {/* Title */}
              <h3 className="text-xs font-bold text-charcoal-900 tracking-tight mb-2">
                {plan.name}
              </h3>

              {/* Financial Metrics Grid */}
              <div className="grid grid-cols-2 gap-2 p-3 rounded-2xl bg-white/40 border border-white/60 font-mono text-xs mb-3 shadow-sm">
                <div>
                  <span className="text-[10px] font-bold text-charcoal-600 uppercase block">Mitigation Spend</span>
                  <span className="text-charcoal-900 font-extrabold tabular-nums text-sm">
                    ₹{(plan.total_mitigation_cost_inr / 100000).toFixed(2)}L
                  </span>
                </div>
                <div>
                  <span className="text-[10px] font-bold text-charcoal-600 uppercase block">Net SLA Saved</span>
                  <span className="text-forest font-extrabold tabular-nums text-sm">
                    ₹{(plan.net_sla_saved_inr / 100000).toFixed(2)}L
                  </span>
                </div>
                <div>
                  <span className="text-[10px] font-bold text-charcoal-600 uppercase block">SLA Confidence</span>
                  <span className="text-charcoal-900 font-bold tabular-nums">
                    {plan.confidence_pct}%
                  </span>
                </div>
                <div>
                  <span className="text-[10px] font-bold text-charcoal-600 uppercase block">Overtime</span>
                  <span className="text-charcoal-800 font-bold tabular-nums">
                    {plan.overtime_hours ? `+${plan.overtime_hours}h Shift OT` : "0h"}
                  </span>
                </div>
              </div>

              {/* Summary text */}
              <p className="text-[11px] text-charcoal-800 font-medium leading-relaxed mb-3">
                {plan.description}
              </p>

              {/* Vendor Allocations breakdown */}
              {plan.vendor_allocations.length > 0 && (
                <div className="space-y-1 pt-2 border-t border-charcoal-900/10 font-mono text-[10.5px] text-charcoal-700 mb-3">
                  {plan.vendor_allocations.map((a, i) => (
                    <div key={i} className="flex justify-between items-center">
                      <span className="truncate max-w-[200px] text-charcoal-800 font-medium">• {a.supplier_name}</span>
                      <span className="text-charcoal-950 font-bold">{a.units_allocated} u @ ₹{a.cost_per_unit_inr}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* ─── Acid Lime Hero [APPROVE & EXECUTE] Button ────────────────── */}
              {isWinner && (
                <button
                  onClick={() => executePlaybook(plan.id)}
                  disabled={isExecuting || isProtected}
                  className={`w-full py-3 px-5 rounded-full font-bold text-xs font-mono transition-all duration-300 flex items-center justify-center gap-2 select-none ${
                    isProtected
                      ? "bg-forest text-acid border border-forest cursor-default shadow-sm"
                      : isExecuting
                      ? "bg-charcoal-700 text-white cursor-not-allowed"
                      : "bg-acid hover:bg-acid-hover text-charcoal-950 shadow-pill active:scale-[0.98]"
                  }`}
                >
                  {isProtected ? (
                    <>
                      <ShieldCheck className="w-4 h-4 text-acid" />
                      <span>APPROVED & DISPATCHED TO TALLY</span>
                    </>
                  ) : isExecuting ? (
                    <>
                      <Sparkles className="w-4 h-4 animate-spin" />
                      <span>COMMITTING TO ERP & WHATSAPP...</span>
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-4 h-4" />
                      <span>⚡ [APPROVE & DISPATCH PLAN B]</span>
                    </>
                  )}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}