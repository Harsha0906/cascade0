"use client";

import React, { useEffect } from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import { TopKpiBar } from "@/components/TopKpiBar";
import { WebhookBar } from "@/components/WebhookBar";
import { AgentPipelineStrip } from "@/components/AgentPipelineStrip";
import { FlowCanvas } from "@/components/FlowCanvas";
import { AgentStream } from "@/components/AgentStream";
import { PlaybookSidebar } from "@/components/PlaybookSidebar";
import { ExecutionModal } from "@/components/ExecutionModal";
import { ExecutiveStoryView } from "@/components/ExecutiveStoryView";
import { CrisisSandboxModal } from "@/components/CrisisSandboxModal";

export default function CommandCenterPage() {
  const {
    fetchInitialState,
    initRealtimeSubscriptions,
    isReceiptModalOpen,
    closeReceiptModal,
    dashboardViewMode,
  } = useFactoryStore();

  useEffect(() => {
    fetchInitialState();
    const unsubscribe = initRealtimeSubscriptions();
    return () => {
      unsubscribe();
    };
  }, [fetchInitialState, initRealtimeSubscriptions]);

  return (
    <main className="min-h-screen flex flex-col text-charcoal-900 selection:bg-acid selection:text-charcoal-950">
      {/* 1. Executive Top KPI Header */}
      <TopKpiBar />

      {/* 2. SME Multi-Channel Ingestion Bar */}
      <WebhookBar />

      {/* 3. 4-Step Agent Pipeline Status Strip */}
      <AgentPipelineStrip />

      {/* 4. Conditional View: Executive Story View vs 2.5D Digital Twin Studio */}
      {dashboardViewMode === "EXECUTIVE" ? (
        <ExecutiveStoryView />
      ) : (
        /* Core Command Center Grid */
        <div className="flex-1 w-full max-w-[1880px] mx-auto p-4 sm:p-6 flex flex-col lg:flex-row gap-5 items-start animate-in fade-in duration-300">
          {/* ─── Left Column (Canvas + Agent Terminal) ────────────────────────── */}
          <div className="flex-1 w-full flex flex-col gap-4">
            {/* Canvas Sub-Header & Legend */}
            <div className="flex flex-wrap items-center justify-between text-xs font-mono text-charcoal-700 px-2 gap-2">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-forest animate-pulse" />
                <span className="text-charcoal-950 font-bold tracking-tight">
                  2.5D Digital Twin & Causal Blast-Radius Flow
                </span>
                <span className="text-charcoal-400 hidden md:inline">•</span>
                <span className="hidden md:inline text-charcoal-600 font-medium">
                  Interactive Canvas (Drag, Zoom, Click Node to Inspect Live Postgres Record)
                </span>
              </div>

              <div className="flex items-center gap-3.5 text-[11px]">
                <span className="flex items-center gap-1.5 font-medium">
                  <span className="w-2.5 h-2.5 rounded-full bg-forest inline-block shadow-sm" />
                  <span className="text-charcoal-800">SLA Protected / On-Track</span>
                </span>
                <span className="flex items-center gap-1.5 font-medium">
                  <span className="w-2.5 h-2.5 rounded-full bg-coral inline-block shadow-pill-coral" />
                  <span className="text-charcoal-800">Thermal / Highway Delay</span>
                </span>
                <span className="flex items-center gap-1.5 font-medium">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-400 inline-block shadow-sm" />
                  <span className="text-charcoal-800">Standby Regional Supplier</span>
                </span>
              </div>
            </div>

            {/* React Flow 2.5D Digital Twin Canvas */}
            <FlowCanvas />

            {/* Bottom Live Agent Terminal Feed */}
            <AgentStream />
          </div>

          {/* ─── Right Column (3 Audited Playbooks Sidebar) ───────────────────── */}
          <div className="w-full lg:w-[410px] xl:w-[450px] shrink-0">
            <PlaybookSidebar />
          </div>
        </div>
      )}

      {/* 5. Custom Crisis Scenario Studio Modal */}
      <CrisisSandboxModal />

      {/* 6. HITL Approval & Draft PO / Notices Modal */}
      <ExecutionModal
        isOpen={isReceiptModalOpen}
        onClose={closeReceiptModal}
      />
    </main>
  );
}