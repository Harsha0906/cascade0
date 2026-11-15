"use client";

import React, { useState } from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import {
  CloudSun,
  Flame,
  MessageSquare,
  Radio,
  Send,
  Sparkles,
  Truck,
  Wrench,
} from "lucide-react";

export function WebhookBar() {
  const { simulateCrisis, isSimulating } = useFactoryStore();
  const [customInput, setCustomInput] = useState("");
  const [isPollingWeather, setIsPollingWeather] = useState(false);
  const [weatherData, setWeatherData] = useState<any>(null);

  const handleCustomSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customInput.trim()) return;
    simulateCrisis(undefined, customInput.trim());
  };

  const pollHighwayWeather = async () => {
    setIsPollingWeather(true);
    try {
      const API_BASE = typeof window !== "undefined" ? "" : (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000");
      const res = await fetch(`${API_BASE}/api/v1/ingest/live-highway-check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ corridor: "NH48 Chennai-Bengaluru", city: "Vellore" }),
      });
      if (res.ok) {
        const data = await res.json();
        setWeatherData(data);
      }
    } catch {
      // Fallback
    } finally {
      setIsPollingWeather(false);
    }
  };

  return (
    <div className="w-full px-4 sm:px-6 py-1.5">
      <div className="w-full max-w-[1880px] mx-auto island-card-static px-5 py-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
        {/* ─── Left: Rinesk Floating Scenario Pills ─────────────────────────── */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] font-mono font-bold text-charcoal-700 uppercase tracking-wider mr-1">
            Tactical Scenarios:
          </span>

          {/* Scenario 1 Pill */}
          <button
            onClick={() => simulateCrisis(1)}
            disabled={isSimulating}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/40 hover:bg-white/70 text-charcoal-900 border border-white/50 font-medium transition-all active:scale-95"
          >
            <Flame className="w-3.5 h-3.5 text-coral" />
            <span>Scenario 1: Compound Flood + Overheat</span>
          </button>

          {/* Scenario 2 Pill */}
          <button
            onClick={() => simulateCrisis(2)}
            disabled={isSimulating}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/40 hover:bg-white/70 text-charcoal-900 border border-white/50 font-medium transition-all active:scale-95"
          >
            <Wrench className="w-3.5 h-3.5 text-amber-700" />
            <span>Scenario 2: Line 3 Sensor Drift (25u)</span>
          </button>

          {/* Scenario 3 Pill */}
          <button
            onClick={() => simulateCrisis(3)}
            disabled={isSimulating}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/40 hover:bg-white/70 text-charcoal-900 border border-white/50 font-medium transition-all active:scale-95"
          >
            <Truck className="w-3.5 h-3.5 text-forest" />
            <span>Scenario 3: Chennai Collapse (350u)</span>
          </button>

          {/* Highway Weather Pill */}
          <button
            onClick={pollHighwayWeather}
            disabled={isPollingWeather}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/30 hover:bg-white/60 text-charcoal-800 border border-white/40 font-medium transition-all active:scale-95"
          >
            <CloudSun className="w-3.5 h-3.5 text-sky-700" />
            <span>
              {isPollingWeather
                ? "Checking NH48..."
                : weatherData
                ? `NH48: ${weatherData.weather} (${weatherData.temp_c}°C)`
                : "NH48 Corridor Check"}
            </span>
          </button>
        </div>

        {/* ─── Right: Custom WhatsApp Ingestion Input ──────────────────────── */}
        <form onSubmit={handleCustomSubmit} className="flex items-center gap-2 flex-1 sm:flex-initial min-w-[280px]">
          <div className="relative flex-1">
            <MessageSquare className="w-3.5 h-3.5 absolute left-3 top-2.5 text-charcoal-600" />
            <input
              type="text"
              value={customInput}
              onChange={(e) => setCustomInput(e.target.value)}
              placeholder="Driver alert: 'NH48 waterlogging, 48h delay'..."
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
