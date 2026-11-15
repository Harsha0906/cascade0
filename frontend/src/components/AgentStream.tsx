"use client";

import React, { useEffect, useRef, useState } from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import { Terminal, Copy, Check, Sparkles, Cpu, Clock } from "lucide-react";

export function AgentStream() {
  const { agentLogs, isSimulating, solveDurationMs, rebuttalOccurred } =
    useFactoryStore();

  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom as new logs stream in
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [agentLogs]);

  const handleCopyLogs = () => {
    const text = agentLogs
      .map(
        (l) =>
          `[${l.step_order}] ${l.agent_name} (${l.tool_called})\n${l.message}\n`
      )
      .join("\n");
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getBadgeStyle = (badgeColor: string) => {
    switch (badgeColor.toLowerCase()) {
      case "amber":
        return "bg-amber-100 border border-amber-300 text-amber-950 font-bold";
      case "rose":
        return "bg-coral/20 border border-coral text-coral-600 font-extrabold";
      case "cyan":
        return "bg-sky-100 border border-sky-300 text-sky-950 font-bold";
      case "emerald":
        return "bg-forest/15 border border-forest/40 text-forest-deep font-bold";
      default:
        return "bg-white/60 border border-white/80 text-charcoal-800 font-bold";
    }
  };

  return (
    <div className="w-full h-[270px] rounded-[32px] island-card-static border border-white/50 flex flex-col overflow-hidden shadow-island">
      {/* ─── Header ────────────────────────────────────────────────────────── */}
      <div className="px-5 py-3 bg-white/30 border-b border-charcoal-900/10 flex items-center justify-between text-xs font-mono">
        <div className="flex items-center gap-2.5 text-charcoal-900">
          <div className="p-1.5 rounded-xl bg-charcoal-900 text-acid">
            <Terminal className="w-3.5 h-3.5" />
          </div>
          <span className="font-extrabold text-charcoal-950 tracking-tight">Live Multi-Agent Debate & LP Audit</span>
          <span className="text-[10px] text-charcoal-400">•</span>
          <span className="text-[11px] text-charcoal-600 font-medium">
            {isSimulating ? (
              <span className="text-amber-700 font-bold animate-pulse flex items-center gap-1">
                <Sparkles className="w-3 h-3 text-amber-600" /> LangGraph Active...
              </span>
            ) : agentLogs.length > 0 ? (
              `Supabase Realtime Stream (${agentLogs.length} events logged)`
            ) : (
              "Standing by for disruption trigger..."
            )}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {solveDurationMs > 0 && (
            <span className="text-[11px] text-charcoal-700 font-medium flex items-center gap-1">
              <Clock className="w-3.5 h-3.5 text-forest" />
              <span>Solved in:</span>
              <span className="text-forest font-extrabold tabular-nums">
                {solveDurationMs}ms
              </span>
            </span>
          )}

          {rebuttalOccurred && (
            <span className="px-2.5 py-0.5 rounded-full bg-coral text-white text-[10px] font-extrabold shadow-pill-coral animate-pulse">
              ⚡ REBUTTAL ENGAGED
            </span>
          )}

          <button
            onClick={handleCopyLogs}
            disabled={agentLogs.length === 0}
            className="flex items-center gap-1 px-3 py-1 rounded-full text-[11px] bg-white/60 hover:bg-white/90 border border-white/80 text-charcoal-900 font-bold transition-all shadow-sm disabled:opacity-40"
          >
            {copied ? <Check className="w-3 h-3 text-forest" /> : <Copy className="w-3 h-3" />}
            <span>{copied ? "Copied" : "Copy Log"}</span>
          </button>
        </div>
      </div>

      {/* ─── Scrollable Logs Feed ───────────────────────────────────────────── */}
      <div
        ref={scrollRef}
        className="flex-1 p-4 overflow-y-auto space-y-2.5 font-mono text-xs select-text"
      >
        {agentLogs.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-charcoal-600 text-center gap-2">
            <Cpu className="w-6 h-6 text-charcoal-500 animate-pulse" />
            <p className="text-xs font-semibold text-charcoal-800">No active disruption detected. Plant running at 100% nominal speed.</p>
            <p className="text-[11px] text-charcoal-600">
              Click &quot;Simulate Crisis&quot; above to watch the 4 AI agents debate recovery in realtime.
            </p>
          </div>
        ) : (
          agentLogs.map((log, idx) => (
            <div
              key={log.id || idx}
              className="p-3 rounded-2xl bg-white/40 border border-white/60 shadow-sm transition-colors hover:bg-white/50"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-charcoal-500 font-semibold">[{log.step_order}]</span>
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-[10px] uppercase ${getBadgeStyle(
                      log.badge_color
                    )}`}
                  >
                    {log.agent_name}
                  </span>
                  <span className="text-[11px] text-charcoal-700 font-medium">• {log.agent_role}</span>
                </div>

                {log.tool_called && (
                  <span className="px-2 py-0.5 rounded-full bg-white/60 border border-white/80 text-charcoal-800 text-[10px] font-bold">
                    ⚡ Tool: {log.tool_called}
                  </span>
                )}
              </div>

              {log.tool_output_summary && (
                <div className="mb-1 text-[11px] text-charcoal-800 pl-3 border-l-2 border-forest">
                  <span className="text-[10px] font-bold text-charcoal-600 uppercase">Tool Output: </span>
                  <span className="text-charcoal-900 font-semibold">{log.tool_output_summary}</span>
                </div>
              )}

              <p className="text-[11.5px] text-charcoal-950 font-medium leading-relaxed pl-3 border-l-2 border-charcoal-900/20">
                {log.message}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}