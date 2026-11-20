import type { Edge, Node } from "@xyflow/react";
import type {
  Order as OrderRow,
  PlaybookOption as Playbook,
  ProductionLine as ProductionLineRow,
  Supplier as SupplierRow,
} from "../store/useFactoryStore";

export interface FactoryVendor {
  supplier_id: string;
  name: string;
  sourcing_role: string;
  max_units: number;
  unit_cost: number;
  flat_cost: number;
  lead_hours: number;
  reliability_pct: number;
}

export interface FactoryLine {
  line_id: string;
  name: string;
  rated_units_per_hour: number;
  ot_units_per_hour: number;
  ot_cost_per_hour: number;
  max_ot_hours: number;
}

export interface FactoryInfo {
  factory_id: string;
  name: string;
  vendors: FactoryVendor[];
  lines: FactoryLine[];
}

export interface Scenario {
  scenario_id: number;
  title: string;
  summary: string;
  raw_message: string;
  delay_hours: number;
  shortfall_units: number;
  line_speeds: Record<string, number>;
  order_id: string;
}

export interface TwinGraphInput {
  factory: FactoryInfo;
  /** Rows from /api/v1/state (includes the PRIMARY supplier, which factory.vendors omits). */
  suppliers: SupplierRow[];
  lines: ProductionLineRow[];
  orders: OrderRow[];
  playbook?: Playbook | null;
  focusOrderId?: string | null;
}

const COL_X = { supplier: 0, line: 400, order: 800 } as const;
const ROW_Y = 180;

/** Line statuses that mean the line is a problem for everything downstream (single source of truth). */
export const PROBLEM_LINE_STATUSES = ["THROTTLED", "OVERHEATING_THROTTLED", "DOWN", "OVERHEATING"];
/** Supplier statuses that are a problem for everything downstream. */
export const PROBLEM_SUPPLIER_STATUSES = ["DELAYED"];

export function focusOrder(orders: OrderRow[], preferredOrderId?: string | null): OrderRow | null {
  if (!orders.length) return null;
  if (preferredOrderId) {
    const preferred = orders.find((o) => o.order_id === preferredOrderId);
    if (preferred) return preferred;
  }
  const byPenalty = (a: OrderRow, b: OrderRow) => (b.sla_penalty_inr ?? 0) - (a.sla_penalty_inr ?? 0);
  const atRisk = orders.filter((o) => o.status !== "ON_TRACK").sort(byPenalty);
  if (atRisk.length) return atRisk[0];
  return [...orders].sort(byPenalty)[0];
}

/** "Line B at 50% (89°C), Line C at 0% (95°C)" for every line that is not NORMAL; "" when none. */
export function throttledLinesText(lines: ProductionLineRow[]): string {
  return lines
    .filter((l) => l.status !== "NORMAL")
    .map((l) => `${l.name} at ${l.speed_pct}% (${l.temp_celsius}°C)`)
    .join(", ");
}

/** "Client #ID (500u) & Client #ID (300u)"; "" when there are no orders. */
export function ordersSummary(orders: OrderRow[]): string {
  return orders.map((o) => `${o.client} #${o.order_id} (${o.required_qty}u)`).join(" & ");
}

