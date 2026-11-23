"use client";

import React, { useRef, useState } from "react";
import { apiFetch } from "@/lib/session";
import { AccountControls } from "./AccountControls";
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

const IMPORT_KINDS = [
  { label: "Orders (erp-csv)", path: "/api/v1/ingest/erp-csv" },
  { label: "Stock summary", path: "/api/v1/ingest/stock-summary" },
  { label: "Open purchase orders", path: "/api/v1/ingest/open-purchase-orders" },
  { label: "Sales order lines", path: "/api/v1/ingest/sales-order-lines" },
] as const;
type ImportKind = (typeof IMPORT_KINDS)[number];
interface ImportResult {
  title: string;
  ok: boolean;
  summary: string;
  errors: string[];
  warnings: string[];
}

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
    factory,
    factoryName,
  } = useFactoryStore();

  const fileInputRef = useRef<HTMLInputElement>(null);

  const focus = focusOrder(orders, activeOrderId);
  const selectedPlan = playbooks.find((p) => p.id === selectedPlaybookId);

  const isCrisis = statusMode === "CRISIS";
  const isProtected = statusMode === "PROTECTED";

  const [importKind, setImportKind] = useState<ImportKind>(IMPORT_KINDS[0]);
  const [importMenuOpen, setImportMenuOpen] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const input = e.target;
    const file = input.files?.[0];
    if (!file) return;
    const text = await file.text();
    const API_BASE = typeof window !== "undefined" ? "" : (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000");
    try {
      const res = await apiFetch(`${API_BASE}${importKind.path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, csv_content: text }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setImportResult({
          title: `Import failed: ${file.name}`,
          ok: false,
          summary: String(data.detail || `HTTP ${res.status}`),
          errors: [],
          warnings: [],
        });
      } else {
        setImportResult({
          title: `${importKind.label}: ${file.name}`,
          ok: !(data.errors?.length),
          summary: `Imported ${data.imported_count ?? 0} row(s); ${data.errors?.length ?? 0} error(s), ${data.warnings?.length ?? 0} warning(s).`,
          errors: (data.errors ?? []).map((x: { line: number; error: string }) => `Line ${x.line}: ${x.error}`),
          warnings: (data.warnings ?? []).map((x: { line: number | null; warning: string }) =>
            x.line == null ? x.warning : `Line ${x.line}: ${x.warning}`),
        });
      }
    } catch {
      setImportResult({ title: "Import failed", ok: false, summary: "Could not reach the backend.", errors: [], warnings: [] });
    } finally {
      input.value = "";
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
              {factory?.name || factoryName || "Loading factory…"}
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

          <AccountControls />

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

          {/* Action: import CSV (pick the file type first) */}
          <div className="relative">
            <button
              onClick={() => setImportMenuOpen((o) => !o)}
              title="Import a Tally / Excel CSV"
              aria-haspopup="menu"
              aria-expanded={importMenuOpen}
              className="w-9 h-9 rounded-full bg-white/40 hover:bg-white/60 border border-white/50 text-charcoal-800 flex items-center justify-center transition-all active:scale-95"
            >
              <Upload className="w-4 h-4" />
            </button>
            {importMenuOpen && (
              <div role="menu" className="absolute right-0 mt-2 w-56 z-40 rounded-2xl bg-white border border-charcoal-900/10 shadow-xl p-1.5">
                {IMPORT_KINDS.map((k) => (
                  <button
                    key={k.path}
                    role="menuitem"
                    onClick={() => {
                      setImportKind(k);
                      setImportMenuOpen(false);
                      fileInputRef.current?.click();
                    }}
                    className="w-full text-left px-3 py-2 rounded-xl text-xs font-mono font-bold text-charcoal-900 hover:bg-acid/30"
                  >
                    {k.label}
                  </button>
                ))}
              </div>
            )}
          </div>

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
      {importResult && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-charcoal-950/50"
          onClick={() => setImportResult(null)}
        >
          <div
            role="dialog"
            aria-label="Import result"
            className="w-full max-w-lg max-h-[80vh] overflow-y-auto bg-white rounded-2xl p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className={`text-sm font-extrabold ${importResult.ok ? "text-emerald-700" : "text-coral"}`}>
              {importResult.title}
            </h3>
            <p className="text-xs font-mono text-charcoal-800 mt-1">{importResult.summary}</p>
            {importResult.errors.length > 0 && (
              <ul data-testid="import-errors" className="mt-3 space-y-1 text-[11px] font-mono text-coral">
                {importResult.errors.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            )}
            {importResult.warnings.length > 0 && (
              <ul data-testid="import-warnings" className="mt-3 space-y-1 text-[11px] font-mono text-amber-700">
                {importResult.warnings.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            )}
            <button
              onClick={() => setImportResult(null)}
              className="mt-4 px-4 py-2 rounded-full bg-charcoal-900 text-white text-xs font-mono font-bold"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </header>
  );
}
