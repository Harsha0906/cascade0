"use client";

import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Flame,
  MessageSquare,
  Radio,
  RotateCcw,
  Send,
  ShieldCheck,
  Smartphone,
  Truck,
  Zap,
} from "lucide-react";

interface FactoryStateSummary {
  statusMode: "NORMAL" | "CRISIS" | "PROTECTED";
  orderClient: string;
  orderShortfall: number;
  contractRiskInr: number;
  lastAgentLog: string;
  lastAgentName: string;
  bestPlaybook: string | null;
  roiMultiplier: number;
}

export default function MobileControllerPage() {
  const [summary, setSummary] = useState<FactoryStateSummary>({
    statusMode: "NORMAL",
    orderClient: "Ather-Grid Mobility Corp (#EV-402)",
    orderShortfall: 0,
    contractRiskInr: 0,
    lastAgentLog: "All systems operating within nominal tolerances.",
    lastAgentName: "Detective",
    bestPlaybook: null,
    roiMultiplier: 13.9,
  });

  const [customPrompt, setCustomPrompt] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);

  // Poll state every 2 seconds for mobile responsiveness
  const refreshState = async () => {
    try {
      const res = await fetch("/api/v1/state");
      if (res.ok) {
        const data = await res.json();
        const ev402 = data.orders?.find((o: any) => o.order_id === "EV-402");
        const logs = data.agent_logs || [];
        const lastLog = logs.length > 0 ? logs[logs.length - 1] : null;

        const isProtected = ev402?.status === "SLA_PROTECTED";
        const isCrisis =
          ev402?.shortfall_units > 0 && !isProtected;

        setSummary({
          statusMode: isProtected ? "PROTECTED" : isCrisis ? "CRISIS" : "NORMAL",
          orderClient: ev402 ? `${ev402.client} (#${ev402.order_id})` : "Ather-Grid Mobility Corp (#EV-402)",
          orderShortfall: ev402?.shortfall_units || (isCrisis ? 150 : 0),
          contractRiskInr: isProtected ? 0 : isCrisis ? (ev402?.sla_penalty_inr || 2500000) : 0,
          lastAgentLog: lastLog ? lastLog.message : "All systems operating within nominal tolerances.",
          lastAgentName: lastLog ? lastLog.agent_name : "Detective",
          bestPlaybook: isProtected ? "PLAN B (EXECUTED)" : isCrisis ? "PLAN B (RECOMMENDED)" : null,
          roiMultiplier: 13.9,
        });
      }
    } catch {
      // Keep existing state if offline
    }
  };

  useEffect(() => {
    refreshState();
    const interval = setInterval(refreshState, 2000);
    return () => clearInterval(interval);
  }, []);

  const triggerScenario = async (scenarioId: number) => {
    setIsSubmitting(true);
    setFeedbackMsg(`Transmitting Scenario ${scenarioId} crisis telemetry...`);
    try {
      const res = await fetch("/api/v1/simulate-crisis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: scenarioId }),
      });
      if (res.ok) {
        setFeedbackMsg(`✅ Scenario ${scenarioId} dispatched! 4 Agents reasoning...`);
        await refreshState();
      }
    } catch {
      setFeedbackMsg("⚠️ Could not contact FastAPI backend.");
    } finally {
      setIsSubmitting(false);
      setTimeout(() => setFeedbackMsg(null), 4000);
    }
  };

  const triggerCustomDisruption = async () => {
    if (!customPrompt.trim()) return;
    setIsSubmitting(true);
    setFeedbackMsg("Transmitting custom WhatsApp/Voice disruption text...");
    try {
      const res = await fetch("/api/v1/simulate-crisis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ custom_text: customPrompt }),
      });
      if (res.ok) {
        setFeedbackMsg("✅ Extracted via Gemini & dispatched to LangGraph!");
        setCustomPrompt("");
        await refreshState();
      }
    } catch {
      setFeedbackMsg("⚠️ Error triggering custom disruption.");
    } finally {
      setIsSubmitting(false);
      setTimeout(() => setFeedbackMsg(null), 4000);
    }
  };

  const triggerReset = async () => {
    setIsSubmitting(true);
    setFeedbackMsg("Resetting factory to clean seed state...");
    try {
      await fetch("/api/v1/reset", { method: "POST" });
      setFeedbackMsg("✅ Factory restored to NORMAL operations.");
      await refreshState();
    } catch {
      setFeedbackMsg("⚠️ Error resetting factory.");
    } finally {
      setIsSubmitting(false);
      setTimeout(() => setFeedbackMsg(null), 3000);
    }
  };

  const executeRecommendedPlan = async () => {
    setIsSubmitting(true);
    setFeedbackMsg("Executing Plan B via Human-In-The-Loop action...");
    try {
      const poNum = `PO-APEX-2026-${Math.floor(100 + Math.random() * 900)}`;
      const res = await fetch("/api/v1/execute-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          po_number: poNum,
          playbook_id: "PLAN_B",
          order_id: "EV-402",
          allocations: [
            {
              supplier_id: "SUP-PNY-02",
              supplier_name: "Peenya Rapid Metals",
              tier: "TIER-2",
              units_allocated: 150,
              cost_per_unit_inr: 600,
              flat_charter_cost_inr: 0,
              total_cost_inr: 90000,
              lead_time_hours: 4,
              route: "Peenya (14 km)",
            },
          ],
          overtime_hours: 4,
          total_cost_inr: 180000,
          net_sla_saved_inr: 2320000,
          confidence_pct: 94.2,
          client: "Ather-Grid Mobility Corp",
        }),
      });
      if (res.ok) {
        setFeedbackMsg("✅ Plan B Executed! Tally PO Dispatched & SLA Protected.");
        await refreshState();
      }
    } catch {
      setFeedbackMsg("⚠️ Execution failed.");
    } finally {
      setIsSubmitting(false);
      setTimeout(() => setFeedbackMsg(null), 4000);
    }
  };

  const isCrisis = summary.statusMode === "CRISIS";
  const isProtected = summary.statusMode === "PROTECTED";

  return (
    <div className="min-h-screen text-charcoal-900 flex flex-col font-sans selection:bg-acid selection:text-charcoal-950 pb-28">
      {/* ─── Rinesk Floating Glass Mobile Header ────────────────────────────── */}
      <header className="sticky top-0 z-40 bg-white/20 backdrop-blur-2xl border-b border-white/50 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-charcoal-900 text-acid flex items-center justify-center font-black text-sm shadow-sm">
            ⚡
          </div>
          <div>
            <h1 className="text-sm font-extrabold tracking-tight text-charcoal-900 flex items-center gap-1.5">
              CASCADE<span className="text-forest font-semibold">ZERO</span>
              <span className="text-[9px] uppercase font-mono px-2 py-0.5 rounded-full bg-white/50 text-charcoal-800 border border-white/70 font-bold">
                MOBILE
              </span>
            </h1>
            <p className="text-[10px] text-charcoal-600 font-mono">
              Live Field Controller
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={triggerReset}
            disabled={isSubmitting}
            title="Reset Demo"
            className="p-2 rounded-full bg-white/50 hover:bg-white/80 border border-white/70 text-charcoal-800 active:scale-95 transition-all shadow-sm"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
          <a
            href="/"
            className="flex items-center gap-1 text-[11px] font-mono font-bold px-3 py-1.5 rounded-full bg-charcoal-900 text-white active:scale-95 transition-all shadow-sm"
          >
            <span>Twin</span>
            <ChevronRight className="w-3 h-3 text-acid" />
          </a>
        </div>
      </header>

      {/* ─── Feedback Toast Pill ────────────────────────────────────────────── */}
      {feedbackMsg && (
        <div className="mx-4 mt-3 px-4 py-2.5 rounded-full bg-white/60 backdrop-blur-xl border border-white/80 text-charcoal-950 text-xs font-mono shadow-island animate-fade-in flex items-center gap-2.5">
          <Radio className="w-3.5 h-3.5 text-forest shrink-0 animate-pulse" />
          <span className="font-semibold">{feedbackMsg}</span>
        </div>
      )}

      {/* ─── Main Content ───────────────────────────────────────────────────── */}
      <main className="p-4 flex flex-col gap-4">
        {/* ─── Status Hero Card (Anastasia Rinesk Large Typography) ─────────── */}
        <div
          className={`p-5 rounded-[28px] island-card transition-all ${
            isCrisis
              ? "!bg-coral/15 !border-coral !shadow-[0_16px_36px_rgba(255,71,87,0.3)] ring-2 ring-coral/50"
              : isProtected
              ? "!bg-acid/20 !border-acid !shadow-[0_16px_36px_rgba(229,244,58,0.25)] ring-2 ring-acid"
              : "!bg-white/30"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-charcoal-600">
              Plant Operational State
            </span>
            <div
              className={`flex items-center gap-1.5 px-3 py-0.5 rounded-full text-[10px] font-mono font-extrabold ${
                isCrisis
                  ? "bg-coral text-white border border-coral shadow-pill-coral animate-pulse"
                  : isProtected
                  ? "bg-acid text-charcoal-950 border border-acid shadow-pill"
                  : "bg-forest/15 text-forest-deep border border-forest/30"
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isCrisis ? "bg-white" : isProtected ? "bg-charcoal-900" : "bg-forest"
                }`}
              />
              <span>{summary.statusMode}</span>
            </div>
          </div>

          {/* Big Financial Risk Metric */}
          <div className="mt-3">
            <div className="text-[11px] font-mono font-semibold text-charcoal-600">
              {isCrisis ? "Contract Penalty Exposure" : isProtected ? "Mitigated SLA Value" : "Contract SLA Risk"}
            </div>
            <div
              className={`text-3xl font-extrabold font-mono tracking-tight tabular-nums mt-0.5 ${
                isCrisis
                  ? "text-coral"
                  : isProtected
                  ? "text-forest-deep"
                  : "text-charcoal-950"
              }`}
            >
              {isCrisis
                ? "-₹25,00,000"
                : isProtected
                ? "₹0 (Saved ₹23.20L)"
                : "₹0 Exposure"}
            </div>
          </div>

          {/* Order Details */}
          <div className="mt-4 pt-3 border-t border-charcoal-900/10 flex items-center justify-between text-xs font-mono">
            <div>
              <span className="text-charcoal-600 text-[10px] font-bold uppercase block">TARGET ORDER</span>
              <span className="text-charcoal-900 font-bold">EV-402 (500 units)</span>
            </div>
            <div className="text-right">
              <span className="text-charcoal-600 text-[10px] font-bold uppercase block">SHORTFALL</span>
              <span
                className={`font-extrabold ${
                  summary.orderShortfall > 0 ? "text-coral" : "text-forest"
                }`}
              >
                {summary.orderShortfall > 0 ? `${summary.orderShortfall} Units` : "0 Units"}
              </span>
            </div>
          </div>
        </div>

        {/* ─── Emergency HITL Action Banner (When Crisis Active) ────────────── */}
        {isCrisis && (
          <div className="p-5 rounded-[28px] island-card !bg-white/40 border border-white/80 shadow-island flex flex-col gap-3.5 animate-bounce-short">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-2xl bg-charcoal-900 text-acid shadow-sm">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-xs font-extrabold text-charcoal-900 uppercase tracking-wider font-mono">
                  PuLP LP Solver Ready
                </h3>
                <p className="text-[11px] text-charcoal-700 font-medium">
                  Plan B: Peenya 150u + 4h OT (₹1.80L mitigation • 13.9x ROI)
                </p>
              </div>
            </div>

            <button
              onClick={executeRecommendedPlan}
              disabled={isSubmitting}
              className="w-full py-3 px-5 rounded-full bg-acid hover:bg-acid-hover text-charcoal-950 font-mono font-extrabold text-xs uppercase tracking-wider flex items-center justify-center gap-2 shadow-pill active:scale-95 transition-all"
            >
              <Zap className="w-4 h-4 fill-charcoal-950" />
              <span>{isSubmitting ? "Dispatching PO..." : "⚡ [Approve & Dispatch Plan B]"}</span>
            </button>
          </div>
        )}

        {/* ─── Section: One-Tap Crisis Scenarios ─────────────────────────────── */}
        <div className="flex flex-col gap-2.5">
          <div className="flex items-center justify-between text-xs font-mono text-charcoal-700 px-1">
            <span className="uppercase tracking-wider font-bold">
              One-Tap Field Scenarios
            </span>
            <span className="text-[11px] text-charcoal-500 font-medium">Tap to Trigger</span>
          </div>

          {/* Scenario 1 Button */}
          <button
            onClick={() => triggerScenario(1)}
            disabled={isSubmitting}
            className="p-4 rounded-[24px] island-card text-left active:scale-[0.98] transition-all flex items-start gap-3.5"
          >
            <div className="w-9 h-9 rounded-2xl bg-coral/15 border border-coral/30 flex items-center justify-center shrink-0 mt-0.5 text-coral">
              <Flame className="w-5 h-5" />
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-charcoal-900 font-mono">
                  Scenario 1: Compound Disruption
                </span>
                <span className="text-[10px] font-mono font-extrabold px-2 py-0.5 rounded-full bg-coral/20 text-coral border border-coral/30">
                  150u Deficit
                </span>
              </div>
              <p className="text-[11px] text-charcoal-700 mt-1 leading-snug font-medium">
                NH48 Highway flood (48h delay) + Welding Line 2 throttled to 50% @ 89°C.
              </p>
              <span className="text-[10px] text-forest font-bold font-mono mt-1.5 block">
                → Recommended: Plan B (₹1.80L • 13.9x ROI)
              </span>
            </div>
          </button>

          {/* Scenario 2 Button */}
          <button
            onClick={() => triggerScenario(2)}
            disabled={isSubmitting}
            className="p-4 rounded-[24px] island-card text-left active:scale-[0.98] transition-all flex items-start gap-3.5"
          >
            <div className="w-9 h-9 rounded-2xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center shrink-0 mt-0.5 text-amber-800">
              <Cpu className="w-5 h-5" />
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-charcoal-900 font-mono">
                  Scenario 2: Minor Sensor Drift
                </span>
                <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-900 border border-amber-300">
                  25u Deficit
                </span>
              </div>
              <p className="text-[11px] text-charcoal-700 mt-1 leading-snug font-medium">
                Line 3 temperature spike (78°C). Minor casing shortfall.
              </p>
              <span className="text-[10px] text-forest font-bold font-mono mt-1.5 block">
                → Recommended: Plan C (2h Overtime @ ₹45k • 55.6x ROI)
              </span>
            </div>
          </button>

          {/* Scenario 3 Button */}
          <button
            onClick={() => triggerScenario(3)}
            disabled={isSubmitting}
            className="p-4 rounded-[24px] island-card text-left active:scale-[0.98] transition-all flex items-start gap-3.5"
          >
            <div className="w-9 h-9 rounded-2xl bg-purple-500/15 border border-purple-500/30 flex items-center justify-center shrink-0 mt-0.5 text-purple-900">
              <Truck className="w-5 h-5" />
            </div>
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-charcoal-900 font-mono">
                  Scenario 3: Severe Supply Cut
                </span>
                <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-purple-100 text-purple-900 border border-purple-300">
                  350u Deficit
                </span>
              </div>
              <p className="text-[11px] text-charcoal-700 mt-1 leading-snug font-medium">
                Chennai supplier transformer explosion. Full 350-unit deficit.
              </p>
              <span className="text-[10px] text-forest font-bold font-mono mt-1.5 block">
                → Recommended: Multi-tier Split (Peenya 200 + Hosur 150 + 8h OT)
              </span>
            </div>
          </button>
        </div>

        {/* ─── Section: Custom WhatsApp / Audio Text Disruption ─────────────── */}
        <div className="p-5 rounded-[28px] island-card flex flex-col gap-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-charcoal-900 text-acid">
              <MessageSquare className="w-4 h-4" />
            </div>
            <h3 className="text-xs font-extrabold text-charcoal-900 font-mono uppercase tracking-wider">
              Simulate WhatsApp / Field Alert
            </h3>
          </div>
          <p className="text-[11px] text-charcoal-600 font-medium leading-snug">
            Type natural language disruption text. Gemini will extract entities & trigger LangGraph.
          </p>

          <textarea
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            placeholder="e.g. Driver Ramesh reporting landslide near Krishnagiri on NH48. Truck stalled, 48 hours delayed."
            rows={3}
            className="w-full p-3 rounded-2xl bg-white/40 border border-white/60 text-xs text-charcoal-900 placeholder:text-charcoal-500 focus:outline-none focus:border-charcoal-900 font-sans resize-none shadow-inner"
          />

          {/* Quick Preset Chips */}
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() =>
                setCustomPrompt(
                  "Driver Ramesh reporting landslide near Krishnagiri on NH48. Truck stalled, 48 hours delayed."
                )
              }
              className="text-[10px] font-mono font-semibold px-2.5 py-1 rounded-full bg-white/50 hover:bg-white/80 border border-white/70 text-charcoal-800 text-left"
            >
              + NH48 Landslide (48h)
            </button>
            <button
              onClick={() =>
                setCustomPrompt(
                  "Robotic Welding Line 2 water cooling leak! Temperature spiked to 91C, speed throttled to 40%."
                )
              }
              className="text-[10px] font-mono font-semibold px-2.5 py-1 rounded-full bg-white/50 hover:bg-white/80 border border-white/70 text-charcoal-800 text-left"
            >
              + Line 2 Water Leak (91°C)
            </button>
          </div>

          <button
            onClick={triggerCustomDisruption}
            disabled={isSubmitting || !customPrompt.trim()}
            className="w-full py-2.5 px-4 rounded-full bg-charcoal-900 hover:bg-charcoal-800 text-acid font-mono font-bold text-xs flex items-center justify-center gap-2 disabled:opacity-40 active:scale-95 transition-all shadow-sm"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Transmit Disruption Alert</span>
          </button>
        </div>

        {/* ─── Realtime Agent Reasoner Feed Snippet ─────────────────────────── */}
        <div className="p-4 rounded-[24px] island-card flex flex-col gap-2 font-mono">
          <div className="flex items-center justify-between text-[11px] text-charcoal-600">
            <span className="flex items-center gap-1.5 text-charcoal-900 font-bold">
              <Radio className="w-3 h-3 text-forest animate-pulse" />
              Latest Multi-Agent Consensus
            </span>
            <span className="text-[10px] text-charcoal-500 font-semibold">Supabase Realtime</span>
          </div>
          <div className="text-xs text-charcoal-950 bg-white/40 p-3 rounded-2xl border border-white/60 leading-relaxed shadow-sm">
            <span className="font-extrabold text-charcoal-900 block mb-0.5">
              [{summary.lastAgentName}]
            </span>
            {summary.lastAgentLog}
          </div>
        </div>
      </main>

      {/* ─── Rinesk Floating Bottom Navigation Bar (Anastasia Cherniak Concept) ─ */}
      <nav className="fixed bottom-4 left-1/2 -translate-x-1/2 w-[90%] max-w-sm bg-white/60 backdrop-blur-2xl border border-white/80 rounded-full py-2.5 px-6 shadow-island flex items-center justify-around text-charcoal-800 z-50">
        <a href="#status" className="p-2 rounded-full hover:bg-white/50 transition-colors text-charcoal-950">
          <Smartphone className="w-5 h-5" />
        </a>
        <a href="#scenarios" className="p-2 rounded-full hover:bg-white/50 transition-colors text-charcoal-950">
          <Zap className="w-5 h-5" />
        </a>
        <button
          onClick={triggerReset}
          className="p-2 rounded-full hover:bg-white/50 transition-colors text-charcoal-950"
          title="Reset"
        >
          <RotateCcw className="w-5 h-5" />
        </button>
      </nav>
    </div>
  );
}