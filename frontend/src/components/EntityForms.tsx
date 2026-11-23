"use client";

import React, { useState } from "react";
import { callApi } from "@/lib/api";
import {
  RISK_PROFILES,
  SOURCING_ROLES,
  hasErrors,
  optNum,
  parseNum,
  slugify,
  validateFactory,
  validateLine,
  validateOrder,
  validateSupplier,
  type Errors,
} from "@/lib/forms";
import { Banner, Btn, Field, INPUT } from "./ui";

type Vals = Record<string, string>;

function useValues(initial: Vals) {
  const [v, setV] = useState<Vals>(initial);
  const [errors, setErrors] = useState<Errors>({});
  const [apiError, setApiError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV((p) => ({ ...p, [k]: e.target.value }));
  return { v, set, errors, setErrors, apiError, setApiError, busy, setBusy };
}

function Actions({ busy, onCancel, label }: { busy: boolean; onCancel?: () => void; label: string }) {
  return (
    <div className="flex gap-2 pt-2">
      <Btn type="submit" busy={busy}>{label}</Btn>
      {onCancel && <Btn variant="quiet" onClick={onCancel}>Cancel</Btn>}
    </div>
  );
}

const str = (x: unknown) => (x == null ? "" : String(x));

/** Shared submit: validate, call the API, show the server's message verbatim. */
function useSubmit(form: ReturnType<typeof useValues>, validate: (v: Vals) => Errors, run: (v: Vals) => Promise<{ ok: boolean; error: string; data: any }>, onDone: (data: any) => void) {
  return async (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validate(form.v);
    form.setErrors(errs);
    form.setApiError("");
    if (hasErrors(errs)) return;
    form.setBusy(true);
    const r = await run(form.v);
    form.setBusy(false);
    if (!r.ok) return form.setApiError(r.error);
    onDone(r.data);
  };
}

/* ── Production line ─────────────────────────────────────────────────────── */

export function LineForm({ initial, onDone, onCancel }: { initial?: any; onDone: (row?: any) => void; onCancel?: () => void }) {
  const f = useValues({
    name: str(initial?.name),
    rated_units_per_hour: str(initial?.rated_units_per_hour),
    ot_units_per_hour: str(initial?.ot_units_per_hour),
    ot_cost_per_hour: str(initial?.ot_cost_per_hour),
    max_ot_hours: str(initial?.max_ot_hours),
  });
  const submit = useSubmit(f, validateLine, (v) => {
    const body = {
      name: v.name.trim(),
      rated_units_per_hour: parseNum(v.rated_units_per_hour),
      ot_units_per_hour: optNum(v.ot_units_per_hour) ?? 0,
      ot_cost_per_hour: optNum(v.ot_cost_per_hour) ?? 0,
      max_ot_hours: optNum(v.max_ot_hours) ?? 0,
    };
    return initial ? callApi(`/api/v1/lines/${encodeURIComponent(initial.line_id)}`, "PATCH", body) : callApi("/api/v1/lines", "POST", body);
  }, onDone);
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label="Line name" error={f.errors.name}><input className={INPUT} value={f.v.name} onChange={f.set("name")} placeholder="Line A" /></Field>
      <Field label="Normal speed (units per hour)" error={f.errors.rated_units_per_hour}><input className={INPUT} inputMode="decimal" value={f.v.rated_units_per_hour} onChange={f.set("rated_units_per_hour")} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Extra units per overtime hour" error={f.errors.ot_units_per_hour}><input className={INPUT} inputMode="decimal" value={f.v.ot_units_per_hour} onChange={f.set("ot_units_per_hour")} placeholder="0" /></Field>
        <Field label="Overtime cost per hour (₹)" error={f.errors.ot_cost_per_hour}><input className={INPUT} inputMode="decimal" value={f.v.ot_cost_per_hour} onChange={f.set("ot_cost_per_hour")} placeholder="0" /></Field>
      </div>
      <Field label="Most overtime hours you would run" error={f.errors.max_ot_hours} hint="Leave empty if this line never runs overtime."><input className={INPUT} inputMode="numeric" value={f.v.max_ot_hours} onChange={f.set("max_ot_hours")} placeholder="0" /></Field>
      {f.apiError && <Banner>{f.apiError}</Banner>}
      <Actions busy={f.busy} onCancel={onCancel} label={initial ? "Save changes" : "Add line"} />
    </form>
  );
}

/* ── Supplier ────────────────────────────────────────────────────────────── */

