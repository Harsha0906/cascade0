"use client";

import React, { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { AlertTriangle, CheckCircle2, Clock, Flame, ShieldCheck, Truck, Zap } from "lucide-react";
import { RECOVERY_STATUSES, useFactoryStore } from "@/store/useFactoryStore";

type Tone = "ok" | "bad" | "good" | "neutral";

const TONE_CARD: Record<Tone, string> = {
  ok: "hover:border-white/70",
  neutral: "hover:border-white/70",
  bad: "!border-coral !bg-coral/15 !shadow-[0_18px_40px_rgba(255,71,87,0.3)] ring-2 ring-coral/50",
  good: "!border-acid/90 !bg-acid/20 !shadow-[0_18px_40px_rgba(229,244,58,0.25)] ring-2 ring-acid",
};
const TONE_PILL: Record<Tone, string> = {
  ok: "bg-forest/15 text-forest-deep border border-forest/30",
  neutral: "bg-white/40 text-charcoal-700 border border-white/60",
  bad: "bg-coral text-white border border-coral shadow-pill-coral",
  good: "bg-acid text-charcoal-950 border border-acid shadow-pill",
};
const TONE_ICON: Record<Tone, string> = {
  ok: "bg-white/50 border border-white/70 text-charcoal-900",
  neutral: "bg-white/50 border border-white/70 text-charcoal-900",
  bad: "bg-coral text-white shadow-pill-coral",
  good: "bg-acid text-charcoal-950 shadow-pill",
};
const HANDLE = "!w-2.5 !h-2.5 !border-2 !border-white";

const label = (s: string) => s.replace(/_/g, " ");

function supplierTone(status: string): Tone {
  if (status === "DELAYED") return "bad";
  if (status === "PO_DRAFTED") return "good";
  return "ok";
}
function lineTone(status: string): Tone {
  if (status === "THROTTLED") return "bad";
  if (status === "OVERTIME_SCHEDULED") return "good";
  return "ok";
}
function orderTone(status: string): Tone {
  if (status === "BREACH_RISK") return "bad";
  if (RECOVERY_STATUSES.includes(status)) return "good";
  return "ok";
}

// ─── Supplier ────────────────────────────────────────────────────────────────
export const SupplierNode = memo(({ data }: any) => {
  const setSelectedNodeData = useFactoryStore((s) => s.setSelectedNodeData);
  const tone = supplierTone(data.status);

  return (
    <div
      onClick={() => setSelectedNodeData({ type: "SUPPLIER", ...data })}
      className={`cursor-pointer rounded-[24px] p-4 w-72 transition-all duration-300 island-card select-none ${TONE_CARD[tone]}`}
    >
      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[10px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-full bg-white/40 border border-white/60 text-charcoal-800">
          {data.role}
        </span>
        <span className={`flex items-center gap-1 text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full ${TONE_PILL[tone]}`}>
          {tone === "bad" ? <AlertTriangle className="w-3 h-3" /> : tone === "good" ? <Clock className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3" />}
          {data.status === "DELAYED" ? `DELAYED (+${data.delayHours}h)` : label(data.status)}
        </span>
      </div>

      <div className="flex items-center gap-2.5 mb-2.5">
        <div className={`p-2.5 rounded-2xl flex items-center justify-center transition-colors ${TONE_ICON[tone]}`}>
          <Truck className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-charcoal-900 tracking-tight leading-tight truncate">{data.name}</h3>
          <p className="text-[11px] font-medium text-charcoal-700">{data.supplierId}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-2.5 pt-2.5 border-t border-charcoal-900/10 font-mono text-xs">
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Inbound Qty</span>
          <span className="text-charcoal-900 font-bold tabular-nums text-sm">{data.inboundQty}</span>
        </div>
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Allocated</span>
          <span className="text-charcoal-900 font-bold tabular-nums text-sm">
            {data.allocatedUnits ? `${data.allocatedUnits} units` : "-"}
          </span>
        </div>
      </div>

      <Handle type="source" position={Position.Right} className={`${HANDLE} ${tone === "bad" ? "!bg-coral" : "!bg-charcoal-900"}`} />
    </div>
  );
});
SupplierNode.displayName = "SupplierNode";

// ─── Production line ─────────────────────────────────────────────────────────
export const LineNode = memo(({ data }: any) => {
  const setSelectedNodeData = useFactoryStore((s) => s.setSelectedNodeData);
  const tone = lineTone(data.status);

  return (
    <div
      onClick={() => setSelectedNodeData({ type: "PRODUCTION_LINE", ...data })}
      className={`cursor-pointer rounded-[24px] p-4 w-72 transition-all duration-300 island-card select-none ${TONE_CARD[tone]}`}
    >
      <Handle type="target" position={Position.Left} className={`${HANDLE} !bg-charcoal-900`} />

      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[10px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-full bg-white/40 border border-white/60 text-charcoal-800">
          PRODUCTION LINE
        </span>
        <span className={`flex items-center gap-1 text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full ${TONE_PILL[tone]} ${tone === "bad" ? "animate-pulse" : ""}`}>
          {tone === "good" ? <Zap className="w-3 h-3" /> : <Flame className="w-3 h-3" />}
          {label(data.status)}
        </span>
      </div>

      <div className="flex items-center gap-2.5 mb-2.5">
        <div className={`p-2.5 rounded-2xl flex items-center justify-center transition-colors ${TONE_ICON[tone]}`}>
          <Flame className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-charcoal-900 tracking-tight leading-tight truncate">{data.name}</h3>
          <p className="text-[11px] font-medium text-charcoal-700">{data.lineId}</p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-2.5 pt-2.5 border-t border-charcoal-900/10 font-mono text-xs">
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Speed</span>
          <span className={`font-bold tabular-nums text-sm ${tone === "bad" ? "text-coral font-extrabold" : "text-charcoal-900"}`}>
            {data.speedPct}%
          </span>
        </div>
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Temp</span>
          <span className="font-bold tabular-nums text-sm text-charcoal-900">{data.tempC}°C</span>
        </div>
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">OT</span>
          <span className="font-bold tabular-nums text-sm text-charcoal-900">{data.otHours ? `+${data.otHours}h` : "-"}</span>
        </div>
      </div>

      <Handle type="source" position={Position.Right} className={`${HANDLE} ${tone === "bad" ? "!bg-coral" : "!bg-charcoal-900"}`} />
    </div>
  );
});
LineNode.displayName = "LineNode";

// ─── Order ───────────────────────────────────────────────────────────────────
export const OrderNode = memo(({ data }: any) => {
  const setSelectedNodeData = useFactoryStore((s) => s.setSelectedNodeData);
  const tone = orderTone(data.status);

  return (
    <div
      onClick={() => setSelectedNodeData({ type: "ORDER_SLA", ...data })}
      className={`cursor-pointer rounded-[24px] p-4 w-80 transition-all duration-300 island-card select-none ${TONE_CARD[tone]} ${
        data.isFocus ? "outline outline-2 outline-offset-2 outline-charcoal-900/40" : ""
      }`}
    >
      <Handle type="target" position={Position.Left} className={`${HANDLE} ${tone === "bad" ? "!bg-coral" : "!bg-charcoal-900"}`} />

      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[10px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-full bg-white/40 border border-white/60 text-charcoal-800">
          {data.isFocus ? "FOCUS ORDER" : "CLIENT ORDER"}
        </span>
        <span className={`flex items-center gap-1 text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full ${TONE_PILL[tone]}`}>
          {tone === "bad" ? <AlertTriangle className="w-3.5 h-3.5" /> : tone === "good" ? <ShieldCheck className="w-3.5 h-3.5" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
          {label(data.status)}
        </span>
      </div>

      <div className="flex items-center gap-2.5 mb-2.5">
        <div className={`p-2.5 rounded-2xl flex items-center justify-center transition-colors ${TONE_ICON[tone]}`}>
          <ShieldCheck className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-charcoal-900 tracking-tight leading-tight">Order #{data.orderId}</h3>
          <p className="text-[11px] font-medium text-charcoal-700 truncate">{data.client}</p>
        </div>
      </div>

      <div className="space-y-2 mt-2.5 pt-2.5 border-t border-charcoal-900/10 font-mono text-xs">
        <div className="flex justify-between items-center">
          <span className="text-[10px] font-bold text-charcoal-600 uppercase tracking-wide">Unit Shortfall:</span>
          <span className={`font-bold tabular-nums text-sm ${tone === "bad" ? "text-coral font-extrabold" : "text-charcoal-900"}`}>
            {data.shortfall}
          </span>
        </div>
        <div className="flex justify-between items-center pt-1.5 border-t border-charcoal-900/10">
          <span className="text-[10px] font-bold text-charcoal-600 uppercase tracking-wide">SLA Penalty:</span>
          <span className={`font-extrabold text-sm tabular-nums ${tone === "bad" ? "text-coral" : "text-charcoal-700"}`}>
            ₹{(data.penaltyInr ?? 0).toLocaleString("en-IN")}
          </span>
        </div>
      </div>
    </div>
  );
});
OrderNode.displayName = "OrderNode";

// Node type registry for React Flow
export const nodeTypes = {
  supplier: SupplierNode,
  line: LineNode,
  order: OrderNode,
};