export function buildTwinGraph(input: TwinGraphInput): { nodes: Node[]; edges: Edge[] } {
  const { factory, playbook } = input;
  const roleById = new Map(factory.vendors.map((v) => [v.supplier_id, v.sourcing_role]));
  const vendorById = new Map(factory.vendors.map((v) => [v.supplier_id, v]));

  // Suppliers: every state row of this factory (incl. the primary), then any model vendor with no row yet.
  const supplierRows = input.suppliers.filter((s) =>
    s.factory_id ? s.factory_id === factory.factory_id : vendorById.has(s.id)
  );
  const seenSuppliers = new Set(supplierRows.map((s) => s.id));
  const supplierNodes = [
    ...supplierRows.map((s) => ({
      id: s.id,
      name: s.name,
      role: roleById.get(s.id) ?? s.sourcing_role ?? "SUPPLIER",
      status: s.status || "ON_TIME",
      delayHours: s.delay_hours ?? 0,
      inboundQty: s.inbound_qty ?? 0,
    })),
    ...factory.vendors
      .filter((v) => !seenSuppliers.has(v.supplier_id))
      .map((v) => ({
        id: v.supplier_id,
        name: v.name,
        role: v.sourcing_role,
        status: "ON_TIME",
        delayHours: 0,
        inboundQty: 0,
      })),
  ];

  const allocBySupplier = new Map<string, number>();
  for (const a of playbook?.vendor_allocations ?? []) {
    allocBySupplier.set(a.supplier_id, (allocBySupplier.get(a.supplier_id) ?? 0) + a.units_allocated);
  }
  const otByLine = playbook?.overtime_line_hours ?? {};

  const nodes: Node[] = [];

  supplierNodes.forEach((s, i) => {
    nodes.push({
      id: `supplier:${s.id}`,
      type: "supplier",
      position: { x: COL_X.supplier, y: i * ROW_Y },
      data: {
        supplierId: s.id,
        name: s.name,
        role: s.role,
        status: s.status,
        delayHours: s.delayHours,
        inboundQty: s.inboundQty,
        allocatedUnits: allocBySupplier.get(s.id) ?? 0,
      },
    });
  });

  const lineRowById = new Map(input.lines.map((l) => [l.line_id, l]));
  factory.lines.forEach((info, i) => {
    const row = lineRowById.get(info.line_id);
    nodes.push({
      id: `line:${info.line_id}`,
      type: "line",
      position: { x: COL_X.line, y: i * ROW_Y },
      data: {
        lineId: info.line_id,
        name: row?.name ?? info.name,
        status: row?.status ?? "NORMAL",
        speedPct: row?.speed_pct ?? 100,
        tempC: row?.temp_celsius ?? 0,
        otHours: otByLine[info.line_id] ?? 0,
      },
    });
  });

  const factoryOrders = input.orders.filter((o) => !o.factory_id || o.factory_id === factory.factory_id);
  const focus = focusOrder(factoryOrders, input.focusOrderId);
  factoryOrders.forEach((o, i) => {
    nodes.push({
      id: `order:${o.order_id}`,
      type: "order",
      position: { x: COL_X.order, y: i * ROW_Y },
      data: {
        orderId: o.order_id,
        client: o.client,
        status: o.status,
        shortfall: o.shortfall_units ?? 0,
        penaltyInr: o.sla_penalty_inr ?? 0,
        isFocus: focus?.order_id === o.order_id,
      },
    });
  });

  const edges: Edge[] = [];
  const edgeFor = (source: Node, target: Node): Edge => {
    const status = String(source.data.status);
    const problem =
      source.type === "line" ? PROBLEM_LINE_STATUSES.includes(status) : PROBLEM_SUPPLIER_STATUSES.includes(status);
    return {
      id: `${source.id}->${target.id}`,
      source: source.id,
      target: target.id,
      animated: problem,
      className: problem ? "animated-pipe-crimson" : "animated-pipe-emerald",
      style: problem ? { stroke: "#ff4757", strokeWidth: 2.5 } : undefined,
    };
  };
  const byType = (t: string) => nodes.filter((n) => n.type === t);
  for (const s of byType("supplier")) for (const l of byType("line")) edges.push(edgeFor(s, l));
  for (const l of byType("line")) for (const o of byType("order")) edges.push(edgeFor(l, o));

  return { nodes, edges };
}

export interface ShortfallParams {
  shortfall_units: number;
  shortfall_source: "override" | "inventory" | "alert_text";
  shortfall_breakdown?: { explanation?: string } | null;
  alert_stated_shortfall?: number | null;
}

/** One-line description of where the shortfall number came from. */
export function shortfallText(p: ShortfallParams): string {
  if (p.shortfall_source === "inventory") {
    const base = p.shortfall_breakdown?.explanation ?? `${p.shortfall_units} short (from inventory)`;
    return p.alert_stated_shortfall != null ? `${base} (alert said ${p.alert_stated_shortfall}; not used)` : base;
  }
  if (p.shortfall_source === "override") return `${p.shortfall_units} short (set manually)`;
  return `${p.shortfall_units} short (from the alert; no inventory data for this order)`;
}
