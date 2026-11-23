"use client";

import React, { useState } from "react";
import { useApiData } from "@/lib/useApiData";
import { callApi } from "@/lib/api";
import { formatHours, groupIndian } from "@/lib/format";
import { Badge, Banner, Btn, DataTable, EmptyState, Loading, PageHeader } from "@/components/ui";
import { ImportButtons, ORDER_IMPORTS, STOCK_IMPORTS } from "@/components/ImportButtons";
import { useCanEdit } from "@/components/ShellContext";

export default function StockPage() {
  const canEdit = useCanEdit();
  const stock = useApiData<{ items: any[]; shipments: any[] }>("/api/v1/stock");
  const pending = useApiData<{ outcomes: any[] }>("/api/v1/deliveries?status=PENDING");
  const [busyPo, setBusyPo] = useState("");
  const [actionError, setActionError] = useState("");
  const [note, setNote] = useState("");

  const refresh = () => {
    void stock.reload();
    void pending.reload();
  };

  const markDelivered = async (o: any) => {
    setBusyPo(o.po_number);
    setActionError("");
    setNote("");
    const r = await callApi("/api/v1/deliveries", "POST", {
      po_number: o.po_number,
      supplier_id: o.supplier_id,
      delivered_at: new Date().toISOString(),
    });
    setBusyPo("");
    if (!r.ok) return setActionError(r.error);
    setNote(`${o.po_number} marked as delivered${r.data?.on_time === false ? " (late)" : r.data?.on_time ? " (on time)" : ""}.`);
    refresh();
  };

  return (
    <>
      <PageHeader title="Stock" sub="What is on the shelf, and what is on its way to you." />
      {stock.error && <Banner>{stock.error}</Banner>}
      {actionError && <Banner>{actionError}</Banner>}
      {note && <Banner tone="green">{note}</Banner>}

      <h2 className="mb-3 mt-2 font-display text-lg font-bold">On the shelf</h2>
      {stock.loading ? (
        <Loading />
      ) : (
        !stock.error && (
          <DataTable
            rows={stock.data?.items ?? []}
            rowKey={(r) => r.item_code}
            searchLabel="Search parts"
            empty={<EmptyState title="No stock recorded" body="Upload your stock summary below, or it will fill in as you add parts." />}
            columns={[
              { key: "item", header: "Part", render: (r) => <span><span className="font-semibold">{r.name || r.item_code}</span><span className="block text-[13px] text-charcoal-600">{r.item_code}</span></span>, text: (r) => `${r.name} ${r.item_code}` },
              { key: "qty", header: "In stock", render: (r) => `${groupIndian(r.on_hand_qty)} ${r.unit || "units"}` },
            ]}
          />
        )
      )}

      <h2 className="mb-3 mt-10 font-display text-lg font-bold">On the way</h2>
      {!stock.loading && !stock.error && (
        <DataTable
          rows={stock.data?.shipments ?? []}
          rowKey={(r) => r.shipment_id}
          searchLabel="Search shipments"
          empty={<EmptyState title="Nothing on the way" body="Upload your open purchase orders to see what you are waiting for." />}
          columns={[
            { key: "id", header: "Shipment", render: (r) => <span className="font-semibold">{r.shipment_id}</span>, text: (r) => r.shipment_id },
            { key: "sup", header: "From", render: (r) => r.supplier_name || r.supplier_id || "—", text: (r) => r.supplier_name ?? "" },
            { key: "qty", header: "Quantity", render: (r) => `${groupIndian(r.qty)} units` },
            { key: "eta", header: "Arrives", render: (r) => formatHours(r.eta_hours) },
            { key: "st", header: "Status", render: (r) => <Badge tone={r.status === "DELAYED" ? "red" : "grey"}>{String(r.status ?? "").toLowerCase().replace(/_/g, " ") || "—"}</Badge> },
          ]}
        />
      )}

      <h2 className="mb-1 mt-10 font-display text-lg font-bold">Waiting for delivery</h2>
      <p className="mb-3 text-charcoal-600">When a supplier's truck arrives, mark it delivered. This teaches the planner who is really on time.</p>
      {pending.error && <Banner>{pending.error}</Banner>}
      {!pending.loading && !pending.error && (
        <DataTable
          rows={pending.data?.outcomes ?? []}
          rowKey={(r) => `${r.po_number}-${r.supplier_id}`}
          searchLabel="Search deliveries"
          empty={<EmptyState title="No deliveries are waiting" body="Orders you place with suppliers will show up here." />}
          columns={[
            { key: "po", header: "Purchase order", render: (r) => <span className="font-semibold">{r.po_number}</span>, text: (r) => r.po_number },
            { key: "sup", header: "Supplier", render: (r) => r.supplier_id, text: (r) => r.supplier_id },
            { key: "units", header: "Units", render: (r) => groupIndian(r.units) },
            { key: "due", header: "Promised", render: (r) => new Date(r.promised_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) },
          ]}
          actions={canEdit ? (r) => <Btn variant="quiet" small busy={busyPo === r.po_number} onClick={() => markDelivered(r)}>Mark delivered</Btn> : undefined}
        />
      )}

      {canEdit && (
        <section className="mt-10">
          <h2 className="mb-1 font-display text-lg font-bold">Import from your files</h2>
          <p className="mb-3 text-charcoal-600">Export a CSV from Tally or Excel and upload it. Rows with problems are listed so you can fix them.</p>
          <ImportButtons kinds={[...STOCK_IMPORTS, ...ORDER_IMPORTS]} onDone={refresh} />
        </section>
      )}
    </>
  );
}
