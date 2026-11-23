"use client";

import React, { useEffect, useState } from "react";
import { Rfq, useFactoryStore } from "@/store/useFactoryStore";
import { Handshake, Loader2, Send } from "lucide-react";

const STATUS_STYLE: Record<Rfq["status"], string> = {
  SENT: "bg-amber-100 text-amber-900 border-amber-300",
  CONFIRMED: "bg-emerald-100 text-emerald-900 border-emerald-300",
  PARTIAL: "bg-sky-100 text-sky-900 border-sky-300",
  DECLINED: "bg-coral/15 text-coral border-coral/40",
  NO_REPLY: "bg-charcoal-900/10 text-charcoal-700 border-charcoal-900/20",
  SEND_FAILED: "bg-coral/15 text-coral border-coral/40",
};

const STATUS_LABEL: Record<Rfq["status"], string> = {
  SENT: "Awaiting reply",
  CONFIRMED: "Confirmed",
  PARTIAL: "Partial offer",
  DECLINED: "Declined",
  NO_REPLY: "No reply",
  SEND_FAILED: "Send failed",
};

function shortName(name: string) {
  return name.split(" (")[0];
}

function ReplyBox({ rfq }: { rfq: Rfq }) {
  const { submitVendorReply, isSourcingBusy } = useFactoryStore();
  const [text, setText] = useState("");
  const lead = Math.max(1, Math.round(rfq.needed_within_hours / 4));
  const factory = useFactoryStore((st) => st.factory);
  const vendor = factory?.vendors.find((v) => v.supplier_id === rfq.supplier_id);
  const charterCost = vendor?.flat_cost ?? 0;
  const isCharter = charterCost > 0;
  const quick = [
    {
      label: "Confirm",
      text: isCharter
        ? `YES ${rfq.units_requested} pcs, charter Rs ${rfq.expected_unit_price_inr || charterCost} in ${vendor?.lead_hours ?? lead}h`
        : `YES ${rfq.units_requested} pcs @${rfq.expected_unit_price_inr} in ${lead}h`,
    },
    { label: "Partial", text: `can do ${Math.max(1, Math.floor(rfq.units_requested / 2))} pcs only` },
    { label: "Decline", text: "NO, out of stock" },
  ];

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {quick.map((q) => (
          <button
            key={q.label}
            type="button"
            disabled={isSourcingBusy}
            onClick={() => submitVendorReply(rfq.supplier_id, q.text)}
            className="text-[10px] font-bold px-2 py-1 rounded-full bg-white border border-charcoal-900/15 hover:bg-charcoal-900/5 disabled:opacity-50"
            title={q.text}
          >
            {q.label}
          </button>
        ))}
      </div>
      <form
        className="flex gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          submitVendorReply(rfq.supplier_id, text);
          setText("");
        }}
      >
        <input
          aria-label={`Reply from ${shortName(rfq.supplier_name)}`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder='Vendor reply, e.g. "haan 120 pcs @650, 5 ghante"'
          className="flex-1 min-w-0 text-[11px] px-2.5 py-1.5 rounded-xl bg-white border border-charcoal-900/15"
        />
        <button
          type="submit"
          aria-label="Record reply"
          disabled={isSourcingBusy || !text.trim()}
          className="px-2.5 rounded-xl bg-charcoal-900 text-acid disabled:opacity-40"
        >
          <Send className="w-3.5 h-3.5" />
        </button>
      </form>
    </div>
  );
}

