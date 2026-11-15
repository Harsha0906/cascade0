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
    isSimulating,
  } = useFactoryStore();

  const [activeTab, setActiveTab] = useState<"TEMPLATES" | "FREEFORM" | "SLIDERS">("TEMPLATES");

  // Form states
  const [freeformPrompt, setFreeformPrompt] = useState(
    "Driver Ramesh reporting flood on NH48. 48h delay on EV-402, Line 2 running at 50% thermal throttle."
  );

  const [targetOrder, setTargetOrder] = useState("EV-402");
  const [shortfallUnits, setShortfallUnits] = useState(150);
  const [delayHours, setDelayHours] = useState(48);
  const [line2Speed, setLine2Speed] = useState(50);
  const [line2Temp, setLine2Temp] = useState(89);

  if (!isCustomCrisisModalOpen) return null;

  const handleInjectTemplate = async (templateText: string) => {
    closeCustomCrisisModal();
    await simulateCrisis(undefined, templateText);
  };

  const handleInjectFreeform = async () => {
    if (!freeformPrompt.trim()) return;
    closeCustomCrisisModal();
    await simulateCrisis(undefined, freeformPrompt);
  };

  const handleInjectSliders = async () => {
    const message = `Custom plant incident: ${shortfallUnits} units shortfall on order #${targetOrder}. Inbound transit delayed by ${delayHours} hours. Line 2 operating at ${line2Speed}% speed at ${line2Temp}°C.`;
    closeCustomCrisisModal();
    await simulateCrisis(undefined, message);
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
              <button
                onClick={() =>
                  handleInjectTemplate(
                    "Driver Ramesh reporting flood on NH48 near Vellore. 48h delay on EV-402, Line 2 running at 50% thermal throttle."
                  )
                }
                className="p-4 rounded-2xl border border-charcoal-900/10 bg-white hover:bg-acid/15 hover:border-acid text-left transition-all group flex items-start justify-between gap-4"
              >
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-xl bg-coral/15 text-coral flex items-center justify-center shrink-0 mt-0.5">
                    <Truck className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-xs font-extrabold text-charcoal-900 group-hover:text-charcoal-950">
                      Scenario A: NH48 Highway Inundation + Machine Overheat
                    </h4>
                    <p className="text-[11px] text-charcoal-600 mt-0.5">
                      150 unit deficit on Ather-Grid #EV-402 (+48h delay). Solves for Plan B regional SME re-routing (Peenya).
                    </p>
                    <div className="flex items-center gap-2 mt-2 text-[10px] font-mono text-charcoal-500">
                      <span className="px-2 py-0.5 rounded bg-charcoal-900/5">SLA Risk: ₹25.0L</span>
                      <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">Expected ROI: 13.9x</span>
                    </div>
                  </div>
                </div>
                <ArrowRight className="w-4 h-4 text-charcoal-400 group-hover:translate-x-1 transition-all shrink-0 mt-2" />
              </button>

              <button
                onClick={() =>
                  handleInjectTemplate(
                    "Severe Cyclone Alert: NH48 Chennai route completely submerged for 72h. Shortfall 350 units on EV-402. Line 2 motor seized."
                  )
                }
                className="p-4 rounded-2xl border border-charcoal-900/10 bg-white hover:bg-acid/15 hover:border-acid text-left transition-all group flex items-start justify-between gap-4"
              >
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-xl bg-amber-500/15 text-amber-600 flex items-center justify-center shrink-0 mt-0.5">
                    <Flame className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-xs font-extrabold text-charcoal-900 group-hover:text-charcoal-950">
                      Scenario B: Catastrophic 350-Unit Shortfall (Triggers Agent Rebuttal)
                    </h4>
                    <p className="text-[11px] text-charcoal-600 mt-0.5">
                      High volume deficit exceeding single vendor capacity. Forces Ops Hawk & CFO Watchdog into cyclic debate before solving.
                    </p>
                    <div className="flex items-center gap-2 mt-2 text-[10px] font-mono text-charcoal-500">
                      <span className="px-2 py-0.5 rounded bg-charcoal-900/5">Rebuttal Cycle: ACTIVE</span>
                      <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-800">Multi-Vendor Split</span>
                    </div>
                  </div>
                </div>
                <ArrowRight className="w-4 h-4 text-charcoal-400 group-hover:translate-x-1 transition-all shrink-0 mt-2" />
              </button>

              <button
                onClick={() =>
                  handleInjectTemplate(
                    "Transport strike at Attibele toll gate. 180 casings delayed 36h for Deccan E-Fleet order #EV-405. Line 1 throttled to 60%."
                  )
                }
                className="p-4 rounded-2xl border border-charcoal-900/10 bg-white hover:bg-acid/15 hover:border-acid text-left transition-all group flex items-start justify-between gap-4"
              >
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-xl bg-sky-500/15 text-sky-600 flex items-center justify-center shrink-0 mt-0.5">
                    <Wrench className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-xs font-extrabold text-charcoal-900 group-hover:text-charcoal-950">
                      Scenario C: Border Toll Bottleneck on Deccan Logistics #EV-405
                    </h4>
                    <p className="text-[11px] text-charcoal-600 mt-0.5">
                      Tests dynamic order shifting — preserves secondary client SLA of ₹10.0L without disrupting Line 3 parallel buffer.
                    </p>
                    <div className="flex items-center gap-2 mt-2 text-[10px] font-mono text-charcoal-500">
                      <span className="px-2 py-0.5 rounded bg-charcoal-900/5">SLA Risk: ₹10.0L</span>
                      <span className="px-2 py-0.5 rounded bg-sky-100 text-sky-800">Target: #EV-405</span>
                    </div>
                  </div>
                </div>
                <ArrowRight className="w-4 h-4 text-charcoal-400 group-hover:translate-x-1 transition-all shrink-0 mt-2" />
              </button>
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
                placeholder="e.g. Truck breakdown near Krishnagiri, 120 battery casings short on EV-402, Line 2 running at 50%..."
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
                    <option value="EV-402">#EV-402 (Ather-Grid: 500u / ₹25L SLA)</option>
                    <option value="EV-405">#EV-405 (Deccan E-Fleet: 300u / ₹10L SLA)</option>
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

                <div>
                  <div className="flex items-center justify-between text-[11px] font-mono font-bold text-charcoal-700 mb-1">
                    <span>Line 2 Throttling</span>
                    <span className="text-amber-600">{line2Speed}% Speed ({line2Temp}°C)</span>
                  </div>
                  <input
                    type="range"
                    min="20"
                    max="100"
                    step="10"
                    value={line2Speed}
                    onChange={(e) => {
                      const speed = Number(e.target.value);
                      setLine2Speed(speed);
                      setLine2Temp(Math.round(95 - (speed / 100) * 35));
                    }}
                    className="w-full accent-amber-600"
                  />
                </div>
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