export function SupplierForm({ initial, onDone, onCancel }: { initial?: any; onDone: (row?: any) => void; onCancel?: () => void }) {
  const rel = initial?.reliability;
  const f = useValues({
    name: str(initial?.name),
    sourcing_role: str(initial?.sourcing_role),
    route: str(initial?.route),
    max_units: str(initial?.max_units),
    lead_hours: str(initial?.lead_hours),
    unit_cost: str(initial?.unit_cost),
    flat_cost: str(initial?.flat_cost),
    min_lead_hours: initial && initial.min_lead_hours !== initial.lead_hours ? str(initial.min_lead_hours) : "",
    risk_profile: str(initial?.risk_profile),
    past_orders: rel?.past_orders ? str(rel.past_orders) : "",
    on_time: rel?.past_orders ? str(rel.on_time) : "",
  });
  const submit = useSubmit(f, validateSupplier, (v) => {
    const body: Record<string, unknown> = {
      name: v.name.trim(),
      sourcing_role: v.sourcing_role,
      route: v.route.trim(),
      max_units: parseNum(v.max_units),
      lead_hours: parseNum(v.lead_hours),
      unit_cost: optNum(v.unit_cost) ?? 0,
      flat_cost: optNum(v.flat_cost) ?? 0,
      risk_profile: v.risk_profile,
    };
    if (optNum(v.min_lead_hours) !== undefined) body.min_lead_hours = optNum(v.min_lead_hours);
    if (optNum(v.past_orders) !== undefined) {
      body.past_orders = optNum(v.past_orders);
      body.on_time = optNum(v.on_time);
    }
    return initial ? callApi(`/api/v1/suppliers/${encodeURIComponent(initial.id)}`, "PATCH", body) : callApi("/api/v1/suppliers", "POST", body);
  }, onDone);
  const profile = f.v.risk_profile as keyof typeof RISK_PROFILES;
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label="Supplier name" error={f.errors.name}><input className={INPUT} value={f.v.name} onChange={f.set("name")} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Role" error={f.errors.sourcing_role}>
          <select className={INPUT} value={f.v.sourcing_role} onChange={f.set("sourcing_role")}>
            <option value="">Choose…</option>
            {SOURCING_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </Field>
        <Field label="Route" error={f.errors.route}><input className={INPUT} value={f.v.route} onChange={f.set("route")} placeholder="Chennai to Bengaluru" /></Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Most units they can supply" error={f.errors.max_units}><input className={INPUT} inputMode="numeric" value={f.v.max_units} onChange={f.set("max_units")} /></Field>
        <Field label="Delivery time (hours)" error={f.errors.lead_hours}><input className={INPUT} inputMode="numeric" value={f.v.lead_hours} onChange={f.set("lead_hours")} /></Field>
        <Field label="Price per unit (₹)" error={f.errors.unit_cost}><input className={INPUT} inputMode="decimal" value={f.v.unit_cost} onChange={f.set("unit_cost")} placeholder="0" /></Field>
        <Field label="Fixed charge (₹)" error={f.errors.flat_cost} hint="For a charter or express run."><input className={INPUT} inputMode="decimal" value={f.v.flat_cost} onChange={f.set("flat_cost")} placeholder="0" /></Field>
      </div>
      <Field label="How reliable are they?" error={f.errors.risk_profile} hint={profile in RISK_PROFILES ? RISK_PROFILES[profile] : "Pick the one that sounds most like this supplier."}>
        <select className={INPUT} value={f.v.risk_profile} onChange={f.set("risk_profile")}>
          <option value="">Choose…</option>
          <option value="low">Low risk</option>
          <option value="medium">Medium risk</option>
          <option value="high">High risk</option>
        </select>
      </Field>
      <details className="rounded-xl border border-rule p-3">
        <summary className="cursor-pointer text-sm font-semibold">Optional: delivery history</summary>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Field label="Past orders" error={f.errors.past_orders}><input className={INPUT} inputMode="numeric" value={f.v.past_orders} onChange={f.set("past_orders")} /></Field>
          <Field label="Of those, on time" error={f.errors.on_time}><input className={INPUT} inputMode="numeric" value={f.v.on_time} onChange={f.set("on_time")} /></Field>
          <Field label="Fastest delivery (hours)" error={f.errors.min_lead_hours} className="col-span-2" hint="Only if they can beat their usual time."><input className={INPUT} inputMode="numeric" value={f.v.min_lead_hours} onChange={f.set("min_lead_hours")} /></Field>
        </div>
      </details>
      {f.apiError && <Banner>{f.apiError}</Banner>}
      <Actions busy={f.busy} onCancel={onCancel} label={initial ? "Save changes" : "Add supplier"} />
    </form>
  );
}

/* ── Order ───────────────────────────────────────────────────────────────── */

