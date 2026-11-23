"use client";

import React, { useEffect, useState } from "react";
import { useFactoryStore } from "@/store/useFactoryStore";
import { clientStatusText } from "@/lib/clientStatus";
import { Loader2, MailCheck } from "lucide-react";

const FIELD = "text-[11px] px-2.5 py-1.5 rounded-xl bg-white border border-charcoal-900/15";

export function ClientPanel() {
  const {
    activeRunId, statusMode, clientRecord, isClientBusy, clientError,
    loadClient, draftClientExtension, approveClientExtension, answerClientExtension,
  } = useFactoryStore();
  const [hours, setHours] = useState("12");
  const [reason, setReason] = useState("");
  const [approver, setApprover] = useState("");
  const [answerText, setAnswerText] = useState("");
  const [newDeadline, setNewDeadline] = useState("");

  // Load any existing request for this run; poll while we wait for the client's answer.
  useEffect(() => {
    if (activeRunId) loadClient();
  }, [activeRunId, loadClient]);
  const status = clientRecord?.status;
  useEffect(() => {
    if (status !== "SENT" && status !== "ANSWERING") return;
    const t = setInterval(loadClient, 4000);
    return () => clearInterval(t);
  }, [status, loadClient]);

  if (!activeRunId || statusMode === "PROTECTED") return null;

  const hoursNum = Number(hours);
  const hoursOk = Number.isInteger(hoursNum) && hoursNum > 0;
  const deadlineOk = newDeadline.trim() === "" || (Number.isInteger(Number(newDeadline)) && Number(newDeadline) > 0);

  return (
    <div className="p-3 rounded-2xl bg-sky-50 border border-sky-200 space-y-2" aria-live="polite">
      <div className="flex items-center justify-between text-[10px] font-bold text-sky-950">
        <span className="flex items-center gap-1.5">
          <MailCheck className="w-3.5 h-3.5" /> CLIENT AGENT
        </span>
        {status && <span className="uppercase">{status}</span>}
      </div>
      <p className="text-[11px] text-sky-950 leading-relaxed">{clientStatusText(clientRecord)}</p>

      {(!clientRecord || status === "DRAFTED") && (
        <form
          className="flex flex-wrap gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (hoursOk) draftClientExtension(hoursNum, reason);
          }}
        >
          <input
            aria-label="Extension hours"
            value={hours}
            onChange={(e) => setHours(e.target.value)}
            inputMode="numeric"
            className={`${FIELD} w-16`}
          />
          <input
            aria-label="Reason (optional)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (optional)"
            className={`${FIELD} flex-1 min-w-0`}
          />
          <button
            type="submit"
            disabled={isClientBusy || !hoursOk}
            className="px-3 rounded-xl bg-sky-700 text-white font-bold text-[11px] disabled:opacity-40"
          >
            {clientRecord ? "Redraft" : "Draft extension request"}
          </button>
        </form>
      )}

      {clientRecord?.draft_message && (
        <pre className="whitespace-pre-wrap text-[10px] bg-white/80 border border-sky-100 rounded-xl p-2.5 text-charcoal-800">
          {clientRecord.draft_message}
        </pre>
      )}

      {status === "DRAFTED" && (
        <form
          className="flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (approver.trim()) approveClientExtension(approver.trim());
          }}
        >
          <input
            aria-label="Approved by"
            value={approver}
            onChange={(e) => setApprover(e.target.value)}
            placeholder="Your name (approver)"
            className={`${FIELD} flex-1 min-w-0`}
          />
          <button
            type="submit"
            disabled={isClientBusy || !approver.trim()}
            className="px-3 rounded-xl bg-charcoal-900 text-acid font-bold text-[11px] disabled:opacity-40"
          >
            Approve &amp; send
          </button>
        </form>
      )}

      {(status === "SENT" || status === "ANSWERING") && (
        <div className="space-y-1.5">
          <div className="flex gap-1.5">
            <input
              aria-label="Client's reply text"
              value={answerText}
              onChange={(e) => setAnswerText(e.target.value)}
              placeholder="Client's reply (optional)"
              className={`${FIELD} flex-1 min-w-0`}
            />
            <input
              aria-label="New deadline hours (optional)"
              value={newDeadline}
              onChange={(e) => setNewDeadline(e.target.value)}
              placeholder="New deadline h"
              inputMode="numeric"
              className={`${FIELD} w-28`}
            />
          </div>
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={isClientBusy || !deadlineOk}
              onClick={() => answerClientExtension(true, answerText, newDeadline.trim() ? Number(newDeadline) : undefined)}
              className="flex-1 py-2 rounded-xl bg-emerald-700 text-white font-bold text-[11px] disabled:opacity-40"
            >
              Accepted (+{clientRecord?.extension_hours ?? "?"}h)
            </button>
            <button
              type="button"
              disabled={isClientBusy}
              onClick={() => answerClientExtension(false, answerText)}
              className="flex-1 py-2 rounded-xl bg-coral text-white font-bold text-[11px] disabled:opacity-40"
            >
              Refused
            </button>
          </div>
        </div>
      )}

      {isClientBusy && (
        <p className="text-[10px] text-sky-900 flex items-center gap-1">
          <Loader2 className="w-3 h-3 animate-spin" /> Working…
        </p>
      )}
      {clientError && (
        <p role="alert" className="text-[11px] text-coral font-medium">
          {clientError}
        </p>
      )}
    </div>
  );
}
