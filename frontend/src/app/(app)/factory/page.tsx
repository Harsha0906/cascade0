"use client";

import React, { useState } from "react";
import { Plus } from "lucide-react";
import { useApiData } from "@/lib/useApiData";
import { callApi } from "@/lib/api";
import { formatInr, groupIndian } from "@/lib/format";
import { Banner, Btn, Card, DataTable, Drawer, EmptyState, Loading, PageHeader } from "@/components/ui";
import { FactoryForm, LineForm } from "@/components/EntityForms";
import { ImportButtons, LINE_IMPORT } from "@/components/ImportButtons";
import { useCanEdit } from "@/components/ShellContext";

export default function FactoryPage() {
  const canEdit = useCanEdit();
  const settings = useApiData<any>("/api/v1/factory/settings");
  const lines = useApiData<{ lines: any[] }>("/api/v1/lines");
  const [drawer, setDrawer] = useState<{ row?: any } | null>(null);
  const [saved, setSaved] = useState(false);
  const [actionError, setActionError] = useState("");

  const remove = async (l: any) => {
    if (!window.confirm(`Remove ${l.name}? This can't be undone.`)) return;
    setActionError("");
    const r = await callApi(`/api/v1/lines/${encodeURIComponent(l.line_id)}`, "DELETE");
    if (!r.ok) return setActionError(r.error);
    void lines.reload();
  };

  return (
    <>
      <PageHeader title="Factory" sub="The basics of your plant, and the production lines the planner can use." />
      {settings.error && <Banner>{settings.error}</Banner>}
      {settings.loading ? (
        <Loading />
      ) : (
        settings.data && (
          <Card className="mb-8 p-5">
            <h2 className="mb-4 font-display text-lg font-bold">Basics</h2>
            {canEdit ? (
              <FactoryForm key={settings.data.name + settings.data.safety_stock_units} initial={settings.data} onDone={() => { setSaved(true); void settings.reload(); }} />
            ) : (
              <dl className="grid gap-3 sm:grid-cols-2">
                <div><dt className="text-sm text-charcoal-600">Name</dt><dd className="font-semibold">{settings.data.name}</dd></div>
                <div><dt className="text-sm text-charcoal-600">Main part</dt><dd className="font-semibold">{settings.data.stock_item_name} ({settings.data.stock_item_code})</dd></div>
                <div><dt className="text-sm text-charcoal-600">Safety stock</dt><dd className="font-semibold">{groupIndian(settings.data.safety_stock_units)} units</dd></div>
              </dl>
            )}
            {saved && <div className="mt-3"><Banner tone="green">Saved.</Banner></div>}
          </Card>
        )
      )}

      <PageHeader
        title="Production lines"
        action={canEdit && <Btn onClick={() => setDrawer({})}><Plus className="h-4 w-4" aria-hidden /> Add line</Btn>}
      />
      {lines.error && <Banner>{lines.error}</Banner>}
      {actionError && <Banner>{actionError}</Banner>}
      {!lines.loading && !lines.error && (
        <DataTable
          rows={lines.data?.lines ?? []}
          rowKey={(r) => r.line_id}
          searchLabel="Search lines"
          empty={<EmptyState title="No production lines yet" body="Add each line with its normal speed, so the planner knows what you can make." action={canEdit && <Btn onClick={() => setDrawer({})}>Add your first line</Btn>} />}
          columns={[
            { key: "name", header: "Line", render: (r) => <span className="font-semibold">{r.name}</span>, text: (r) => r.name },
            { key: "speed", header: "Normal speed", render: (r) => `${groupIndian(r.rated_units_per_hour)} units / h` },
            { key: "ot", header: "With overtime", render: (r) => (r.max_ot_hours > 0 ? `+${groupIndian(r.ot_units_per_hour)} units / h, up to ${r.max_ot_hours} h` : "No overtime") },
            { key: "otc", header: "Overtime cost", render: (r) => (r.max_ot_hours > 0 ? `${formatInr(r.ot_cost_per_hour)} / h` : "—") },
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
      )}
      {canEdit && (
        <div className="mt-6">
          <ImportButtons kinds={[LINE_IMPORT]} onDone={lines.reload} />
        </div>
      )}
      <Drawer open={Boolean(drawer)} title={drawer?.row ? `Edit ${drawer.row.name}` : "Add production line"} onClose={() => setDrawer(null)}>
        {drawer && <LineForm key={drawer.row?.line_id ?? "new"} initial={drawer.row} onDone={() => { setDrawer(null); void lines.reload(); }} onCancel={() => setDrawer(null)} />}
      </Drawer>
    </>
  );
}