export function OrderForm({ initial, onDone, onCancel }: { initial?: any; onDone: (row?: any) => void; onCancel?: () => void }) {
  const initialHours = initial?.hours_remaining != null ? String(Math.max(1, Math.round(initial.hours_remaining))) : "";
  const f = useValues({
    client: str(initial?.client),
    required_qty: str(initial?.required_qty),
    hours_remaining: initialHours,
    sla_penalty_inr: str(initial?.sla_penalty_inr),
    partial_delay_penalty_inr: str(initial?.partial_delay_penalty_inr),
  });
  const submit = useSubmit(f, validateOrder, (v) => {
    const body: Record<string, unknown> = {
      client: v.client.trim(),
      required_qty: parseNum(v.required_qty),
      sla_penalty_inr: parseNum(v.sla_penalty_inr),
      partial_delay_penalty_inr: optNum(v.partial_delay_penalty_inr) ?? 0,
    };
    if (!initial || v.hours_remaining !== initialHours) body.hours_remaining = parseNum(v.hours_remaining);
    return initial ? callApi(`/api/v1/orders/${encodeURIComponent(initial.order_id)}`, "PATCH", body) : callApi("/api/v1/orders", "POST", body);
  }, onDone);
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label="Customer" error={f.errors.client}><input className={INPUT} value={f.v.client} onChange={f.set("client")} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Quantity (units)" error={f.errors.required_qty}><input className={INPUT} inputMode="numeric" value={f.v.required_qty} onChange={f.set("required_qty")} /></Field>
        <Field label="Due in (hours)" error={f.errors.hours_remaining}><input className={INPUT} inputMode="numeric" value={f.v.hours_remaining} onChange={f.set("hours_remaining")} /></Field>
      </div>
      <Field label="Penalty if late (₹)" error={f.errors.sla_penalty_inr} hint="What the customer charges if this order misses its date."><input className={INPUT} inputMode="decimal" value={f.v.sla_penalty_inr} onChange={f.set("sla_penalty_inr")} /></Field>
      <Field label="Penalty for a short delay (₹)" error={f.errors.partial_delay_penalty_inr} hint="Optional. Used when you ask the customer for a little more time."><input className={INPUT} inputMode="decimal" value={f.v.partial_delay_penalty_inr} onChange={f.set("partial_delay_penalty_inr")} placeholder="0" /></Field>
      {f.apiError && <Banner>{f.apiError}</Banner>}
      <Actions busy={f.busy} onCancel={onCancel} label={initial ? "Save changes" : "Add order"} />
    </form>
  );
}

/* ── Factory basics (create in the wizard, edit on the Factory page) ─────── */

export function FactoryForm({ initial, onDone, onCancel, label }: { initial?: any; onDone: (row?: any) => void; onCancel?: () => void; label?: string }) {
  const f = useValues({
    name: str(initial?.name),
    stock_item_code: str(initial?.stock_item_code),
    stock_item_name: str(initial?.stock_item_name),
    qa_dispatch_hours: str(initial?.qa_dispatch_hours ?? ""),
    safety_stock_units: str(initial?.safety_stock_units ?? ""),
    production_hours_in_window: str(initial?.production_hours_in_window ?? ""),
  });
  const submit = useSubmit(f, validateFactory, (v) => {
    const body: Record<string, unknown> = {
      name: v.name.trim(),
      stock_item_name: v.stock_item_name.trim(),
      qa_dispatch_hours: parseNum(v.qa_dispatch_hours),
      safety_stock_units: parseNum(v.safety_stock_units),
      production_hours_in_window: parseNum(v.production_hours_in_window),
    };
    if (initial) return callApi("/api/v1/factory/settings", "PATCH", body);
    return callApi("/api/v1/factories", "POST", { ...body, id: slugify(v.name) || undefined, stock_item_code: v.stock_item_code.trim() });
  }, onDone);
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label="Factory name" error={f.errors.name}><input className={INPUT} value={f.v.name} onChange={f.set("name")} placeholder="Apex Volt, Bengaluru" /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Main part you make" error={f.errors.stock_item_name}><input className={INPUT} value={f.v.stock_item_name} onChange={f.set("stock_item_name")} placeholder="Battery pack" /></Field>
        <Field label="Part code" error={f.errors.stock_item_code} hint={initial ? "The code can't be changed." : undefined}>
          <input className={INPUT} value={f.v.stock_item_code} onChange={f.set("stock_item_code")} placeholder="BP-01" disabled={Boolean(initial)} />
        </Field>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Field label="Quality check + dispatch (hours)" error={f.errors.qa_dispatch_hours}><input className={INPUT} inputMode="decimal" value={f.v.qa_dispatch_hours} onChange={f.set("qa_dispatch_hours")} /></Field>
        <Field label="Safety stock (units)" error={f.errors.safety_stock_units} hint="Stock you never want to dip below."><input className={INPUT} inputMode="numeric" value={f.v.safety_stock_units} onChange={f.set("safety_stock_units")} /></Field>
        <Field label="Working hours before a deadline" error={f.errors.production_hours_in_window}><input className={INPUT} inputMode="decimal" value={f.v.production_hours_in_window} onChange={f.set("production_hours_in_window")} /></Field>
      </div>
      {f.apiError && <Banner>{f.apiError}</Banner>}
      <Actions busy={f.busy} onCancel={onCancel} label={label ?? (initial ? "Save changes" : "Create my factory")} />
    </form>
  );
}
