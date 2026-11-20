import { describe, expect, it } from "vitest";
import { buildTwinGraph, focusOrder, type FactoryInfo } from "./twinGraph";
import type { Order, PlaybookOption, ProductionLine, Supplier } from "../store/useFactoryStore";

const vendor = (id: string, role = "BACKUP") => ({
  supplier_id: id, name: `Vendor ${id}`, sourcing_role: role,
  max_units: 100, unit_cost: 10, flat_cost: 0, lead_hours: 6, reliability_pct: 90,
});
const lineInfo = (id: string) => ({
  line_id: id, name: `Line ${id}`, rated_units_per_hour: 10,
  ot_units_per_hour: 5, ot_cost_per_hour: 100, max_ot_hours: 8,
});
const sup = (id: string, extra: Partial<Supplier> = {}): Supplier => ({
  id, name: `Vendor ${id}`, tier: "T1", route: "r", part_name: "p", inbound_qty: 100,
  max_available_qty: 100, extra_cost_per_unit_inr: 1, flat_charter_cost_inr: 0,
  lead_time_hours: 4, traffic_risk_pct: 0, weather_risk_pct: 0,
  status: "ON_TIME", delay_hours: 0, factory_id: "F1", ...extra,
});
const line = (id: string, extra: Partial<ProductionLine> = {}): ProductionLine => ({
  line_id: id, name: `Line ${id}`, status: "NORMAL", speed_pct: 100, temp_celsius: 60,
  daily_capacity_units: 100, overtime_cost_per_hour_inr: 1, extra_units_per_ot_hour: 1,
  max_ot_hours: 8, factory_id: "F1", ...extra,
});
const order = (id: string, extra: Partial<Order> = {}): Order => ({
  order_id: id, client: `Client ${id}`, required_qty: 100, deadline_label: "x",
  hours_remaining: 10, sla_penalty_inr: 1000, partial_delay_penalty_inr: 0,
  status: "ON_TRACK", shortfall_units: 0, factory_id: "F1", ...extra,
});

const demoFactory: FactoryInfo = {
  factory_id: "F1", name: "Demo",
  vendors: [vendor("V1"), vendor("V2"), vendor("V3"), vendor("V4", "EXPEDITE")],
  lines: [lineInfo("L1"), lineInfo("L2"), lineInfo("L3")],
};
const demoInput = () => ({
  factory: demoFactory,
  suppliers: ["V1", "V2", "V3", "V4"].map((i) => sup(i)),
  lines: ["L1", "L2", "L3"].map((i) => line(i)),
  orders: [order("O1"), order("O2", { sla_penalty_inr: 5000 })],
});

