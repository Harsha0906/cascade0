"use client";

import React, { useState } from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import {
  Flame,
  MessageSquare,
  Radio,
  Send,
  Sparkles,
} from "lucide-react";

export function WebhookBar() {
  const { simulateCrisis, isSimulating, scenarios, scenariosError } = useFactoryStore();
  const [customInput, setCustomInput] = useState("");

  const handleCustomSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customInput.trim()) return;
    simulateCrisis(undefined, customInput.trim());
  };

  return (
    <div className="w-full px-4 sm:px-6 py-1.5">
      <div className="w-full max-w-[1880px] mx-auto island-card-static px-5 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
        {/* ─── Left: Rinesk Floating Scenario Pills ─────────────────────────── */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] font-mono font-bold text-charcoal-700 uppercase tracking-wider mr-1">
            Tactical Scenarios:
          </span>

          {scenariosError && (
            <span className="text-[11px] font-mono text-coral">{scenariosError}</span>
          )}
          {scenarios.map((sc) => (
            <button
              key={sc.scenario_id}
              onClick={() => simulateCrisis(sc.scenario_id)}
              disabled={isSimulating}
              title={sc.summary}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/40 hover:bg-white/70 text-charcoal-900 border border-white/50 font-medium transition-all active:scale-95"
            >
              <Flame className="w-3.5 h-3.5 text-coral" />
              <span>{sc.title}</span>
            </button>
          ))}

        </div>

        {/* ─── Right: Custom WhatsApp Ingestion Input ──────────────────────── */}
        <form onSubmit={handleCustomSubmit} className="flex items-center gap-2 flex-1 sm:flex-initial min-w-[280px]">
          <div className="relative flex-1">
            <MessageSquare className="w-3.5 h-3.5 absolute left-3 top-2.5 text-charcoal-600" />
            <input
              type="text"
              value={customInput}
              onChange={(e) => setCustomInput(e.target.value)}
              placeholder={scenarios[0]?.raw_message ?? "Type a disruption alert..."}
              className="w-full pl-8 pr-3 py-1.5 rounded-full bg-white/50 border border-white/60 text-xs text-charcoal-900 placeholder:text-charcoal-600 focus:outline-none focus:bg-white/80 focus:border-charcoal-800 transition-all font-sans"
            />
          </div>
          <button
            type="submit"
            disabled={!customInput.trim() || isSimulating}
            className="px-3.5 py-1.5 rounded-full bg-charcoal-900 hover:bg-charcoal-800 text-white font-medium text-xs flex items-center gap-1.5 transition-all disabled:opacity-40 active:scale-95 shrink-0"
          >
            <Send className="w-3 h-3" />
            <span>Ingest</span>
          </button>
        </form>
      </div>
    </div>
  );
}
