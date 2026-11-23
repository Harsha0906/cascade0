/** Indian digit grouping: 2500000 -> "25,00,000". Non-finite numbers give an em dash. */
export function groupIndian(n: number): string {
  if (!Number.isFinite(n)) return "—";
  const neg = n < 0;
  const [intPart, frac] = Math.abs(Math.round(n * 100) / 100).toString().split(".");
  let out: string;
  if (intPart.length <= 3) out = intPart;
  else {
    const last3 = intPart.slice(-3);
    const rest = intPart.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
    out = `${rest},${last3}`;
  }
  return `${neg ? "-" : ""}${out}${frac ? `.${frac}` : ""}`;
}

/** Rupees in Indian format: ₹25,00,000. */
export function formatInr(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n < 0 ? "-" : ""}₹${groupIndian(Math.abs(n))}`;
}

/** Short rupees for tight spaces: ₹25 lakh, ₹1.2 crore, ₹45,000. */
export function formatInrShort(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  const trim = (x: number) => x.toFixed(2).replace(/\.?0+$/, "");
  if (a >= 1e7) return `${sign}₹${trim(a / 1e7)} crore`;
  if (a >= 1e5) return `${sign}₹${trim(a / 1e5)} lakh`;
  return formatInr(n);
}

export function formatCount(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? "—" : groupIndian(n);
}

export function formatPct(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? "—" : `${Math.round(n)}%`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${groupIndian(n)} ${n === 1 ? one : many}`;
}

/** "in 5 h", "in 2 days", "2 h overdue" from a number of hours. */
export function formatHours(h: number | null | undefined): string {
  if (h == null || !Number.isFinite(h)) return "—";
  const abs = Math.abs(h);
  const span = abs >= 48 ? `${Math.round(abs / 24)} days` : `${Math.round(abs * 10) / 10} h`;
  return h < 0 ? `${span} overdue` : `in ${span}`;
}

/** Plain-language name for a supplier's sourcing role. */
export function roleLabel(role: string | null | undefined): string {
  switch (role) {
    case "PRIMARY": return "Main supplier";
    case "BACKUP": return "Backup";
    case "EXPEDITE": return "Express";
    default: return role || "—";
  }
}
