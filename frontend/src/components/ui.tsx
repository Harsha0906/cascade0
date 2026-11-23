"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Check, Copy, Loader2, Search, X } from "lucide-react";

export const INPUT =
  "w-full rounded-xl border border-rule bg-white px-3.5 py-2.5 text-[15px] text-charcoal-900 placeholder:text-charcoal-400 focus:border-forest focus:outline-none disabled:bg-ground";

type Variant = "primary" | "quiet" | "danger" | "accent";
const BTN: Record<Variant, string> = {
  primary: "bg-forest text-white hover:bg-forest-light",
  accent: "bg-acid text-acid-text hover:bg-acid-hover font-bold",
  quiet: "bg-white text-charcoal-900 border border-rule hover:bg-ground",
  danger: "bg-white text-alert border border-alert/30 hover:bg-alert-soft",
};

export function Btn({
  variant = "primary",
  small,
  busy,
  className = "",
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; small?: boolean; busy?: boolean }) {
  return (
    <button
      type="button"
      {...rest}
      disabled={rest.disabled || busy}
      className={`inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
        small ? "px-3 py-1.5 text-sm" : "px-5 py-2.5 text-[15px]"
      } ${BTN[variant]} ${className}`}
    >
      {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  className = "",
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <span className="block text-sm font-semibold text-charcoal-800 mb-1">{label}</span>
      {children}
      {error ? (
        <span role="alert" className="block text-sm text-alert mt-1">{error}</span>
      ) : hint ? (
        <span className="block text-[13px] text-charcoal-600 mt-1">{hint}</span>
      ) : null}
    </label>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-rule bg-paper ${className}`}>{children}</section>;
}

const TONES = {
  green: "bg-emerald-100 text-emerald-900",
  red: "bg-alert-soft text-alert-deep",
  amber: "bg-amber-100 text-amber-900",
  grey: "bg-ground text-charcoal-700",
  lime: "bg-acid text-acid-text",
} as const;

export function Badge({ tone = "grey", children }: { tone?: keyof typeof TONES; children: React.ReactNode }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[13px] font-semibold ${TONES[tone]}`}>{children}</span>;
}

export function Banner({ tone = "red", children }: { tone?: "red" | "green" | "grey"; children: React.ReactNode }) {
  const cls = tone === "red" ? "bg-alert-soft text-alert-deep border-alert/20" : tone === "green" ? "bg-emerald-50 text-emerald-900 border-emerald-200" : "bg-ground text-charcoal-800 border-rule";
  return (
    <p role={tone === "red" ? "alert" : "status"} className={`rounded-xl border px-4 py-3 text-sm break-words ${cls}`}>
      {children}
    </p>
  );
}

export function PageHeader({ title, sub, action }: { title: string; sub?: string; action?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3 mb-6">
      <div>
        <h1 className="font-display text-[28px] leading-tight font-extrabold tracking-tight text-charcoal-900">{title}</h1>
        {sub && <p className="text-charcoal-600 mt-1 max-w-xl">{sub}</p>}
      </div>
      {action}
    </header>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="flex items-center gap-2 text-charcoal-600 py-8">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}
    </p>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: React.ReactNode }) {
  return (
    <div className="text-center py-12 px-4">
      <p className="font-display text-lg font-bold text-charcoal-900">{title}</p>
      {body && <p className="text-charcoal-600 mt-1 max-w-md mx-auto">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Btn
      variant="quiet"
      small
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1800);
        } catch {
          /* clipboard blocked: the text stays selectable on screen */
        }
      }}
    >
      {done ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
      {done ? "Copied" : label}
    </Btn>
  );
}

/** Side drawer for add / edit forms. */
export function Drawer({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={title}>
      <button aria-label="Close" className="absolute inset-0 bg-charcoal-950/40" onClick={onClose} />
      <div className="drawer-panel relative h-full w-full max-w-md overflow-y-auto bg-paper shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-rule bg-paper px-5 py-4">
          <h2 className="font-display text-lg font-bold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 hover:bg-ground">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  /** Text used by the search box; omit to exclude the column from search. */
  text?: (row: T) => string;
  className?: string;
}

/** Searchable table. On phones each row folds into a stacked card. */
export function DataTable<T>({
  rows,
  columns,
  rowKey,
  searchLabel = "Search",
  empty,
  actions,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (r: T) => string;
  searchLabel?: string;
  empty: React.ReactNode;
  actions?: (r: T) => React.ReactNode;
}) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((r) => columns.some((c) => c.text && c.text(r).toLowerCase().includes(needle)));
  }, [rows, columns, q]);

  if (!rows.length) return <Card>{empty}</Card>;
  return (
    <div className="space-y-3">
      <div className="relative max-w-xs">
        <Search className="absolute left-3 top-3 h-4 w-4 text-charcoal-400" aria-hidden />
        <input aria-label={searchLabel} placeholder={`${searchLabel}…`} value={q} onChange={(e) => setQ(e.target.value)} className={`${INPUT} pl-9`} />
      </div>
      <Card className="overflow-hidden">
        <table className="w-full text-[15px]">
          <thead className="hidden md:table-header-group">
            <tr className="border-b border-rule text-left text-sm text-charcoal-600">
              {columns.map((c) => (
                <th key={c.key} className={`px-4 py-3 font-semibold ${c.className ?? ""}`}>{c.header}</th>
              ))}
              {actions && <th className="px-4 py-3"><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={rowKey(r)} className="block md:table-row border-b border-rule last:border-0 px-4 py-3 md:p-0">
                {columns.map((c) => (
                  <td key={c.key} className={`block md:table-cell md:px-4 md:py-3 py-0.5 align-top ${c.className ?? ""}`}>
                    <span className="md:hidden text-[13px] text-charcoal-600">{c.header}: </span>
                    {c.render(r)}
                  </td>
                ))}
                {actions && <td className="block md:table-cell md:px-4 md:py-3 pt-2 md:text-right whitespace-nowrap">{actions(r)}</td>}
              </tr>
            ))}
            {!shown.length && (
              <tr><td className="px-4 py-6 text-charcoal-600" colSpan={columns.length + 1}>Nothing matches “{q}”.</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
