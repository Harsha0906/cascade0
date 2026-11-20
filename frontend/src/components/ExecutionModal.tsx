"use client";

import React, { useState } from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import {
  Check,
  Copy,
  Download,
  FileCode,
  MessageSquare,
  ShieldCheck,
  X,
} from "lucide-react";

export function ExecutionModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const { executionReceipt, playbooks, productionLines } = useFactoryStore();
  const [activeTab, setActiveTab] = useState<"tally" | "whatsapp" | "sla">("tally");
  const [copiedType, setCopiedType] = useState<string | null>(null);

  // Only real, server-generated receipts are shown — no canned fallback.
  if (!isOpen || !executionReceipt) return null;
  const receipt = executionReceipt;
  const receiptPlaybook = playbooks.find((p) => p.id === receipt.playbook_id);
  const overtimeLineNames = Object.entries(receiptPlaybook?.overtime_line_hours ?? {})
    .filter(([, hours]) => hours > 0)
    .map(([lineId]) => productionLines.find((l) => l.line_id === lineId)?.name ?? lineId);
  const shiftNoticeHeading = overtimeLineNames.length
    ? `Draft shift notice for ${overtimeLineNames.join(", ")} supervisors (copy and send)`
    : "No overtime scheduled";

  const downloadXml = () => {
    const blob = new Blob([receipt.tally_xml_payload], { type: "application/xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${receipt.po_number || "PO-CASCADEZERO"}.xml`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(receipt.tally_json_payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${receipt.po_number || "PO-CASCADEZERO"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copyText = (text: string, type: string) => {
    navigator.clipboard.writeText(text);
    setCopiedType(type);
    setTimeout(() => setCopiedType(null), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-charcoal-950/60 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-3xl rounded-[36px] bg-sage-100/95 backdrop-blur-3xl border border-white/80 p-6 flex flex-col gap-4 shadow-2xl">
        {/* ─── Header ──────────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between pb-3.5 border-b border-charcoal-900/10">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-2xl bg-charcoal-900 text-acid shadow-sm">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-extrabold text-charcoal-900 tracking-tight flex items-center gap-2">
                <span>HITL ERP Execution Ledger</span>
                <span className="text-[11px] font-mono px-2.5 py-0.5 rounded-full bg-acid text-charcoal-950 border border-acid shadow-pill font-extrabold">
                  {receipt.po_number}
                </span>
              </h2>
              <p className="text-xs text-charcoal-600 font-medium">
                Approval recorded • Drafts below are NOT sent — review, then send through your normal channels
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-full text-charcoal-600 hover:text-charcoal-950 hover:bg-white/60 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* ─── Rinesk Rounded Pill Tabs ───────────────────────────────────────── */}
        <div className="flex rounded-full bg-white/40 p-1 border border-white/60 font-mono text-xs shadow-inner">
          <button
            onClick={() => setActiveTab("tally")}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-full transition-all ${
              activeTab === "tally"
                ? "bg-white text-charcoal-900 font-extrabold shadow-sm border border-white/80"
                : "text-charcoal-700 hover:text-charcoal-950 font-medium"
            }`}
          >
            <FileCode className="w-3.5 h-3.5 text-forest" />
            <span>1. Tally Prime PO (XML/JSON)</span>
          </button>

          <button
            onClick={() => setActiveTab("whatsapp")}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-full transition-all ${
              activeTab === "whatsapp"
                ? "bg-white text-charcoal-900 font-extrabold shadow-sm border border-white/80"
                : "text-charcoal-700 hover:text-charcoal-950 font-medium"
            }`}
          >
            <MessageSquare className="w-3.5 h-3.5 text-forest" />
            <span>2. WhatsApp Shift Broadcast</span>
          </button>

          <button
            onClick={() => setActiveTab("sla")}
            className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-full transition-all ${
              activeTab === "sla"
                ? "bg-white text-charcoal-900 font-extrabold shadow-sm border border-white/80"
                : "text-charcoal-700 hover:text-charcoal-950 font-medium"
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5 text-forest" />
            <span>3. Client SLA Compliance Notice</span>
          </button>
        </div>

        {/* ─── Tab Content ─────────────────────────────────────────────────── */}
        <div className="flex-1 min-h-[300px] max-h-[420px] overflow-y-auto">
          {/* TAB 1: Tally Prime PO */}
          {activeTab === "tally" && (
            <div className="space-y-3 font-mono text-xs">
              <div className="flex items-center justify-between">
                <span className="text-charcoal-600 text-[11px] font-medium">
                  Enterprise XML schema formatted for Tally Prime Gateway Import
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={downloadJson}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/60 hover:bg-white text-charcoal-900 border border-white/80 transition-all text-[11px] font-bold shadow-sm"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download JSON</span>
                  </button>
                  <button
                    onClick={downloadXml}
                    className="flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-acid hover:bg-acid-hover text-charcoal-950 transition-all text-[11px] font-extrabold shadow-pill"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download Tally XML (.xml)</span>
                  </button>
                </div>
              </div>

              <div className="relative">
                <pre className="p-4 rounded-2xl bg-charcoal-950 border border-white/10 text-acid text-[11px] overflow-x-auto max-h-[320px] leading-relaxed shadow-inner">
                  {receipt.tally_xml_payload}
                </pre>
              </div>
            </div>
          )}

          {/* TAB 2: WhatsApp Shift Broadcast */}
          {activeTab === "whatsapp" && (
            <div className="space-y-3 font-mono text-xs">
              <div className="flex items-center justify-between">
                <span className="text-charcoal-600 text-[11px] font-medium">
                  {shiftNoticeHeading}
                </span>
                <button
                  onClick={() => copyText(receipt.shift_broadcast_msg, "whatsapp")}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/60 hover:bg-white text-charcoal-900 border border-white/80 transition-all text-[11px] font-bold shadow-sm"
                >
                  {copiedType === "whatsapp" ? (
                    <Check className="w-3.5 h-3.5 text-forest" />
                  ) : (
                    <Copy className="w-3.5 h-3.5" />
                  )}
                  <span>{copiedType === "whatsapp" ? "Copied!" : "Copy Broadcast"}</span>
                </button>
              </div>

              <div className="p-4 rounded-2xl bg-white/50 border border-white/70 text-charcoal-900 whitespace-pre-wrap text-[11.5px] leading-relaxed shadow-sm font-sans">
                {receipt.shift_broadcast_msg}
              </div>
            </div>
          )}

          {/* TAB 3: Client SLA Compliance Notice */}
          {activeTab === "sla" && (
            <div className="space-y-3 font-mono text-xs">
              <div className="flex items-center justify-between">
                <span className="text-charcoal-600 text-[11px] font-medium">
                  Draft client notice (copy and send after supplier confirmation)
                </span>
                <button
                  onClick={() => copyText(receipt.client_sla_notice, "sla")}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white/60 hover:bg-white text-charcoal-900 border border-white/80 transition-all text-[11px] font-bold shadow-sm"
                >
                  {copiedType === "sla" ? (
                    <Check className="w-3.5 h-3.5 text-forest" />
                  ) : (
                    <Copy className="w-3.5 h-3.5" />
                  )}
                  <span>{copiedType === "sla" ? "Copied!" : "Copy Notice"}</span>
                </button>
              </div>

              <div className="p-4 rounded-2xl bg-white/50 border border-white/70 text-charcoal-900 whitespace-pre-wrap text-[11.5px] leading-relaxed shadow-sm font-sans">
                {receipt.client_sla_notice}
              </div>
            </div>
          )}
        </div>

        {/* ─── Footer ──────────────────────────────────────────────────────── */}
        <div className="pt-3 border-t border-charcoal-900/10 flex items-center justify-between font-mono text-[11px] text-charcoal-600">
          <span>Executed At: {new Date(receipt.executed_at).toLocaleString()}</span>
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-full bg-charcoal-900 hover:bg-charcoal-800 text-white font-bold transition-colors text-xs"
          >
            Close Receipt
          </button>
        </div>
      </div>
    </div>
  );
}