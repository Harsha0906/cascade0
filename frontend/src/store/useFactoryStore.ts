import { create } from "zustand";
import { Edge, Node } from "@xyflow/react";
import { subscribeToTable } from "@/lib/supabase";

export interface Supplier {
  id: string;
  name: string;
  tier: string;
  route: string;
  part_name: string;
  inbound_qty: number;
  max_available_qty: number;
  extra_cost_per_unit_inr: number;
  flat_charter_cost_inr: number;
  lead_time_hours: number;
  traffic_risk_pct: number;
  weather_risk_pct: number;
  status: string;
  delay_hours: number;
}

export interface VendorHistory {
  id: number;
  supplier_id: string;
  past_orders_count: number;
  on_time_deliveries: number;
  reliability_score_pct: number;
  quality_rejection_rate_pct: number;
  last_incident_note: string;
}

export interface ProductionLine {
  line_id: string;
  name: string;
  status: string;
  speed_pct: number;
  temp_celsius: number;
  daily_capacity_units: number;
  overtime_cost_per_hour_inr: number;
  extra_units_per_ot_hour: number;
  max_ot_hours: number;
}

export interface Order {
  order_id: string;
  client: string;
  required_qty: number;
  deadline_label: string;
  hours_remaining: number;
  sla_penalty_inr: number;
  partial_delay_penalty_inr: number;
  status: string;
  shortfall_units: number;
}

export interface AgentLog {
  id: number;
  run_id: string;
  step_order: number;
  agent_name: string;
  agent_role: string;
  badge_color: string;
  tool_called: string;
  tool_output_summary: string;
  message: string;
  created_at: string;
}

export interface VendorAllocation {
  supplier_id: string;
  supplier_name: string;
  tier: string;
  units_allocated: number;
  cost_per_unit_inr: number;
  flat_charter_cost_inr: number;
  total_cost_inr: number;
  lead_time_hours: number;
  route: string;
}

export interface PlaybookOption {
  id: string;
  name: string;
  strategy_type: string;
  vendor_allocations: VendorAllocation[];
  overtime_hours: number;
  overtime_cost_inr: number;
  supplier_cost_inr: number;
  total_mitigation_cost_inr: number;
  sla_penalty_prevented_inr: number;
  net_sla_saved_inr: number;
  roi_multiplier: number;
  confidence_pct: number;
  recommended: boolean;
  badge_label: string;
  description: string;
  tally_po_payload?: any;
  shift_broadcast_msg: string;
  client_sla_notice: string;
}

export type FactoryStatusMode = "NORMAL" | "CRISIS" | "PROTECTED";

interface FactoryState {
  factoryName: string;
  statusMode: FactoryStatusMode;
  activeScenarioId: number | null;
  suppliers: Supplier[];
  vendorHistory: VendorHistory[];
  productionLines: ProductionLine[];
  orders: Order[];
  agentLogs: AgentLog[];
  playbooks: PlaybookOption[];
  selectedPlaybookId: string | null;
  activeRunId: string | null;
  isSimulating: boolean;
  isExecuting: boolean;
  solveDurationMs: number;
  rebuttalOccurred: boolean;
  executionReceipt: any | null;
  isReceiptModalOpen: boolean;
  selectedNodeData: any | null;
  isInspectionDrawerOpen: boolean;
  nodes: Node[];
  edges: Edge[];
  dashboardViewMode: "EXECUTIVE" | "TWIN";
  isCustomCrisisModalOpen: boolean;

  // Actions
  fetchInitialState: () => Promise<void>;
  initRealtimeSubscriptions: () => () => void;
  simulateCrisis: (scenarioId?: number, customText?: string) => Promise<void>;
  executePlaybook: (playbookId: string) => Promise<void>;
  resetFactory: () => Promise<void>;
  setSelectedNodeData: (data: any) => void;
  closeInspectionDrawer: () => void;
  openReceiptModal: () => void;
  closeReceiptModal: () => void;
  setDashboardViewMode: (mode: "EXECUTIVE" | "TWIN") => void;
  openCustomCrisisModal: () => void;
  closeCustomCrisisModal: () => void;
  updateNodesAndEdges: () => void;
}

const API_BASE =
  typeof window !== "undefined"
    ? ""
    : process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─── Default 5 Node Coordinates (Left-to-Right Industrial Flow) ─────────────