describe("buildTwinGraph", () => {
  it("builds 9 nodes and 18 edges for the demo factory", () => {
    const g = buildTwinGraph(demoInput());
    expect(g.nodes).toHaveLength(9);
    expect(g.edges).toHaveLength(4 * 3 + 3 * 2);
    const ids = g.nodes.map((n) => n.id);
    expect(ids).toContain("supplier:V1");
    expect(ids).toContain("line:L2");
    expect(ids).toContain("order:O1");
  });

  it("lays out columns at x=0/400/800 and y=index*180", () => {
    const g = buildTwinGraph(demoInput());
    const s2 = g.nodes.find((n) => n.id === "supplier:V2")!;
    const l3 = g.nodes.find((n) => n.id === "line:L3")!;
    const o2 = g.nodes.find((n) => n.id === "order:O2")!;
    expect(s2.position).toEqual({ x: 0, y: 180 });
    expect(l3.position).toEqual({ x: 400, y: 360 });
    expect(o2.position).toEqual({ x: 800, y: 180 });
    expect(s2.type).toBe("supplier");
  });

  it("builds 5 nodes and 6 edges for a 2-vendor/2-line/1-order factory", () => {
    const g = buildTwinGraph({
      factory: { factory_id: "F1", name: "S", vendors: [vendor("V1"), vendor("V2")], lines: [lineInfo("L1"), lineInfo("L2")] },
      suppliers: [sup("V1"), sup("V2")],
      lines: [line("L1"), line("L2")],
      orders: [order("O1")],
    });
    expect(g.nodes).toHaveLength(5);
    expect(g.edges).toHaveLength(2 * 2 + 2 * 1);
  });

  it("animates outgoing edges of a DELAYED supplier", () => {
    const input = demoInput();
    input.suppliers[0] = sup("V1", { status: "DELAYED", delay_hours: 48 });
    const g = buildTwinGraph(input);
    const out = g.edges.filter((e) => e.source === "supplier:V1");
    expect(out).toHaveLength(3);
    expect(out.every((e) => e.animated)).toBe(true);
    expect(g.edges.filter((e) => e.source === "supplier:V2").every((e) => !e.animated)).toBe(true);
  });

  it("animates outgoing edges of a THROTTLED line", () => {
    const input = demoInput();
    input.lines[1] = line("L2", { status: "THROTTLED", speed_pct: 50 });
    const g = buildTwinGraph(input);
    expect(g.edges.filter((e) => e.source === "line:L2").every((e) => e.animated)).toBe(true);
  });

  it("shows playbook allocations and overtime hours", () => {
    const playbook = {
      vendor_allocations: [{ supplier_id: "V1", units_allocated: 60 }],
      overtime_line_hours: { L2: 3 },
    } as unknown as PlaybookOption;
    const g = buildTwinGraph({ ...demoInput(), playbook });
    expect(g.nodes.find((n) => n.id === "supplier:V1")!.data.allocatedUnits).toBe(60);
    expect(g.nodes.find((n) => n.id === "supplier:V2")!.data.allocatedUnits).toBe(0);
    expect(g.nodes.find((n) => n.id === "line:L2")!.data.otHours).toBe(3);
  });

  it("excludes orders of another factory", () => {
    const input = demoInput();
    input.orders.push(order("OX", { factory_id: "OTHER" }));
    const g = buildTwinGraph(input);
    expect(g.nodes.find((n) => n.id === "order:OX")).toBeUndefined();
    expect(g.nodes.filter((n) => n.type === "order")).toHaveLength(2);
  });

  it("includes the primary supplier (not in factory.vendors) and uses its own role", () => {
    const input = demoInput();
    input.suppliers.unshift(sup("PRIM", { sourcing_role: "PRIMARY", status: "DELAYED", delay_hours: 48 }));
    input.suppliers.push(sup("ELSEWHERE", { factory_id: "OTHER" }));
    const g = buildTwinGraph(input);
    expect(g.nodes.find((n) => n.id === "supplier:PRIM")!.data.role).toBe("PRIMARY");
    expect(g.nodes.find((n) => n.id === "supplier:ELSEWHERE")).toBeUndefined();
    expect(g.nodes.find((n) => n.id === "supplier:V4")!.data.role).toBe("EXPEDITE");
  });

  it("marks the focus order", () => {
    const g = buildTwinGraph({ ...demoInput(), focusOrderId: "O1" });
    expect(g.nodes.find((n) => n.id === "order:O1")!.data.isFocus).toBe(true);
    expect(g.nodes.find((n) => n.id === "order:O2")!.data.isFocus).toBe(false);
  });
});

describe("focusOrder", () => {
  const orders = [
    order("A", { sla_penalty_inr: 100, status: "ON_TRACK" }),
    order("B", { sla_penalty_inr: 300, status: "BREACH_RISK" }),
    order("C", { sla_penalty_inr: 200, status: "BREACH_RISK" }),
    order("D", { sla_penalty_inr: 900, status: "ON_TRACK" }),
  ];
  it("prefers the given id", () => expect(focusOrder(orders, "A")?.order_id).toBe("A"));
  it("otherwise picks the highest-penalty at-risk order", () => expect(focusOrder(orders)?.order_id).toBe("B"));
  it("falls back to highest penalty when none at risk", () =>
    expect(focusOrder([orders[0], orders[3]])?.order_id).toBe("D"));
  it("ignores an unknown preferred id", () => expect(focusOrder(orders, "ZZ")?.order_id).toBe("B"));
  it("returns null for no orders", () => expect(focusOrder([])).toBeNull());
});
