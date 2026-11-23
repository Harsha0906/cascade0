"use client";

import React, { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { callApi } from "@/lib/api";
import { Banner, Btn } from "./ui";

export interface ImportKind {
  label: string;
  path: string;
  hint: string;
}

export const STOCK_IMPORTS: ImportKind[] = [
  { label: "Stock summary", path: "/api/v1/ingest/stock-summary", hint: "What is on the shelf today" },
  { label: "Open purchase orders", path: "/api/v1/ingest/open-purchase-orders", hint: "Deliveries you are waiting for" },
];
export const ORDER_IMPORTS: ImportKind[] = [
  { label: "Customer orders", path: "/api/v1/ingest/erp-csv", hint: "Orders from your ERP or Excel" },
  { label: "Sales order lines", path: "/api/v1/ingest/sales-order-lines", hint: "Part-wise lines for each order" },
];
export const LINE_IMPORT: ImportKind = { label: "Upload lines (CSV)", path: "/api/v1/ingest/lines-csv", hint: "Name and speed per line" };
export const SUPPLIER_IMPORT: ImportKind = { label: "Upload suppliers (CSV)", path: "/api/v1/ingest/suppliers-csv", hint: "One row per supplier" };

interface Result {
  ok: boolean;
  title: string;
  lines: string[];
}

function ImportButton({ kind, onDone }: { kind: ImportKind; onDone?: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  const pick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const input = e.target;
    const file = input.files?.[0];
    if (!file) return;
    setBusy(true);
    const text = await file.text();
    const r = await callApi(kind.path, "POST", { filename: file.name, csv_content: text });
    setBusy(false);
    input.value = "";
    if (!r.ok) {
      setResult({ ok: false, title: `Could not import ${file.name}`, lines: [r.error] });
      return;
    }
    const d = r.data ?? {};
    const errors: string[] = (d.errors ?? []).map((x: any) => `Line ${x.line}: ${x.error}`);
    const warnings: string[] = (d.warnings ?? []).map((x: any) => (x.line == null ? x.warning : `Line ${x.line}: ${x.warning}`));
    setResult({
      ok: errors.length === 0,
      title: `${file.name}: ${d.imported_count ?? 0} row(s) imported${errors.length ? `, ${errors.length} with problems` : ""}`,
      lines: [...errors, ...warnings],
    });
    onDone?.();
  };

  return (
    <div className="space-y-2">
      <input ref={ref} type="file" accept=".csv,text/csv" className="sr-only" onChange={pick} aria-label={kind.label} />
      <Btn variant="quiet" busy={busy} onClick={() => ref.current?.click()} title={kind.hint}>
        <Upload className="h-4 w-4" aria-hidden /> {kind.label}
      </Btn>
      {result && (
        <Banner tone={result.ok ? "green" : "red"}>
          <strong>{result.title}</strong>
          {result.lines.length > 0 && (
            <span className="mt-1 block max-h-32 overflow-y-auto">
              {result.lines.slice(0, 20).map((l, i) => <span key={i} className="block">{l}</span>)}
              {result.lines.length > 20 && <span className="block">…and {result.lines.length - 20} more</span>}
            </span>
          )}
        </Banner>
      )}
    </div>
  );
}

export function ImportButtons({ kinds, onDone }: { kinds: ImportKind[]; onDone?: () => void }) {
  return (
    <div className="flex flex-wrap items-start gap-3">
      {kinds.map((k) => <ImportButton key={k.path} kind={k} onDone={onDone} />)}
    </div>
  );
}