export function SourcingPanel() {
  const { sourcing, startSourcing, refreshSourcing, isSourcingBusy, playbooks, selectedPlaybookId, statusMode } =
    useFactoryStore();
  const selectedPlan = playbooks.find((p) => p.id === selectedPlaybookId);

  // Poll while enquiries are open (replies may arrive over Telegram; timeouts are applied server-side).
  useEffect(() => {
    if (sourcing?.status !== "ACTIVE") return;
    const t = setInterval(refreshSourcing, 4000);
    return () => clearInterval(t);
  }, [sourcing?.status, refreshSourcing]);

  if (statusMode === "PROTECTED") return null;

  if (!sourcing) {
    if (!selectedPlan || selectedPlan.vendor_allocations.length === 0) return null;
    return (
      <div className="p-3 rounded-2xl bg-violet-50 border border-violet-200 space-y-2">
        <p className="text-[11px] text-violet-950 leading-relaxed">
          Sends a question (not an order) to the suppliers in {selectedPlan.id}, reads
          their replies and re-plans if someone can&apos;t deliver.
        </p>
        <button
          type="button"
          onClick={startSourcing}
          disabled={isSourcingBusy}
          className="w-full py-2.5 rounded-xl bg-violet-700 hover:bg-violet-800 text-white font-bold text-[11px] flex items-center justify-center gap-2 disabled:opacity-50"
        >
          {isSourcingBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Handshake className="w-3.5 h-3.5" />}
          Ask suppliers first
        </button>
      </div>
    );
  }

  const done = sourcing.status !== "ACTIVE";
  const winner = sourcing.playbooks.find((p) => p.id === sourcing.recommended_plan_id);

  return (
    <div className="p-3 rounded-2xl bg-violet-50 border border-violet-200 space-y-2" aria-live="polite">
      <div className="flex items-center justify-between text-[10px] font-bold text-violet-950">
        <span className="flex items-center gap-1.5">
          <Handshake className="w-3.5 h-3.5" /> ASKING SUPPLIERS · ROUND {sourcing.round}/{sourcing.max_rounds}
        </span>
        <span className="uppercase">{sourcing.status.replace(/_/g, " ")}</span>
      </div>

      {!done && (
        <p className="text-[10px] text-violet-900">
          {sourcing.mode === "telegram"
            ? `Waiting for Telegram replies (timeout ${sourcing.reply_timeout_min} min). Replies received elsewhere can be entered below.`
            : "Nothing is sent in this mode: type each supplier's reply (or use a quick reply)."}
        </p>
      )}

      <ul className="space-y-2">
        {sourcing.rfqs.map((rfq) => (
          <li key={rfq.id} className="p-2.5 rounded-xl bg-white/80 border border-violet-100">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-bold text-charcoal-900">
                {shortName(rfq.supplier_name)}{" "}
                <span className="font-normal text-charcoal-500">R{rfq.round}</span>
              </span>
              <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full border ${STATUS_STYLE[rfq.status]}`}>
                {STATUS_LABEL[rfq.status]}
              </span>
            </div>
            <p className="text-[10px] text-charcoal-600 mt-0.5">
              Asked {rfq.units_requested}u within {rfq.needed_within_hours}h
              {rfq.offered_units != null && rfq.status !== "DECLINED" &&
                ` → offered ${rfq.offered_units}u @ ₹${(rfq.offered_unit_price_inr ?? 0).toLocaleString("en-IN")} in ${rfq.offered_eta_hours}h`}
            </p>
            {rfq.reply_text && (
              <p className="text-[10px] text-charcoal-700 mt-0.5 italic">
                “{rfq.reply_text}”{rfq.parsed_by && <span className="not-italic text-charcoal-400"> · {rfq.parsed_by}</span>}
              </p>
            )}
            {rfq.status === "SENT" && <ReplyBox rfq={rfq} />}
          </li>
        ))}
      </ul>

      {done && winner && (
        <div
          className={`p-2.5 rounded-xl text-[11px] leading-relaxed ${
            sourcing.status === "COMPLETE_UNCONFIRMED"
              ? "bg-amber-100 text-amber-950 border border-amber-300"
              : "bg-emerald-100 text-emerald-950 border border-emerald-300"
          }`}
        >
          <strong>{sourcing.status === "COMPLETE_UNCONFIRMED" ? "⚠ Partly unconfirmed plan:" : "✅ Confirmed plan:"}</strong>{" "}
          {winner.id} — {winner.description} (₹{winner.total_mitigation_cost_inr.toLocaleString("en-IN")}, on-time chance{" "}
          {winner.confidence_pct}%). Approve below.
        </div>
      )}
    </div>
  );
}
