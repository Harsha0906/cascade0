"use client";

import React from "react";
import {
  ReactFlow,
  Background,
  Controls,
  BackgroundVariant,
} from "@xyflow/react";
import { useFactoryStore } from "@/store/useFactoryStore";
import { nodeTypes } from "./CustomNodes";
import { X, Database, History, Cpu, AlertTriangle } from "lucide-react";

export function FlowCanvas() {
  const {
    nodes,
    edges,
    selectedNodeData,
    isInspectionDrawerOpen,
    closeInspectionDrawer,
    vendorHistory,
    factoryError,
  } = useFactoryStore();

  // Find relevant vendor history if node is a supplier
  const relatedHistory = selectedNodeData?.supplierId
    ? vendorHistory.find((vh) => vh.supplier_id === selectedNodeData.supplierId)
    : undefined;

  if (factoryError) {
    return (
      <div className="relative w-full h-[520px] rounded-[32px] overflow-hidden island-card-static border border-white/50 shadow-island flex items-center justify-center">
        <div className="island-card rounded-[24px] p-6 max-w-md text-center border !border-coral !bg-coral/15">
          <AlertTriangle className="w-6 h-6 text-coral mx-auto mb-2" />
          <h3 className="font-bold text-sm text-charcoal-900 mb-1">Digital twin unavailable</h3>
          <p className="text-xs text-charcoal-800 font-mono break-words">{factoryError}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative w-full h-[520px] rounded-[32px] overflow-hidden island-card-static border border-white/50 shadow-island">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.5}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1.5}
          color="rgba(21, 32, 23, 0.22)"
        />
        <Controls
          className="!bg-white/60 !backdrop-blur-xl !border-white/60 !rounded-2xl !text-charcoal-900 !shadow-island"
          showInteractive={false}
        />
      </ReactFlow>

      {/* ─── Rinesk Frosted Glass SQL Telemetry Drawer ───────────────────────── */}
      {isInspectionDrawerOpen && selectedNodeData && (
        <div className="absolute top-0 right-0 h-full w-96 bg-sage-100/90 backdrop-blur-3xl border-l border-white/60 z-20 p-5 overflow-y-auto animate-in slide-in-from-right duration-300 shadow-2xl">
          <div className="flex items-center justify-between pb-3.5 border-b border-charcoal-900/10">
            <div className="flex items-center gap-2 text-charcoal-900">
              <div className="p-1.5 rounded-xl bg-charcoal-900 text-acid">
                <Database className="w-4 h-4" />
              </div>
              <div>
                <h3 className="font-bold text-sm tracking-tight">Supabase Telemetry</h3>
                <p className="text-[10px] text-charcoal-600 font-mono">Live Node Inspection</p>
              </div>
            </div>
            <button
              onClick={closeInspectionDrawer}
              className="p-1.5 rounded-full text-charcoal-700 hover:text-charcoal-950 hover:bg-white/60 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="mt-4 space-y-4 text-xs font-mono">
            <div>
              <span className="text-[10px] font-bold text-charcoal-600 uppercase tracking-wider block mb-1">
                Selected Entity
              </span>
              <p className="text-charcoal-950 font-bold text-sm">
                {selectedNodeData.name || selectedNodeData.supplierId || selectedNodeData.lineId || selectedNodeData.orderId || selectedNodeData.type}
              </p>
            </div>

            {/* Live SQL Attributes Table */}
            <div className="bg-white/40 rounded-2xl p-3.5 border border-white/60 space-y-2 shadow-sm">
              <span className="text-[10px] font-bold text-charcoal-700 uppercase tracking-wider flex items-center gap-1.5">
                <Cpu className="w-3.5 h-3.5 text-forest" /> Live SQL Attributes
              </span>
              {Object.entries(selectedNodeData)
                .filter(([k]) => !["isCrisis", "isProtected"].includes(k))
                .slice(0, 7)
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between items-center text-[11px] py-1 border-b border-charcoal-900/5">
                    <span className="text-charcoal-600 font-medium">{k}:</span>
                    <span className="text-charcoal-900 font-bold truncate max-w-[180px]">
                      {String(v)}
                    </span>
                  </div>
                ))}
            </div>

            {/* Episodic Memory (vendor_history table) */}
            {relatedHistory && (
              <div className="bg-white/40 rounded-2xl p-3.5 border border-white/60 space-y-2 shadow-sm">
                <span className="text-[10px] font-bold text-charcoal-700 uppercase tracking-wider flex items-center gap-1.5">
                  <History className="w-3.5 h-3.5 text-amber-700" /> Episodic Memory (`vendor_history`)
                </span>
                <div className="flex justify-between text-[11px]">
                  <span className="text-charcoal-600">Past Orders:</span>
                  <span className="text-charcoal-900 font-bold">{relatedHistory.past_orders_count} orders</span>
                </div>
                <div className="flex justify-between text-[11px]">
                  <span className="text-charcoal-600">On-Time Reliability:</span>
                  <span className="text-forest font-extrabold">
                    {relatedHistory.reliability_score_pct}%
                  </span>
                </div>
                <div className="flex justify-between text-[11px]">
                  <span className="text-charcoal-600">Quality Rejection Rate:</span>
                  <span className="text-charcoal-900 font-semibold">{relatedHistory.quality_rejection_rate_pct}%</span>
                </div>
                <div className="pt-2 border-t border-charcoal-900/10">
                  <span className="text-[10px] font-bold text-charcoal-600 block mb-0.5">Historical Incident Note:</span>
                  <p className="text-[11px] text-charcoal-800 italic leading-snug">
                    &ldquo;{relatedHistory.last_incident_note}&rdquo;
                  </p>
                </div>
              </div>
            )}

            <div className="pt-1">
              <span className="text-[10px] font-bold text-charcoal-600 block mb-1 uppercase tracking-wider">
                Raw DB Mirror
              </span>
              <pre className="text-[10px] p-3 rounded-2xl bg-charcoal-950 text-acid font-mono overflow-x-auto max-h-36 border border-white/10 shadow-inner">
                {JSON.stringify(selectedNodeData, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}