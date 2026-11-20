import { create } from "zustand";
import { Edge, Node } from "@xyflow/react";
import { subscribeToTable } from "@/lib/supabase";
import { buildTwinGraph, type FactoryInfo, type Scenario } from "@/lib/twinGraph";

export type { FactoryInfo, Scenario };

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
  factory_id?: string | null;
  sourcing_role?: string | null;
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
  factory_id?: string | null;
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
  factory_id?: string | null;
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
  overtime_line_hours?: Record<string, number>;   // overtime hours per production line id
  overtime_cost_inr: number;
  supplier_cost_inr: number;
  total_mitigation_cost_inr: number;
  sla_penalty_prevented_inr: number;
  net_sla_saved_inr: number;
  roi_multiplier: number;
  confidence_pct: number;
  confidence_ci_low_pct?: number | null;
  confidence_ci_high_pct?: number | null;
  p90_finish_hours?: number | null;
  expected_cost_inr: number;
  feasible: boolean;
  uncovered_units: number;
  recommended: boolean;
  badge_label: string;
  description: string;
  tally_po_payload?: any;
  shift_broadcast_msg: string;
  client_sla_notice: string;
}

export interface AiMode {
  overall: "llm" | "mixed" | "fallback";
  model: string | null;
  note: string;
  trace: { node: string; mode: string }[];
}

export interface SolverMeta {
  lp_status: string;
  ranking_rule: string;
  deadline_hours: number;
  capacity_exhausted: boolean;
  throughput_gap_units: number;
}

/** Order statuses that mean a recovery plan has been approved (not that delivery is guaranteed). */
export const RECOVERY_STATUSES = ["RECOVERY_IN_PROGRESS", "EXTENSION_REQUESTED", "RISK_ACCEPTED", "SLA_PROTECTED"];

export interface Rfq {
  id: string;
  round: number;
  supplier_id: string;
  supplier_name: string;
  units_requested: number;
  expected_unit_price_inr: number;
  needed_within_hours: number;
  channel: string;
  status: "SENT" | "CONFIRMED" | "PARTIAL" | "DECLINED" | "NO_REPLY" | "SEND_FAILED";
  offered_units: number | null;
  offered_unit_price_inr: number | null;
  offered_eta_hours: number | null;
  reply_text: string;
  parsed_by: string;
}

export interface SourcingState {
  run_id: string;
  playbook_id: string;
  status: "ACTIVE" | "COMPLETE" | "COMPLETE_UNCONFIRMED" | "NOTHING_TO_SOURCE";
  mode: string;
  round: number;
  max_rounds: number;
  reply_timeout_min: number;
  rfqs: Rfq[];
  events: string[];
  sourced_run_id: string | null;
  playbooks: PlaybookOption[];
  recommended_plan_id: string | null;
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
  rebuttalNotes: string[];
  aiMode: AiMode | null;
  solverMeta: SolverMeta | null;
  lastError: string | null;
  sourcing: SourcingState | null;
  isSourcingBusy: boolean;
  executionReceipt: any | null;
  isReceiptModalOpen: boolean;
  selectedNodeData: any | null;
  isInspectionDrawerOpen: boolean;
  nodes: Node[];
  edges: Edge[];
  dashboardViewMode: "EXECUTIVE" | "TWIN";
  isCustomCrisisModalOpen: boolean;
  factory: FactoryInfo | null;
  factoryError: string | null;
  scenarios: Scenario[];
  activeOrderId: string | null;

