/** Pure validators for the setup forms. Each returns a map of field -> message (empty = valid). */
export type Errors = Record<string, string>;

export const RISK_PROFILES = {
  low: "Reliable: almost always on time, delays are rare and short.",
  medium: "Usual: sometimes a few hours late, typical for a road supplier.",
  high: "Unreliable: often late, and delays can run into most of a day.",
} as const;
export type RiskProfile = keyof typeof RISK_PROFILES;

export const SOURCING_ROLES = [
  { value: "PRIMARY", label: "Main supplier" },
  { value: "BACKUP", label: "Backup" },
  { value: "EXPEDITE", label: "Express (charter, air)" },
] as const;

export function parseNum(s: string | number | null | undefined): number | null {
  if (typeof s === "number") return Number.isFinite(s) ? s : null;
  if (s == null) return null;
  const t = String(s).replace(/[,₹\s]/g, "");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export function isEmail(s: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s.trim());
}

/** Lower-case id from a name, e.g. "Apex Volt (Blr-2)" -> "apex-volt-blr-2". */
export function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 63);
}

type Raw = Record<string, string | number | null | undefined>;
interface NumOpts { min?: number; max?: number; positive?: boolean; int?: boolean; optional?: boolean }

function required(v: Raw, key: string, label: string, e: Errors) {
  if (String(v[key] ?? "").trim() === "") e[key] = `${label} is required`;
}

function number(v: Raw, key: string, label: string, e: Errors, opts: NumOpts = {}) {
  const raw = v[key];
  if (raw == null || String(raw).trim() === "") {
    if (!opts.optional) e[key] = `${label} is required`;
    return;
  }
  const n = parseNum(raw);
  if (n === null) return void (e[key] = `${label} must be a number`);
  if (opts.int && !Number.isInteger(n)) return void (e[key] = `${label} must be a whole number`);
  if (opts.positive && n <= 0) return void (e[key] = `${label} must be more than 0`);
  if (n < (opts.min ?? 0)) return void (e[key] = `${label} can't be below ${opts.min ?? 0}`);
  if (opts.max !== undefined && n > opts.max) e[key] = `${label} can't be above ${opts.max}`;
}

export function validateFactory(v: Raw): Errors {
  const e: Errors = {};
  required(v, "name", "Factory name", e);
  required(v, "stock_item_code", "Part code", e);
  required(v, "stock_item_name", "Part name", e);
  if (v.stock_item_code && !/^[A-Za-z0-9._-]{1,40}$/.test(String(v.stock_item_code))) {
    e.stock_item_code = "Part code: letters, digits, '.', '_' or '-' only";
  }
  number(v, "qa_dispatch_hours", "Quality check and dispatch time", e, { max: 720 });
  number(v, "safety_stock_units", "Safety stock", e, { int: true });
  number(v, "production_hours_in_window", "Working hours before the deadline", e, { positive: true, max: 8760 });
  return e;
}

export function validateLine(v: Raw): Errors {
  const e: Errors = {};
  required(v, "name", "Line name", e);
  number(v, "rated_units_per_hour", "Normal speed", e);
  number(v, "ot_units_per_hour", "Extra units per overtime hour", e, { optional: true });
  number(v, "ot_cost_per_hour", "Overtime cost per hour", e, { optional: true });
  number(v, "max_ot_hours", "Most overtime hours", e, { optional: true, int: true, max: 168 });
  return e;
}

export function validateSupplier(v: Raw): Errors {
  const e: Errors = {};
  required(v, "name", "Supplier name", e);
  required(v, "route", "Route", e);
  if (!v.sourcing_role) e.sourcing_role = "Choose a role";
  if (!v.risk_profile) e.risk_profile = "Choose how reliable they are";
  number(v, "max_units", "Most units they can supply", e);
  number(v, "lead_hours", "Delivery time (hours)", e, { positive: true, int: true });
  number(v, "unit_cost", "Extra cost per unit", e, { optional: true });
  number(v, "flat_cost", "Fixed charge", e, { optional: true });
  number(v, "min_lead_hours", "Fastest delivery (hours)", e, { optional: true, positive: true });
  number(v, "past_orders", "Past orders", e, { optional: true, int: true });
  number(v, "on_time", "Of those, on time", e, { optional: true, int: true });
  const past = parseNum(v.past_orders);
  const ontime = parseNum(v.on_time);
  if ((past === null) !== (ontime === null)) {
    e[past === null ? "past_orders" : "on_time"] = "Fill in both past orders and on-time, or leave both empty";
  } else if (past !== null && ontime !== null && ontime > past && !e.on_time) {
    e.on_time = "On-time can't be more than past orders";
  }
  const lead = parseNum(v.lead_hours);
  const minLead = parseNum(v.min_lead_hours);
  if (lead !== null && minLead !== null && minLead > lead && !e.min_lead_hours) {
    e.min_lead_hours = "Fastest delivery can't be slower than the usual delivery time";
  }
  return e;
}

export function validateOrder(v: Raw): Errors {
  const e: Errors = {};
  required(v, "client", "Customer", e);
  number(v, "required_qty", "Quantity", e, { positive: true, int: true });
  number(v, "hours_remaining", "Hours until due", e, { positive: true, max: 8760 });
  number(v, "sla_penalty_inr", "Penalty if late", e);
  number(v, "partial_delay_penalty_inr", "Penalty for a short delay", e, { optional: true });
  return e;
}

export function validateMember(v: Raw): Errors {
  const e: Errors = {};
  if (!isEmail(String(v.email ?? ""))) e.email = "Enter a valid email address";
  if (!v.role) e.role = "Choose a role";
  return e;
}

export const hasErrors = (e: Errors) => Object.keys(e).length > 0;

/** Number-or-undefined for optional numeric inputs in request bodies. */
export const optNum = (s: string | number | null | undefined): number | undefined => parseNum(s) ?? undefined;