const INITIAL_NODES: Node[] = [
  {
    id: "node-chennai",
    type: "chennaiSupplyNode",
    position: { x: 50, y: 70 },
    data: { id: "SUP-CHN-01", status: "ON_TIME", delayHours: 0, inboundQty: 500 },
  },
  {
    id: "node-peenya-hosur",
    type: "backupVendorNode",
    position: { x: 50, y: 340 },
    data: { status: "STANDBY", peenyaAllocated: 0, hosurAllocated: 0 },
  },
  {
    id: "node-line2",
    type: "weldingLine2Node",
    position: { x: 480, y: 70 },
    data: { id: "LINE-2", status: "NORMAL", speedPct: 100, tempC: 62.0, shortfall: 0 },
  },
  {
    id: "node-lines-buffer",
    type: "parallelBufferNode",
    position: { x: 480, y: 340 },
    data: { status: "NORMAL", otHours: 0, otRate: "₹22.5k/hr" },
  },
  {
    id: "node-order-sla",
    type: "orderSlaNode",
    position: { x: 920, y: 200 },
    data: {
      orderId: "EV-402",
      client: "Ather-Grid Mobility Corp",
      status: "ON_TRACK",
      shortfall: 0,
      penaltyExposure: 0,
      savedInr: 0,
    },
  },
];

const INITIAL_EDGES: Edge[] = [
  {
    id: "edge-chennai-line2",
    source: "node-chennai",
    target: "node-line2",
    animated: true,
    className: "animated-pipe-emerald",
  },
  {
    id: "edge-backup-buffer",
    source: "node-peenya-hosur",
    target: "node-lines-buffer",
    animated: true,
    className: "animated-pipe-amber",
  },
  {
    id: "edge-line2-order",
    source: "node-line2",
    target: "node-order-sla",
    animated: true,
    className: "animated-pipe-emerald",
  },
  {
    id: "edge-buffer-order",
    source: "node-lines-buffer",
    target: "node-order-sla",
    animated: true,
    className: "animated-pipe-sky",
  },
];

