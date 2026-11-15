"use client";

import React from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import { ArrowRight, Bot, CheckCircle2, Clock, Sparkles, Zap } from "lucide-react";

export function AgentPipelineStrip() {
  const { isSimulating, statusMode, solveDurationMs, rebuttalOccurred } = useFactoryStore();

  const isCrisisOrProtected = statusMode === "CRISIS" || statusMode === "PROTECTED";

  return (
    <div className="w-full px-4 sm:px-6 py-1">
      <div className="w-full max-w-[1880px] mx-auto island-card-static px-5 py-2 flex items-center justify-between gap-4 text-xs font-mono overflow-x-auto">
        {/* ─── Left: 4-Agent Pipeline Steps ─────────────────────────────────── */}
        <div className="flex items-center gap-2.5 shrink-0">
          <span className="text-[11px] font-bold text-charcoal-700 uppercase tracking-wider flex items-center gap-1.5 mr-1">
            <Bot className="w-3.5 h-3.5 text-forest" />
            <span>Agent Pipeline:</span>
          </span>

          {/* 1. Detective Pill */}
          <div
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full border transition-all ${
              isSimulating
                ? "bg-amber-100 border-amber-400 text-amber-950 font-bold animate-pulse shadow-sm"
                : isCrisisOrProtected
                ? "bg-white/60 border-white/80 text-charcoal-900 font-semibold"
                : "bg-white/30 border-white/40 text-charcoal-700"
            }`}
          >
            <span>🕵️‍♂️</span>
            <span className="text-xs">Detective</span>
            {isCrisisOrProtected && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-700" />}
          </div>

          <ArrowRight className="w-3 h-3 text-charcoal-600 shrink-0" />

          {/* 2 & 3. Ops Hawk vs CFO Watchdog Rebuttal Capsule */}
          <div
            className={`flex items-center gap-2 px-3 py-1 rounded-full border transition-all ${
              rebuttalOccurred
                ? "bg-coral/20 border-coral text-coral font-bold shadow-sm"
                : isCrisisOrProtected
                ? "bg-white/60 border-white/80 text-charcoal-900 font-semibold"
                : "bg-white/30 border-white/40 text-charcoal-700"
            }`}
          >
            <span className="text-xs">⚙️ Ops Hawk</span>
            <span className="text-[10px] font-bold px-1.5 py-0.2 rounded-full bg-charcoal-900/10 text-charcoal-900">
              vs
            </span>
            <span className="text-xs">💰 CFO Watchdog</span>

            {rebuttalOccurred && (
              <span className="text-[10px] uppercase px-1.5 py-0.5 rounded-full bg-coral text-white font-bold ml-1">
                Rebuttal Looped
              </span>
            )}
          </div>

          <ArrowRight className="w-3 h-3 text-charcoal-600 shrink-0" />

          {/* 4. Arbitrator + PuLP LP Pill */}
          <div
            className={`flex items-center gap-1.5 px-3 py-1 rounded-full border transition-all ${
              isCrisisOrProtected
                ? "bg-white/80 border-white text-charcoal-950 font-bold shadow-sm"
                : "bg-white/30 border-white/40 text-charcoal-700"
            }`}
          >
            <span>⚖️</span>
            <span className="text-xs">Mathematical Arbitrator</span>
            {isCrisisOrProtected && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-700" />}
          </div>
        </div>

        {/* ─── Right: Performance & Solve Duration Pill ─────────────────────── */}
        <div className="flex items-center gap-3 shrink-0 text-xs text-charcoal-800">
          {solveDurationMs > 0 && (
            <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-white/50 border border-white/60">
              <Clock className="w-3 h-3 text-emerald-800" />
              <span>Solved:</span>
              <span className="font-bold tabular-nums text-charcoal-950">{solveDurationMs}ms</span>
            </div>
          )}

          <div className="flex items-center gap-1 px-3 py-1 rounded-full bg-white/40 border border-white/50">
            <span>Monte Carlo:</span>
            <span className="font-bold text-charcoal-950">1,000 runs</span>
          </div>
        </div>
      </div>
    </div>
  );
}
