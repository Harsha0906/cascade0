"use client";

import React, { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { AlertTriangle, CheckCircle2, Clock, Flame, ShieldCheck, Truck, Zap } from "lucide-react";
import { useFactoryStore } from "@/store/useFactoryStore";

// ─── Node 1: NH48 Chennai Supply (Top-Left) ──────────────────────────────────
export const ChennaiSupplyNode = memo(({ data }: any) => {
  const setSelectedNodeData = useFactoryStore((s) => s.setSelectedNodeData);
  const isCrisis = data.isCrisis || data.status === "DELAYED";

  return (
    <div
      onClick={() => setSelectedNodeData({ type: "SUPPLIER", ...data })}
      className={`cursor-pointer rounded-[24px] p-4 w-72 transition-all duration-300 island-card select-none ${
        isCrisis
          ? "!border-coral !bg-coral/15 !shadow-[0_18px_40px_rgba(255,71,87,0.3)] ring-2 ring-coral/50"
          : "hover:border-white/70"
      }`}
    >
      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[10px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-full bg-white/40 border border-white/60 text-charcoal-800">
          TIER-1 INBOUND
        </span>
        <span
          className={`flex items-center gap-1 text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full ${
            isCrisis
              ? "bg-coral text-white border border-coral shadow-pill-coral"
              : "bg-forest/15 text-forest-deep border border-forest/30"
          }`}
        >
          {isCrisis ? <AlertTriangle className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3 text-forest" />}
          {isCrisis ? `DELAYED (+${data.delayHours || 48}h)` : "ON SCHEDULE"}
        </span>
      </div>

      <div className="flex items-center gap-2.5 mb-2.5">
        <div
          className={`p-2.5 rounded-2xl flex items-center justify-center transition-colors ${
            isCrisis
              ? "bg-coral text-white shadow-pill-coral"
              : "bg-white/50 border border-white/70 text-charcoal-900"
          }`}
        >
          <Truck className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-charcoal-900 tracking-tight leading-tight">NH48 Chennai Logistics</h3>
          <p className="text-[11px] font-medium text-charcoal-700">SUP-CHN-01 • Chennai Casings</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-2.5 pt-2.5 border-t border-charcoal-900/10 font-mono text-xs">
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Inbound Qty</span>
          <span className="text-charcoal-900 font-bold tabular-nums text-sm">{data.inboundQty || 500} Casings</span>
        </div>
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Highway Route</span>
          <span className="text-charcoal-800 font-medium text-[11px] truncate block">NH48 Chennai-BLR</span>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className={`!w-2.5 !h-2.5 !border-2 ${isCrisis ? "!bg-coral !border-white" : "!bg-charcoal-900 !border-white"}`}
      />
    </div>
  );
});
ChennaiSupplyNode.displayName = "ChennaiSupplyNode";


// ─── Node 2: Peenya + Hosur Backup (Bottom-Left) ────────────────────────────
export const BackupVendorNode = memo(({ data }: any) => {
  const setSelectedNodeData = useFactoryStore((s) => s.setSelectedNodeData);
  const isProtected = data.isProtected;
  const isCrisis = data.isCrisis;

  return (
    <div
      onClick={() => setSelectedNodeData({ type: "BACKUP_VENDORS", ...data })}
      className={`cursor-pointer rounded-[24px] p-4 w-72 transition-all duration-300 island-card select-none ${
        isProtected
          ? "!border-acid/90 !bg-acid/20 !shadow-[0_18px_40px_rgba(229,244,58,0.25)] ring-2 ring-acid"
          : isCrisis
          ? "border-amber-400/80 bg-amber-500/10 shadow-[0_14px_30px_rgba(245,158,11,0.2)]"
          : "hover:border-white/70"
      }`}
    >
      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[10px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-full bg-white/40 border border-white/60 text-charcoal-800">
          REGIONAL STANDBY
        </span>
        <span
          className={`flex items-center gap-1 text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full ${
            isProtected
              ? "bg-acid text-charcoal-950 border border-acid shadow-pill"
              : isCrisis
              ? "bg-amber-100 text-amber-900 border border-amber-300"
              : "bg-white/40 text-charcoal-700 border border-white/60"
          }`}
        >
          <Clock className="w-3 h-3" />
          {isProtected ? "PO DISPATCHED" : isCrisis ? "RECOVERY READY" : "STANDBY (14 KM)"}
        </span>
      </div>

      <div className="flex items-center gap-2.5 mb-2.5">
        <div
          className={`p-2.5 rounded-2xl flex items-center justify-center transition-colors ${
            isProtected
              ? "bg-acid text-charcoal-950 shadow-pill"
              : "bg-white/50 border border-white/70 text-charcoal-900"
          }`}
        >
          <Zap className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-charcoal-900 tracking-tight leading-tight">Peenya + Hosur SME Network</h3>
          <p className="text-[11px] font-medium text-charcoal-700">SUP-PNY-02 & SUP-HSR-03</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-2.5 pt-2.5 border-t border-charcoal-900/10 font-mono text-xs">
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Peenya @ ₹600</span>
          <span className="text-charcoal-900 font-bold tabular-nums text-sm">
            {data.peenyaAllocated ? `${data.peenyaAllocated} Allocated` : "200 Avail"}
          </span>
        </div>
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Hosur @ ₹850</span>
          <span className="text-charcoal-900 font-bold tabular-nums text-sm">
            {data.hosurAllocated ? `${data.hosurAllocated} Allocated` : "180 Avail"}
          </span>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !border-2 !bg-charcoal-900 !border-white"
      />
    </div>
  );
});
BackupVendorNode.displayName = "BackupVendorNode";


// ─── Node 3: Welding Line 2 (Center-Top) ────────────────────────────────────
export const WeldingLine2Node = memo(({ data }: any) => {
  const setSelectedNodeData = useFactoryStore((s) => s.setSelectedNodeData);
  const isCrisis = data.isCrisis || data.status?.includes("OVERHEAT");

  return (
    <div
      onClick={() => setSelectedNodeData({ type: "PRODUCTION_LINE", ...data })}
      className={`cursor-pointer rounded-[24px] p-4 w-72 transition-all duration-300 island-card select-none ${
        isCrisis
          ? "!border-coral !bg-coral/15 !shadow-[0_18px_40px_rgba(255,71,87,0.35)] ring-2 ring-coral/60"
          : "hover:border-white/70"
      }`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !border-2 !bg-charcoal-900 !border-white"
      />

      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[10px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-full bg-white/40 border border-white/60 text-charcoal-800">
          PLC-L2 TELEMETRY
        </span>
        <span
          className={`flex items-center gap-1 text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full ${
            isCrisis
              ? "bg-coral text-white border border-coral shadow-pill-coral animate-pulse"
              : "bg-forest/15 text-forest-deep border border-forest/30"
          }`}
        >
          <Flame className="w-3 h-3" />
          {isCrisis ? "THERMAL THROTTLE" : "NOMINAL SPEED"}
        </span>
      </div>

      <div className="flex items-center gap-2.5 mb-2.5">
        <div
          className={`p-2.5 rounded-2xl flex items-center justify-center transition-colors ${
            isCrisis
              ? "bg-coral text-white shadow-pill-coral"
              : "bg-white/50 border border-white/70 text-charcoal-900"
          }`}
        >
          <Flame className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-charcoal-900 tracking-tight leading-tight">Robotic Welding Line 2</h3>
          <p className="text-[11px] font-medium text-charcoal-700">LINE-2 • Primary Pack Assembly</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-2.5 pt-2.5 border-t border-charcoal-900/10 font-mono text-xs">
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Line Speed</span>
          <span className={`font-bold tabular-nums text-sm ${isCrisis ? "text-coral font-extrabold" : "text-charcoal-900"}`}>
            {data.speedPct || 100}%
          </span>
        </div>
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Operating Temp</span>
          <span className={`font-bold tabular-nums text-sm ${isCrisis ? "text-coral font-extrabold" : "text-charcoal-900"}`}>
            {data.tempC || 62.0}°C
          </span>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className={`!w-2.5 !h-2.5 !border-2 ${isCrisis ? "!bg-coral !border-white" : "!bg-charcoal-900 !border-white"}`}
      />
    </div>
  );
});
WeldingLine2Node.displayName = "WeldingLine2Node";


// ─── Node 4: Lines 1 & 3 Buffer (Center-Bottom) ─────────────────────────────
export const ParallelBufferNode = memo(({ data }: any) => {
  const setSelectedNodeData = useFactoryStore((s) => s.setSelectedNodeData);
  const isProtected = data.isProtected;

  return (
    <div
      onClick={() => setSelectedNodeData({ type: "PARALLEL_BUFFER", ...data })}
      className={`cursor-pointer rounded-[24px] p-4 w-72 transition-all duration-300 island-card select-none ${
        isProtected
          ? "!border-acid/90 !bg-acid/20 !shadow-[0_18px_40px_rgba(229,244,58,0.25)] ring-2 ring-acid"
          : "hover:border-white/70"
      }`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !border-2 !bg-charcoal-900 !border-white"
      />

      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[10px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-full bg-white/40 border border-white/60 text-charcoal-800">
          PARALLEL CAPACITY
        </span>
        <span
          className={`flex items-center gap-1 text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full ${
            isProtected
              ? "bg-acid text-charcoal-950 border border-acid shadow-pill"
              : "bg-white/40 text-charcoal-800 border border-white/60"
          }`}
        >
          <Clock className="w-3 h-3" />
          {isProtected ? "OVERTIME ACTIVE" : "BUFFER STANDBY"}
        </span>
      </div>

      <div className="flex items-center gap-2.5 mb-2.5">
        <div
          className={`p-2.5 rounded-2xl flex items-center justify-center transition-colors ${
            isProtected
              ? "bg-acid text-charcoal-950 shadow-pill"
              : "bg-white/50 border border-white/70 text-charcoal-900"
          }`}
        >
          <Zap className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-charcoal-900 tracking-tight leading-tight">Welding Lines 1 & 3 Buffer</h3>
          <p className="text-[11px] font-medium text-charcoal-700">LINE-1 & LINE-3 • 38 u/hr OT</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-2.5 pt-2.5 border-t border-charcoal-900/10 font-mono text-xs">
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Overtime Plan</span>
          <span className="text-charcoal-900 font-bold tabular-nums text-sm">
            {data.otHours ? `+${data.otHours}h Shift OT` : "Standby (Max 8h)"}
          </span>
        </div>
        <div>
          <span className="text-[10px] font-bold text-charcoal-600 block uppercase tracking-wide">Overtime Rate</span>
          <span className="text-charcoal-800 font-bold tabular-nums text-sm">₹22,500/hr</span>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !border-2 !bg-charcoal-900 !border-white"
      />
    </div>
  );
});
ParallelBufferNode.displayName = "ParallelBufferNode";


// ─── Node 5: Order #EV-402 SLA Contract (Right) ─────────────────────────────
export const OrderSlaNode = memo(({ data }: any) => {
  const setSelectedNodeData = useFactoryStore((s) => s.setSelectedNodeData);
  const isProtected = data.isProtected || data.status === "SLA_PROTECTED";
  const isCrisis = !isProtected && (data.isCrisis || data.status === "BREACH_RISK");

  return (
    <div
      onClick={() => setSelectedNodeData({ type: "ORDER_SLA", ...data })}
      className={`cursor-pointer rounded-[24px] p-4 w-80 transition-all duration-300 island-card select-none ${
        isProtected
          ? "!border-acid !bg-acid/20 !shadow-[0_20px_45px_rgba(229,244,58,0.3)] ring-2 ring-acid"
          : isCrisis
          ? "!border-coral !bg-coral/20 !shadow-[0_22px_50px_rgba(255,71,87,0.4)] ring-2 ring-coral animate-pulse-slow"
          : "hover:border-white/70"
      }`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className={`!w-2.5 !h-2.5 !border-2 ${isCrisis ? "!bg-coral !border-white" : "!bg-charcoal-900 !border-white"}`}
      />

      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[10px] font-bold tracking-wider uppercase px-2.5 py-0.5 rounded-full bg-white/40 border border-white/60 text-charcoal-800">
          CLIENT SLA CONTRACT
        </span>
        <span
          className={`flex items-center gap-1 text-[11px] font-mono font-bold px-2.5 py-0.5 rounded-full ${
            isProtected
              ? "bg-acid text-charcoal-950 border border-acid shadow-pill"
              : isCrisis
              ? "bg-coral text-white border border-coral shadow-pill-coral"
              : "bg-forest/15 text-forest-deep border border-forest/30"
          }`}
        >
          {isProtected ? (
            <ShieldCheck className="w-3.5 h-3.5" />
          ) : isCrisis ? (
            <AlertTriangle className="w-3.5 h-3.5" />
          ) : (
            <CheckCircle2 className="w-3.5 h-3.5 text-forest" />
          )}
          {isProtected ? "SLA PROTECTED" : isCrisis ? "BREACH RISK" : "ON TRACK"}
        </span>
      </div>

      <div className="flex items-center gap-2.5 mb-2.5">
        <div
          className={`p-2.5 rounded-2xl flex items-center justify-center transition-colors ${
            isProtected
              ? "bg-acid text-charcoal-950 shadow-pill"
              : isCrisis
              ? "bg-coral text-white shadow-pill-coral"
              : "bg-white/50 border border-white/70 text-charcoal-900"
          }`}
        >
          <ShieldCheck className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-sm font-bold text-charcoal-900 tracking-tight leading-tight">Order #EV-402 Delivery</h3>
          <p className="text-[11px] font-medium text-charcoal-700">Ather-Grid Mobility • 500 Packs</p>
        </div>
      </div>

      <div className="space-y-2 mt-2.5 pt-2.5 border-t border-charcoal-900/10 font-mono text-xs">
        <div className="flex justify-between items-center">
          <span className="text-[10px] font-bold text-charcoal-600 uppercase tracking-wide">Committed SLA:</span>
          <span className="text-charcoal-800 font-semibold text-[11px]">Friday 17:00 IST (38h)</span>
        </div>

        <div className="flex justify-between items-center">
          <span className="text-[10px] font-bold text-charcoal-600 uppercase tracking-wide">Net Unit Shortfall:</span>
          <span
            className={`font-bold tabular-nums text-sm ${
              isProtected
                ? "text-charcoal-900 font-extrabold"
                : isCrisis
                ? "text-coral font-extrabold"
                : "text-forest-deep"
            }`}
          >
            {isProtected ? "0 Units (Mitigated)" : isCrisis ? `-${data.shortfall || 150} Casings` : "0 Casings"}
          </span>
        </div>

        <div className="flex justify-between items-center pt-1.5 border-t border-charcoal-900/10">
          <span className="text-[10px] font-bold text-charcoal-600 uppercase tracking-wide">SLA Penalty Risk:</span>
          <span
            className={`font-mono font-extrabold text-sm tabular-nums ${
              isProtected
                ? "text-forest-deep"
                : isCrisis
                ? "text-coral"
                : "text-charcoal-700"
            }`}
          >
            {isProtected
              ? `₹0 (Saved ₹${(data.savedInr / 100000 || 23.2).toFixed(1)}L)`
              : isCrisis
              ? "-₹25,00,000"
              : "₹0 Risk"}
          </span>
        </div>
      </div>
    </div>
  );
});
OrderSlaNode.displayName = "OrderSlaNode";

// Export node types registry for React Flow
export const nodeTypes = {
  chennaiSupplyNode: ChennaiSupplyNode,
  backupVendorNode: BackupVendorNode,
  weldingLine2Node: WeldingLine2Node,
  parallelBufferNode: ParallelBufferNode,
  orderSlaNode: OrderSlaNode,
};