export const useFactoryStore = create<FactoryState>((set, get) => ({
  factoryName: "Apex Volt EV Battery Plant (Bengaluru Unit-2)",
  statusMode: "NORMAL",
  activeScenarioId: null,
  suppliers: [],
  vendorHistory: [],
  productionLines: [],
  orders: [],
  agentLogs: [],
  playbooks: [],
  selectedPlaybookId: null,
  activeRunId: null,
  isSimulating: false,
  isExecuting: false,
  solveDurationMs: 0,
  rebuttalOccurred: false,
  executionReceipt: null,
  isReceiptModalOpen: false,
  selectedNodeData: null,
  isInspectionDrawerOpen: false,
  nodes: INITIAL_NODES,
  edges: INITIAL_EDGES,
  dashboardViewMode: "EXECUTIVE",
  isCustomCrisisModalOpen: false,

  fetchInitialState: async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/state`);
      if (res.ok) {
        const data = await res.json();
        set({
          factoryName: data.factory_name || get().factoryName,
          suppliers: data.suppliers || [],
          vendorHistory: data.vendor_history || [],
          productionLines: data.production_lines || [],
          orders: data.orders || [],
          agentLogs: data.agent_logs || [],
        });
        get().updateNodesAndEdges();
      }
    } catch (err) {
      console.warn("FastAPI /state unreachable — using existing state", err);
    }
  },

  initRealtimeSubscriptions: () => {
    // 1. Subscribe to suppliers
    const chSuppliers = subscribeToTable("suppliers", undefined, (newRow) => {
      set((s) => ({
        suppliers: s.suppliers.map((sup) => (sup.id === newRow.id ? newRow : sup)),
      }));
      get().updateNodesAndEdges();
    });

    // 2. Subscribe to production_lines
    const chLines = subscribeToTable("production_lines", undefined, (newRow) => {
      set((s) => ({
        productionLines: s.productionLines.map((line) =>
          line.line_id === newRow.line_id ? newRow : line
        ),
      }));
      get().updateNodesAndEdges();
    });

    // 3. Subscribe to orders
    const chOrders = subscribeToTable("orders", undefined, (newRow) => {
      set((s) => ({
        orders: s.orders.map((ord) => (ord.order_id === newRow.order_id ? newRow : ord)),
      }));
      get().updateNodesAndEdges();
    });

    // 4. Subscribe to agent_logs (realtime stream to terminal)
    const chLogs = subscribeToTable("agent_logs", (newRow) => {
      set((s) => {
        // Prevent duplicate logs
        if (s.agentLogs.some((l) => l.id === newRow.id)) return s;
        return { agentLogs: [...s.agentLogs, newRow] };
      });
    });

    return () => {
      chSuppliers.unsubscribe();
      chLines.unsubscribe();
      chOrders.unsubscribe();
      chLogs.unsubscribe();
    };
  },

  simulateCrisis: async (scenarioId?: number, customText?: string) => {
    set({ isSimulating: true, activeScenarioId: scenarioId ?? null });
    try {
      const res = await fetch(`${API_BASE}/api/v1/simulate-crisis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario_id: scenarioId,
          raw_message: customText,
          source_channel: "WEB_DASHBOARD",
        }),
      });

      if (res.ok) {
        const data = await res.json();
        set({
          statusMode: "CRISIS",
          playbooks: data.playbooks || [],
          selectedPlaybookId: data.recommended_plan_id || null,
          activeRunId: data.run_id,
          solveDurationMs: data.solver_result?.solve_duration_ms || 28.5,
          rebuttalOccurred: data.rebuttal_occurred,
          isSimulating: false,
        });
        await get().fetchInitialState();
        get().updateNodesAndEdges();
      }
    } catch (err) {
      console.error("Simulation error", err);
      set({ isSimulating: false });
    }
  },

  executePlaybook: async (playbookId: string) => {
    const playbook = get().playbooks.find((p) => p.id === playbookId);
    if (!playbook) return;

    set({ isExecuting: true });
    try {
      const poNum = `PO-APEX-2026-${Math.floor(100 + Math.random() * 900)}`;
      const res = await fetch(`${API_BASE}/api/v1/execute-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          po_number: poNum,
          playbook_id: playbook.id,
          order_id: "EV-402",
          allocations: playbook.vendor_allocations,
          overtime_hours: playbook.overtime_hours,
          total_cost_inr: playbook.total_mitigation_cost_inr,
          net_sla_saved_inr: playbook.net_sla_saved_inr,
          confidence_pct: playbook.confidence_pct,
          client: "Ather-Grid Mobility Corp",
        }),
      });

      if (res.ok) {
        const receipt = await res.json();
        set({
          statusMode: "PROTECTED",
          executionReceipt: receipt,
          isReceiptModalOpen: true,
          isExecuting: false,
        });
        await get().fetchInitialState();
        get().updateNodesAndEdges();
      }
    } catch (err) {
      console.error("Execution error", err);
      set({ isExecuting: false });
    }
  },

  resetFactory: async () => {
    try {
      await fetch(`${API_BASE}/api/v1/reset`, { method: "POST" });
      set({
        statusMode: "NORMAL",
        activeScenarioId: null,
        playbooks: [],
        selectedPlaybookId: null,
        activeRunId: null,
        executionReceipt: null,
        agentLogs: [],
        isInspectionDrawerOpen: false,
      });
      await get().fetchInitialState();
      get().updateNodesAndEdges();
    } catch (err) {
      console.error("Reset error", err);
    }
  },

  setSelectedNodeData: (data: any) => {
    set({ selectedNodeData: data, isInspectionDrawerOpen: true });
  },

  closeInspectionDrawer: () => {
    set({ isInspectionDrawerOpen: false, selectedNodeData: null });
  },

  openReceiptModal: () => {
    set({ isReceiptModalOpen: true });
  },

  closeReceiptModal: () => {
    set({ isReceiptModalOpen: false });
  },

  setDashboardViewMode: (mode: "EXECUTIVE" | "TWIN") => {
    set({ dashboardViewMode: mode });
  },

  openCustomCrisisModal: () => {
    set({ isCustomCrisisModalOpen: true });
  },

  closeCustomCrisisModal: () => {
    set({ isCustomCrisisModalOpen: false });
  },

  updateNodesAndEdges: () => {
    const { suppliers, productionLines, orders, statusMode, playbooks, selectedPlaybookId } = get();

    const chn = suppliers.find((s) => s.id === "SUP-CHN-01");
    const l2 = productionLines.find((l) => l.line_id === "LINE-2");
    const ev402 = orders.find((o) => o.order_id === "EV-402");
    const selectedPlaybook = playbooks.find((p) => p.id === selectedPlaybookId);

    const isCrisis = statusMode === "CRISIS" || l2?.status?.includes("OVERHEAT");
    const isProtected = statusMode === "PROTECTED" || ev402?.status === "SLA_PROTECTED";

    // 1. Update Nodes Data
    const updatedNodes = INITIAL_NODES.map((node) => {
      if (node.id === "node-chennai") {
        return {
          ...node,
          data: {
            id: "SUP-CHN-01",
            name: chn?.name || "Chennai Precision Casings",
            status: chn?.status || (isCrisis ? "DELAYED" : "ON_TIME"),
            delayHours: chn?.delay_hours || (isCrisis ? 48 : 0),
            inboundQty: chn?.inbound_qty || 500,
            isCrisis,
            isProtected,
          },
        };
      }
      if (node.id === "node-peenya-hosur") {
        const peenyaAlloc = selectedPlaybook?.vendor_allocations.find((a) => a.supplier_id === "SUP-PNY-02")?.units_allocated || 0;
        const hosurAlloc = selectedPlaybook?.vendor_allocations.find((a) => a.supplier_id === "SUP-HSR-03")?.units_allocated || 0;
        return {
          ...node,
          data: {
            status: isProtected ? "DISPATCHED" : isCrisis ? "RECOVERY_STANDBY" : "STANDBY",
            peenyaAllocated: peenyaAlloc,
            hosurAllocated: hosurAlloc,
            isCrisis,
            isProtected,
          },
        };
      }
      if (node.id === "node-line2") {
        return {
          ...node,
          data: {
            id: "LINE-2",
            name: l2?.name || "Robotic Welding Line 2",
            status: l2?.status || (isCrisis ? "OVERHEATING_THROTTLED" : "NORMAL"),
            speedPct: l2?.speed_pct || (isCrisis ? 50 : 100),
            tempC: l2?.temp_celsius || (isCrisis ? 89.0 : 62.0),
            shortfall: ev402?.shortfall_units || (isCrisis ? 150 : 0),
            isCrisis,
            isProtected,
          },
        };
      }
      if (node.id === "node-lines-buffer") {
        return {
          ...node,
          data: {
            status: isProtected ? "OVERTIME_ACTIVE" : isCrisis ? "BUFFER_RESERVE" : "NORMAL",
            otHours: selectedPlaybook?.overtime_hours || (isCrisis ? 4 : 0),
            otRate: "₹22,500/hr",
            isCrisis,
            isProtected,
          },
        };
      }
      if (node.id === "node-order-sla") {
        return {
          ...node,
          data: {
            orderId: "EV-402",
            client: ev402?.client || "Ather-Grid Mobility Corp",
            status: isProtected ? "SLA_PROTECTED" : isCrisis ? "BREACH_RISK" : "ON_TRACK",
            shortfall: isProtected ? 0 : ev402?.shortfall_units || (isCrisis ? 150 : 0),
            penaltyExposure: isProtected ? 0 : isCrisis ? 2500000 : 0,
            savedInr: isProtected ? (selectedPlaybook?.net_sla_saved_inr || 2320000) : 0,
            isCrisis,
            isProtected,
          },
        };
      }
      return node;
    });

    // 2. Update Edges Pipe Glowing Classes
    const updatedEdges = INITIAL_EDGES.map((edge) => {
      if (edge.id === "edge-chennai-line2") {
        return {
          ...edge,
          className: isCrisis ? "animated-pipe-crimson" : "animated-pipe-emerald",
        };
      }
      if (edge.id === "edge-line2-order") {
        return {
          ...edge,
          className: isCrisis ? "animated-pipe-crimson" : "animated-pipe-emerald",
        };
      }
      if (edge.id === "edge-backup-buffer") {
        return {
          ...edge,
          className: isProtected ? "animated-pipe-emerald" : isCrisis ? "animated-pipe-amber" : "animated-pipe-sky",
        };
      }
      if (edge.id === "edge-buffer-order") {
        return {
          ...edge,
          className: isProtected ? "animated-pipe-emerald" : "animated-pipe-sky",
        };
      }
      return edge;
    });

    set({ nodes: updatedNodes, edges: updatedEdges });
  },
}));