  // Actions
  fetchInitialState: () => Promise<void>;
  initRealtimeSubscriptions: () => () => void;
  simulateCrisis: (scenarioId?: number, customText?: string) => Promise<void>;
  simulateCustom: (input: {
    raw_message?: string;
    override_delay_hours?: number;
    override_shortfall_units?: number;
    override_line_speeds?: Record<string, number>;
    order_id?: string;
  }) => Promise<void>;
  executePlaybook: (playbookId: string) => Promise<void>;
  startSourcing: () => Promise<void>;
  refreshSourcing: () => Promise<void>;
  submitVendorReply: (supplierId: string, text: string) => Promise<void>;
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

export const useFactoryStore = create<FactoryState>((set, get) => {
  /** Store sourcing state; once the agent finishes, switch the dashboard to the confirmed plan. */
  const applySourcing = (data: SourcingState) => {
    set({ sourcing: data });
    if (data.sourced_run_id && data.playbooks?.length && get().activeRunId !== data.sourced_run_id) {
      set({
        activeRunId: data.sourced_run_id,
        playbooks: data.playbooks,
        selectedPlaybookId: data.recommended_plan_id,
      });
      get().updateNodesAndEdges();
    }
  };

  /** POST /simulate-crisis with the given body, then store the plans and refresh the twin. */
  const runSimulation = async (payload: Record<string, unknown>, scenarioId: number | null) => {
    set({ isSimulating: true, activeScenarioId: scenarioId, lastError: null, sourcing: null });
    try {
      const res = await fetch(`${API_BASE}/api/v1/simulate-crisis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, source_channel: "WEB_DASHBOARD" }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Simulation failed (HTTP ${res.status})`);
      }
      const data = await res.json();
      const sr = data.solver_result || {};
      set({
        statusMode: "CRISIS",
        playbooks: data.playbooks || [],
        selectedPlaybookId: data.recommended_plan_id || null,
        activeRunId: data.run_id,
        activeOrderId: data.extracted_parameters?.affected_order_id ?? null,
        solveDurationMs: sr.solve_duration_ms ?? 0,
        rebuttalOccurred: !!data.rebuttal_occurred,
        rebuttalNotes: data.rebuttal_notes || [],
        aiMode: data.ai_mode || null,
        solverMeta: {
          lp_status: sr.lp_status || "",
          ranking_rule: sr.ranking_rule || "",
          deadline_hours: sr.deadline_hours ?? 0,
          capacity_exhausted: !!sr.capacity_exhausted,
          throughput_gap_units: sr.throughput_gap_units ?? 0,
        },
      });
      await get().fetchInitialState();
    } catch (err) {
      console.error("Simulation error", err);
      set({ lastError: err instanceof Error ? err.message : "Simulation failed" });
    } finally {
      set({ isSimulating: false });
    }
  };

  return {
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
  rebuttalNotes: [],
  aiMode: null,
  solverMeta: null,
  lastError: null,
  sourcing: null,
  isSourcingBusy: false,
  executionReceipt: null,
  isReceiptModalOpen: false,
  selectedNodeData: null,
  isInspectionDrawerOpen: false,
  nodes: [],
  edges: [],
  dashboardViewMode: "EXECUTIVE",
  isCustomCrisisModalOpen: false,
  factory: null,
  factoryError: null,
  scenarios: [],
  activeOrderId: null,

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
      }
    } catch (err) {
      console.warn("FastAPI /state unreachable — using existing state", err);
    }

