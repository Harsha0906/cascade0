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
  const { executionReceipt, selectedPlaybookId } = useFactoryStore();
  const [activeTab, setActiveTab] = useState<"tally" | "whatsapp" | "sla">("tally");
  const [copiedType, setCopiedType] = useState<string | null>(null);

  if (!isOpen && !executionReceipt) return null;

  const receipt = executionReceipt || {
    po_number: "PO-APEX-2026-889",
    playbook_id: selectedPlaybookId || "PLAN_B",
    order_id: "EV-402",
    tally_xml_payload: `<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Purchase Order" ACTION="Create">
            <VOUCHERNUMBER>PO-APEX-2026-889</VOUCHERNUMBER>
            <DATE>20261108</DATE>
            <PARTYNAME>Peenya Rapid Metals</PARTYNAME>
            <NARRATION>CascadeZero Emergency PO: Plan B | Shortfall Mitigation</NARRATION>
            <INVENTORYALLOCATIONS.LIST>
              <STOCKITEMNAME>Aluminum Battery Casings</STOCKITEMNAME>
              <RATE>₹600</RATE>
              <ACTUALQTY>150 Nos</ACTUALQTY>
              <BILLEDQTY>150 Nos</BILLEDQTY>
              <AMOUNT>₹90,000</AMOUNT>
            </INVENTORYALLOCATIONS.LIST>
            <BASICBUYERADDRESS>Unit-2, Peenya Industrial Area, Bengaluru - 560058</BASICBUYERADDRESS>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>`,
    tally_json_payload: {
      voucher_type: "Purchase Order",
      po_number: "PO-APEX-2026-889",
      date: "2026-11-08",
      company: "Apex Volt EV Battery Plant (Bengaluru Unit-2)",
      total_cost_inr: 180000,
      allocations: [
        { supplier_name: "Peenya Rapid Metals", units_allocated: 150, cost_per_unit_inr: 600 }
      ],
      overtime_hours: 4
    },
    shift_broadcast_msg: `🚨 *CASCADEZERO SHIFT OVERTIME DISPATCH NOTICE*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• *Facility:* Apex Volt Unit-2 (Bengaluru)
• *Target Lines:* Robotic Welding Lines 1 & 3 (Parallel)
• *Mandated Overtime:* *4 Hours* (Shift Ext. to 21:00 IST)
• *Target Production:* *150 Battery Casings*
• *Overtime Rate:* Approved @ ₹22,500/hr factory cost
• *Priority Order:* Ather-Grid Mobility Corp (#EV-402)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Floor supervisors please log supervisor confirmation code: *#CZ-OT-4H*.`,
    client_sla_notice: `📄 *OFFICIAL SLA COMPLIANCE & DISPATCH CONFIRMATION*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• *Client:* Ather-Grid Mobility Corp
• *Order ID:* #EV-402
• *Committed Deadline:* Friday 17:00 IST (38h Remaining)
• *Status:* 100% ON-TRACK (SLA Penalty Shield Active)
• *Mitigation Protocol:* CascadeZero Automated Re-Route Enacted
• *Dispatched Casings:* 500/500 units verified in line buffer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Apex Volt Operational Crisis Control Tower — Zero Penalty Breach.`,
    executed_at: new Date().toISOString(),
  };

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
                Transaction committed to Supabase • Dispatched to Accounting, Floor & Client
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
                  Automated floor supervisor dispatch for Robotic Welding Lines 1 & 3
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
                  Official SLA Compliance Certificate dispatched to Ather-Grid Mobility Corp
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