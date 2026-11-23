"use client";

import React, { useState } from "react";
import { Plus } from "lucide-react";
import { useApiData } from "@/lib/useApiData";
import { callApi } from "@/lib/api";
import { formatHours, formatInr, formatPct, groupIndian, roleLabel } from "@/lib/format";
import { RISK_PROFILES } from "@/lib/forms";
import { Badge, Banner, Btn, DataTable, Drawer, EmptyState, Loading, PageHeader } from "@/components/ui";
import { SupplierForm } from "@/components/EntityForms";
import { TelegramInvite } from "@/components/TelegramInvite";
import { ImportButtons, SUPPLIER_IMPORT } from "@/components/ImportButtons";
import { useCanEdit } from "@/components/ShellContext";

export default function SuppliersPage() {
  const canEdit = useCanEdit();
  const { data, error, loading, reload } = useApiData<{ suppliers: any[] }>("/api/v1/suppliers");
  const [drawer, setDrawer] = useState<{ row?: any } | null>(null);
  const [actionError, setActionError] = useState("");

  const rows = data?.suppliers ?? [];
  const done = () => {
    setDrawer(null);
    void reload();
  };
  const remove = async (s: any) => {
    if (!window.confirm(`Remove ${s.name}? This can't be undone.`)) return;
    setActionError("");
    const r = await callApi(`/api/v1/suppliers/${encodeURIComponent(s.id)}`, "DELETE");
    if (!r.ok) return setActionError(r.error);
    void reload();
  };

  return (
    <>
      <PageHeader
        title="Suppliers"
        sub="Who can send you parts when something goes wrong, and how much you can trust them."
        action={canEdit && <Btn onClick={() => setDrawer({})}><Plus className="h-4 w-4" aria-hidden /> Add supplier</Btn>}
      />
      {error && <Banner>{error}</Banner>}
      {actionError && <Banner>{actionError}</Banner>}
      {loading ? (
        <Loading />
      ) : (
        !error && (
          <DataTable
            rows={rows}
            rowKey={(r) => r.id}
            searchLabel="Search suppliers"
            empty={<EmptyState title="No suppliers yet" body="Add the suppliers you would call in a crisis, or upload a list." action={canEdit && <Btn onClick={() => setDrawer({})}>Add your first supplier</Btn>} />}
            columns={[
              { key: "name", header: "Supplier", render: (r) => <span><span className="font-semibold">{r.name}</span><span className="block text-[13px] text-charcoal-600">{r.route}</span></span>, text: (r) => `${r.name} ${r.route}` },
              { key: "role", header: "Role", render: (r) => roleLabel(r.sourcing_role), text: (r) => roleLabel(r.sourcing_role) },
              { key: "lead", header: "Delivers in", render: (r) => formatHours(r.lead_hours).replace(/^in /, "") },
              { key: "cap", header: "Can supply", render: (r) => `${groupIndian(r.max_units)} units` },
              { key: "price", header: "Price", render: (r) => (r.flat_cost > 0 ? `${formatInr(r.flat_cost)} flat` : `${formatInr(r.unit_cost)} / unit`) },
              {
                key: "rel",
                header: "On-time record",
                render: (r) =>
                  r.reliability?.has_history ? (
                    <span>{formatPct(r.reliability.reliability_pct)} on time</span>
                  ) : (
                    <span className="text-charcoal-600">no history yet</span>
                  ),
              },
              { key: "risk", header: "Risk", render: (r) => <span title={RISK_PROFILES[r.risk_profile as keyof typeof RISK_PROFILES]}><Badge tone={r.risk_profile === "low" ? "green" : r.risk_profile === "high" ? "red" : "amber"}>{r.risk_profile}</Badge></span> },
              { key: "tg", header: "Telegram", render: (r) => <TelegramInvite path={`/api/v1/suppliers/${encodeURIComponent(r.id)}/telegram-invite`} connected={Boolean(r.telegram_connected)} canEdit={canEdit} /> },
            ]}
            actions={
              canEdit
                ? (r) => (
                    <span className="inline-flex gap-2">
                      <Btn variant="quiet" small onClick={() => setDrawer({ row: r })}>Edit</Btn>
                      <Btn variant="danger" small onClick={() => remove(r)}>Remove</Btn>
                    </span>
                  )
                : undefined
            }
          />
        )
      )}
      {canEdit && (
        <div className="mt-6">
          <p className="mb-2 text-sm text-charcoal-600">Have a list already? Columns: name, sourcing_role, max_units, lead_hours, route, risk_profile.</p>
          <ImportButtons kinds={[SUPPLIER_IMPORT]} onDone={reload} />
        </div>
      )}
      <Drawer open={Boolean(drawer)} title={drawer?.row ? `Edit ${drawer.row.name}` : "Add supplier"} onClose={() => setDrawer(null)}>
        {drawer && <SupplierForm key={drawer.row?.id ?? "new"} initial={drawer.row} onDone={done} onCancel={() => setDrawer(null)} />}
      </Drawer>
    </>
  );
}
