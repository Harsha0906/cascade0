"use client";

import React, { useState } from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Cpu,
  Flame,
  HelpCircle,
  Sliders,
  Sparkles,
  Truck,
  Wrench,
  X,
  Zap,
} from "lucide-react";

export function CrisisSandboxModal() {
  const {
    isCustomCrisisModalOpen,
    closeCustomCrisisModal,
    simulateCrisis,
    simulateCustom,
    isSimulating,
    factory,
    orders,
    scenarios,
    scenariosError,
  } = useFactoryStore();

  const [activeTab, setActiveTab] = useState<"TEMPLATES" | "FREEFORM" | "SLIDERS">("TEMPLATES");

  // Form states
  const [freeformPrompt, setFreeformPrompt] = useState("");
  const [targetOrderChoice, setTargetOrder] = useState<string | null>(null);
  const [shortfallUnits, setShortfallUnits] = useState(150);
  const [delayHours, setDelayHours] = useState(48);
  const [lineSpeeds, setLineSpeeds] = useState<Record<string, number>>({});

  if (!isCustomCrisisModalOpen) return null;

  const lines = factory?.lines ?? [];
  const targetOrder = targetOrderChoice ?? orders[0]?.order_id ?? "";
  const speedOf = (lineId: string) => lineSpeeds[lineId] ?? 100;
  const placeholder = `e.g. Truck breakdown, 120 units short on ${orders[0]?.order_id ?? "an order"}, ${lines[0]?.name ?? "a line"} running at 50%...`;

  const handleInjectTemplate = async (scenarioId: number) => {
    closeCustomCrisisModal();
    await simulateCrisis(scenarioId);
  };

  const handleInjectFreeform = async () => {
    if (!freeformPrompt.trim()) return;
    closeCustomCrisisModal();
    await simulateCrisis(undefined, freeformPrompt);
  };

  const handleInjectSliders = async () => {
    const override_line_speeds: Record<string, number> = {};
    for (const l of lines) {
      if (speedOf(l.line_id) < 100) override_line_speeds[l.line_id] = speedOf(l.line_id);
    }
    closeCustomCrisisModal();
    await simulateCustom({
      override_delay_hours: delayHours,
      override_shortfall_units: shortfallUnits,
      override_line_speeds,
      order_id: targetOrder || undefined,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-charcoal-950/60 backdrop-blur-md animate-in fade-in duration-200">
      <div
        className="w-full max-w-2xl bg-white/95 backdrop-blur-2xl rounded-3xl border border-white/60 shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-6 border-b border-charcoal-900/10 flex items-center justify-between bg-gradient-to-r from-forest/5 via-transparent to-acid/10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-acid flex items-center justify-center shadow-pill shrink-0">
              <Zap className="w-5 h-5 text-charcoal-900 fill-charcoal-900" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-extrabold text-charcoal-900 tracking-tight">
                  Custom Crisis Scenario Studio
                </h2>
                <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-charcoal-900 text-acid">
                  LIVE INJECTOR
                </span>
              </div>
              <p className="text-xs text-charcoal-600 font-medium">
                Inject any real-world disruption & watch the 4-Agent PuLP solver optimize on the fly.
              </p>
            </div>
          </div>
          <button
            onClick={closeCustomCrisisModal}
            className="w-8 h-8 rounded-full bg-charcoal-900/5 hover:bg-charcoal-900/10 flex items-center justify-center text-charcoal-600 transition-all active:scale-95"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab Switcher */}
        <div className="px-6 pt-4 pb-2 border-b border-charcoal-900/5 flex items-center gap-2">
          <button
            onClick={() => setActiveTab("TEMPLATES")}
            className={`px-4 py-2 rounded-xl text-xs font-mono font-bold transition-all ${
              activeTab === "TEMPLATES"
                ? "bg-charcoal-900 text-white shadow-sm"
                : "bg-charcoal-900/5 text-charcoal-700 hover:bg-charcoal-900/10"
            }`}
          >
            ⚡ Realistic Presets
          </button>
          <button
            onClick={() => setActiveTab("FREEFORM")}
            className={`px-4 py-2 rounded-xl text-xs font-mono font-bold transition-all ${
              activeTab === "FREEFORM"
                ? "bg-charcoal-900 text-white shadow-sm"
                : "bg-charcoal-900/5 text-charcoal-700 hover:bg-charcoal-900/10"
            }`}
          >
            ✍️ Natural Language Prompt
          </button>
          <button
            onClick={() => setActiveTab("SLIDERS")}
            className={`px-4 py-2 rounded-xl text-xs font-mono font-bold transition-all ${
              activeTab === "SLIDERS"
                ? "bg-charcoal-900 text-white shadow-sm"
                : "bg-charcoal-900/5 text-charcoal-700 hover:bg-charcoal-900/10"
            }`}
          >
            🎛️ Interactive Sliders
          </button>
        </div>

        {/* Tab Content */}
        <div className="p-6 overflow-y-auto flex-1 space-y-4">
          {/* TAB 1: TEMPLATES */}
          {activeTab === "TEMPLATES" && (
            <div className="grid grid-cols-1 gap-3">
              {scenariosError && (
                <div className="p-3 rounded-xl bg-coral/10 border border-coral/30 text-[11px] font-mono text-coral">
                  {scenariosError}
                </div>
              )}
              {scenarios.map((sc) => (
                <button
                  key={sc.scenario_id}
                  onClick={() => handleInjectTemplate(sc.scenario_id)}
                  disabled={isSimulating}
                  className="p-4 rounded-2xl border border-charcoal-900/10 bg-white hover:bg-acid/15 hover:border-acid text-left transition-all group flex items-start justify-between gap-4"
                >
                  <div className="flex items-start gap-3">
                    <div className="w-8 h-8 rounded-xl bg-coral/15 text-coral flex items-center justify-center shrink-0 mt-0.5">
                      <Truck className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-xs font-extrabold text-charcoal-900 group-hover:text-charcoal-950">
                        {sc.title}
                      </h4>
                      <p className="text-[11px] text-charcoal-600 mt-0.5">{sc.summary}</p>
                      <div className="flex items-center gap-2 mt-2 text-[10px] font-mono text-charcoal-500">
                        <span className="px-2 py-0.5 rounded bg-charcoal-900/5">Target: #{sc.order_id}</span>
                        <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">Plans computed on run</span>
                      </div>
                    </div>
                  </div>
                  <ArrowRight className="w-4 h-4 text-charcoal-400 group-hover:translate-x-1 transition-all shrink-0 mt-2" />
                </button>
              ))}
              {!scenarios.length && !scenariosError && (
                <div className="text-[11px] font-mono text-charcoal-500">Loading scenario presets...</div>
              )}
            </div>
          )}

          {/* TAB 2: FREEFORM */}
          {activeTab === "FREEFORM" && (
            <div className="space-y-3">
              <label className="text-xs font-mono font-bold text-charcoal-800 block">
                Type Any Unstructured Disruption Report:
              </label>
              <textarea
                value={freeformPrompt}
                onChange={(e) => setFreeformPrompt(e.target.value)}
                rows={4}
                className="w-full p-4 rounded-2xl bg-white border border-charcoal-900/15 text-xs text-charcoal-900 font-sans focus:outline-none focus:ring-2 focus:ring-acid resize-none"
                placeholder={placeholder}
              />
              <div className="p-3 rounded-xl bg-forest/5 border border-forest/15 text-[11px] text-charcoal-700 leading-relaxed flex items-start gap-2">
                <Sparkles className="w-4 h-4 text-forest shrink-0 mt-0.5" />
                <span>
                  The <strong>Blast-Radius Detective</strong> uses Gemini entity extraction to dynamically parse your text, extract numbers/suppliers, and pass them directly to the PuLP solver.
                </span>
              </div>
              <button
                onClick={handleInjectFreeform}
                disabled={isSimulating}
                className="w-full py-3 rounded-xl bg-acid hover:bg-acid-hover text-charcoal-950 font-mono font-extrabold text-xs shadow-pill transition-all active:scale-95 flex items-center justify-center gap-2"
              >
                <Zap className="w-4 h-4 fill-current" />
                <span>Inject Prompt & Run 4-Agent Debate</span>
              </button>
            </div>
          )}

          {/* TAB 3: SLIDERS */}
          {activeTab === "SLIDERS" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[11px] font-mono font-bold text-charcoal-700 block mb-1">
                    Target Order
                  </label>
                  <select
                    value={targetOrder}
                    onChange={(e) => setTargetOrder(e.target.value)}
                    className="w-full p-2.5 rounded-xl border border-charcoal-900/15 text-xs font-mono bg-white"
                  >
                    {orders.map((o) => (
                      <option key={o.order_id} value={o.order_id}>
                        #{o.order_id} ({o.client}: {o.required_qty}u / ₹{((o.sla_penalty_inr ?? 0) / 100000).toFixed(1)}L SLA)
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <div className="flex items-center justify-between text-[11px] font-mono font-bold text-charcoal-700 mb-1">
                    <span>Material Shortfall</span>
                    <span className="text-coral">{shortfallUnits} Units</span>
                  </div>
                  <input
                    type="range"
                    min="25"
                    max="450"
                    step="25"
                    value={shortfallUnits}
                    onChange={(e) => setShortfallUnits(Number(e.target.value))}
                    className="w-full accent-coral"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="flex items-center justify-between text-[11px] font-mono font-bold text-charcoal-700 mb-1">
                    <span>Inbound Delay</span>
                    <span className="text-charcoal-900">{delayHours} Hours</span>
                  </div>
                  <input
                    type="range"
                    min="6"
                    max="96"
                    step="6"
                    value={delayHours}
                    onChange={(e) => setDelayHours(Number(e.target.value))}
                    className="w-full accent-charcoal-900"
                  />
                </div>

              </div>

              <div className="grid grid-cols-2 gap-4">
                {lines.map((l) => (
                  <div key={l.line_id}>
                    <div className="flex items-center justify-between text-[11px] font-mono font-bold text-charcoal-700 mb-1">
                      <span>{l.name}</span>
                      <span className="text-amber-600">{speedOf(l.line_id)}% Speed</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      step="5"
                      value={speedOf(l.line_id)}
                      onChange={(e) => setLineSpeeds((prev) => ({ ...prev, [l.line_id]: Number(e.target.value) }))}
                      className="w-full accent-amber-600"
                    />
                  </div>
                ))}
              </div>

              <button
                onClick={handleInjectSliders}
                disabled={isSimulating}
                className="w-full py-3 rounded-xl bg-acid hover:bg-acid-hover text-charcoal-950 font-mono font-extrabold text-xs shadow-pill transition-all active:scale-95 flex items-center justify-center gap-2 mt-4"
              >
                <Zap className="w-4 h-4 fill-current" />
                <span>Inject Custom Crisis ({shortfallUnits} Units / +{delayHours}h)</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
