"use client";

import React, { useRef } from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import { focusOrder } from "@/lib/twinGraph";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  FileText,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Upload,
  Zap,
} from "lucide-react";

export function TopKpiBar() {
  const {
    statusMode,
    isSimulating,
    simulateCrisis,
    resetFactory,
    orders,
    playbooks,
    selectedPlaybookId,
    executionReceipt,
    openReceiptModal,
    dashboardViewMode,
    setDashboardViewMode,
    openCustomCrisisModal,
    activeOrderId,
  } = useFactoryStore();

  const fileInputRef = useRef<HTMLInputElement>(null);

  const focus = focusOrder(orders, activeOrderId);
  const selectedPlan = playbooks.find((p) => p.id === selectedPlaybookId);

  const isCrisis = statusMode === "CRISIS";
  const isProtected = statusMode === "PROTECTED";

  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const API_BASE = typeof window !== "undefined" ? "" : (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000");
    try {
      const res = await fetch(`${API_BASE}/api/v1/ingest/erp-csv`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, csv_content: text }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        alert(`⚠️ Import failed: ${data.detail || `HTTP ${res.status}`}`);
      } else if (data.errors?.length) {
        alert(`⚠️ Imported ${data.imported_count} orders; ${data.errors.length} rows rejected (first: line ${data.errors[0].line} — ${data.errors[0].error}).`);
      } else {
        alert(`✅ Imported ${data.imported_count} orders from "${file.name}".`);
      }
    } catch {
      alert("⚠️ Could not reach the backend.");
    } finally {
      e.target.value = "";
    }
  };

  return (
    <header className="w-full px-4 sm:px-6 pt-4 pb-2">
      <div className="w-full max-w-[1880px] mx-auto island-card-static px-5 sm:px-6 py-3.5 flex flex-wrap items-center justify-between gap-4">
        {/* ─── Left: Brand Logo & Unit Title ───────────────────────────────── */}
        <div className="flex items-center gap-3.5">
          {/* Rinesk Yellow Pill Logo */}
          <div className="w-10 h-10 rounded-2xl bg-acid flex items-center justify-center shadow-pill shrink-0">
            <Zap className="w-5 h-5 text-charcoal-900 fill-charcoal-900" />
          </div>

          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-extrabold text-charcoal-900 tracking-tight">
                CASCADE<span className="text-forest font-medium">ZERO</span>
              </h1>
              <span className="text-[11px] font-mono font-bold px-2 py-0.5 rounded-full bg-white/40 text-charcoal-800 border border-white/60">
                v2.5
              </span>
            </div>
            <p className="text-xs text-charcoal-700 font-medium tracking-tight hidden sm:block">
              Apex Volt EV Battery Plant • Bengaluru Unit-2
            </p>
          </div>

          {/* Dynamic Status Capsule */}
          <div
            className={`hidden md:flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-mono font-bold transition-all ml-2 ${
              isCrisis
                ? "bg-coral text-white shadow-pill-coral animate-pulse"
                : isProtected
                ? "bg-emerald-600 text-white shadow-[0_4px_16px_rgba(22,110,74,0.3)]"
                : "bg-white/50 text-charcoal-900 border border-white/60"
            }`}
          >
            {isCrisis ? (
              <AlertTriangle className="w-3.5 h-3.5" />
            ) : isProtected ? (
              <ShieldCheck className="w-3.5 h-3.5" />
            ) : (
              <Activity className="w-3.5 h-3.5 text-forest" />
            )}
            <span>
              {isCrisis
                ? "CRISIS: COMPOUND DISRUPTION"
                : isProtected
                ? `APPROVED: ${selectedPlan?.id ?? "PLAN"} — DRAFTS READY`
                : "STATUS: NOMINAL OPERATIONS"}
            </span>
          </div>
        </div>

        {/* ─── Center/Right: View Switcher & Action Pills ───────────────────── */}
        <div className="flex items-center gap-3 flex-wrap">
          {/* Executive vs Twin Mode Switcher */}
          <div className="flex items-center p-1 rounded-2xl bg-white/40 border border-white/60 shadow-sm">
            <button
              onClick={() => setDashboardViewMode("EXECUTIVE")}
              className={`px-3 py-1.5 rounded-xl text-xs font-mono font-bold transition-all ${
                dashboardViewMode === "EXECUTIVE"
                  ? "bg-charcoal-900 text-white shadow-sm"
                  : "text-charcoal-700 hover:text-charcoal-950"
              }`}
            >
              👔 Executive View
            </button>
            <button
              onClick={() => setDashboardViewMode("TWIN")}
              className={`px-3 py-1.5 rounded-xl text-xs font-mono font-bold transition-all ${
                dashboardViewMode === "TWIN"
                  ? "bg-charcoal-900 text-white shadow-sm"
                  : "text-charcoal-700 hover:text-charcoal-950"
              }`}
            >
              🏭 2.5D Twin Studio
            </button>
          </div>

          {/* Active Contract Risk Pill */}
          <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/40 border border-white/50 text-xs font-mono">
            <span className="text-charcoal-700 uppercase tracking-wider text-[11px]">SLA Liability:</span>
            <span
              className={`font-bold tabular-nums ${
                isCrisis
                  ? "text-coral font-extrabold text-sm"
                  : isProtected
                  ? "text-emerald-700 font-extrabold"
                  : "text-charcoal-900"
              }`}
            >
              {isCrisis
                ? `-₹${(focus?.sla_penalty_inr ?? 0).toLocaleString("en-IN")}`
                : isProtected
                ? selectedPlan
                  ? `Plan approved (₹${(selectedPlan.total_mitigation_cost_inr / 100000).toFixed(2)}L)`
                  : "Plan approved"
                : "₹0 Exposure"}
            </span>
          </div>

          {/* Custom Scenario Studio Button */}
          <button
            onClick={openCustomCrisisModal}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-full text-xs font-mono font-bold bg-white text-charcoal-900 hover:bg-white/90 border border-white/80 shadow-sm transition-all active:scale-95"
            title="Inject any custom or freeform crisis"
          >
            <Sparkles className="w-3.5 h-3.5 text-forest" />
            <span>Crisis Studio</span>
          </button>

          {/* View Draft PO Button (When Approved) */}
          {(isProtected || executionReceipt) && (
            <button
              onClick={openReceiptModal}
              className="flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-bold bg-white text-charcoal-900 hover:bg-white/90 border border-white/80 shadow-island transition-all active:scale-95"
            >
              <FileText className="w-3.5 h-3.5 text-emerald-600" />
              <span>View Draft PO</span>
            </button>
          )}

          {/* Hero Action: Simulate Crisis (Acid Lime Button in Normal, Coral in Crisis) */}
          <button
            onClick={() => simulateCrisis(1)}
            disabled={isSimulating}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-full font-bold text-xs font-mono transition-all active:scale-95 ${
              isSimulating
                ? "bg-white/40 text-charcoal-600 cursor-not-allowed"
                : isCrisis
                ? "bg-coral text-white hover:bg-coral-hover shadow-pill-coral"
                : "bg-acid hover:bg-acid-hover text-charcoal-950 shadow-pill"
            }`}
          >
            {isSimulating ? (
              <Sparkles className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Zap className="w-3.5 h-3.5 fill-current" />
            )}
            <span>{isSimulating ? "Solving PuLP..." : isCrisis ? "Crisis Active" : "Simulate Crisis"}</span>
          </button>

          {/* Hidden File Input for CSV */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xml"
            onChange={handleCsvUpload}
            className="hidden"
          />

          {/* Action: Upload ERP CSV Circular Button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            title="Upload Legacy Tally / Excel ERP CSV"
            className="w-9 h-9 rounded-full bg-white/40 hover:bg-white/60 border border-white/50 text-charcoal-800 flex items-center justify-center transition-all active:scale-95"
          >
            <Upload className="w-4 h-4" />
          </button>

          {/* Action: Reset Demo Circular Button */}
          <button
            onClick={resetFactory}
            title="Reset Factory to Nominal State"
            className="w-9 h-9 rounded-full bg-white/40 hover:bg-white/60 border border-white/50 text-charcoal-800 flex items-center justify-center transition-all active:scale-95"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