    // The twin is built from the factory model; load it (and the presets) until it succeeds.
    if (!get().factory) {
      try {
        const res = await fetch(`${API_BASE}/api/v1/factory`);
        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          throw new Error(detail.detail || `Factory model unavailable (HTTP ${res.status})`);
        }
        set({ factory: (await res.json()) as FactoryInfo, factoryError: null });
      } catch (err) {
        set({ factoryError: err instanceof Error ? err.message : "Factory model unavailable" });
      }
      try {
        const res = await fetch(`${API_BASE}/api/v1/scenarios`);
        if (res.ok) set({ scenarios: (await res.json()) as Scenario[] });
      } catch {
        // presets are optional; custom disruptions still work
      }
    }
    get().updateNodesAndEdges();
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

  simulateCrisis: async (scenarioId?: number, customText?: string) =>
    runSimulation({ scenario_id: scenarioId, raw_message: customText }, scenarioId ?? null),

  simulateCustom: async (input) => runSimulation(input, null),

  executePlaybook: async (playbookId: string) => {
    const { activeRunId, playbooks } = get();
    const playbook = playbooks.find((p) => p.id === playbookId);
    if (!playbook || !activeRunId) return;

    set({ isExecuting: true, lastError: null });
    try {
      // The server executes the plan it computed for this run; no costs are sent from the browser.
      const res = await fetch(`${API_BASE}/api/v1/execute-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: activeRunId,
          playbook_id: playbook.id,
          approved_by: "dashboard-operator",
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Execution failed (HTTP ${res.status})`);
      }
      const receipt = await res.json();
      set({
        statusMode: "PROTECTED",
        executionReceipt: receipt,
        isReceiptModalOpen: true,
        selectedPlaybookId: playbook.id,
      });
      await get().fetchInitialState();
      get().updateNodesAndEdges();
    } catch (err) {
      console.error("Execution error", err);
      set({ lastError: err instanceof Error ? err.message : "Execution failed" });
    } finally {
      set({ isExecuting: false });
    }
  },

  startSourcing: async () => {
    const { activeRunId, selectedPlaybookId } = get();
    if (!activeRunId) return;
    set({ isSourcingBusy: true, lastError: null });
    try {
      const res = await fetch(`${API_BASE}/api/v1/sourcing/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: activeRunId, playbook_id: selectedPlaybookId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Could not start sourcing (HTTP ${res.status})`);
      applySourcing(data);
    } catch (err) {
      set({ lastError: err instanceof Error ? err.message : "Could not start sourcing" });
    } finally {
      set({ isSourcingBusy: false });
    }
  },

  refreshSourcing: async () => {
    const sourcing = get().sourcing;
    if (!sourcing) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/sourcing/${encodeURIComponent(sourcing.run_id)}`);
      if (res.ok) applySourcing(await res.json());
    } catch {
      // keep last known state; the panel shows it
    }
  },

  submitVendorReply: async (supplierId: string, text: string) => {
    const sourcing = get().sourcing;
    if (!sourcing || !text.trim()) return;
    set({ isSourcingBusy: true, lastError: null });
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/sourcing/${encodeURIComponent(sourcing.run_id)}/vendor-reply`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ supplier_id: supplierId, text }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Could not record reply (HTTP ${res.status})`);
      applySourcing(data);
    } catch (err) {
      set({ lastError: err instanceof Error ? err.message : "Could not record reply" });
    } finally {
      set({ isSourcingBusy: false });
    }
  },

  resetFactory: async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/reset`, { method: "POST" });
      if (!res.ok) throw new Error(`Reset failed (HTTP ${res.status})`);
      set({
        lastError: null,
        sourcing: null,
        aiMode: null,
        solverMeta: null,
        rebuttalNotes: [],
        statusMode: "NORMAL",
        activeScenarioId: null,
        playbooks: [],
        selectedPlaybookId: null,
        activeRunId: null,
        activeOrderId: null,
        executionReceipt: null,
        agentLogs: [],
        isInspectionDrawerOpen: false,
      });
      await get().fetchInitialState();
      get().updateNodesAndEdges();
    } catch (err) {
      console.error("Reset error", err);
      set({ lastError: err instanceof Error ? err.message : "Reset failed" });
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
    const { factory, suppliers, productionLines, orders, playbooks, selectedPlaybookId, activeOrderId } = get();
    if (!factory) {
      set({ nodes: [], edges: [] });
      return;
    }
    const { nodes, edges } = buildTwinGraph({
      factory,
      suppliers,
      lines: productionLines,
      orders,
      playbook: playbooks.find((p) => p.id === selectedPlaybookId) ?? null,
      focusOrderId: activeOrderId,
    });
    set({ nodes, edges });
  },
};
});
