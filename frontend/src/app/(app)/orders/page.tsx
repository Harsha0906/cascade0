"use client";

import React, { useState } from "react";
import { Plus } from "lucide-react";
import { useApiData } from "@/lib/useApiData";
import { formatHours, formatInr, groupIndian } from "@/lib/format";
import { HEALTHY_STATUSES } from "@/lib/plainPlan";
import { Badge, Banner, Btn, DataTable, Drawer, EmptyState, Loading, PageHeader } from "@/components/ui";
import { OrderForm } from "@/components/EntityForms";
import { TelegramInvite } from "@/components/TelegramInvite";
import { useCanEdit } from "@/components/ShellContext";

export default function OrdersPage() {
  const canEdit = useCanEdit();
  const { data, error, loading, reload } = useApiData<{ orders: any[] }>("/api/v1/orders");
  const [drawer, setDrawer] = useState<{ row?: any } | null>(null);

  const rows = data?.orders ?? [];
  const done = () => {
    setDrawer(null);
    void reload();
  };

  return (
    <>
      <PageHeader
        title="Orders"
        sub="What your customers are waiting for, and what it costs if you are late."
        action={canEdit && <Btn onClick={() => setDrawer({})}><Plus className="h-4 w-4" aria-hidden /> Add order</Btn>}
      />
      {error && <Banner>{error}</Banner>}
      {loading ? (
        <Loading />
      ) : (
        !error && (
          <DataTable
            rows={rows}
            rowKey={(r) => r.order_id}
            searchLabel="Search orders"
            empty={<EmptyState title="No orders yet" body="Add an order by hand, or import your customer orders from Stock." action={canEdit && <Btn onClick={() => setDrawer({})}>Add your first order</Btn>} />}
            columns={[
              { key: "order", header: "Order", render: (r) => <span className="font-semibold">{r.order_id}</span>, text: (r) => r.order_id },
              { key: "client", header: "Customer", render: (r) => r.client, text: (r) => r.client },
              { key: "qty", header: "Quantity", render: (r) => `${groupIndian(r.required_qty)} units`, text: (r) => String(r.required_qty) },
              { key: "due", header: "Due", render: (r) => formatHours(r.hours_remaining) },
              { key: "pen", header: "Penalty if late", render: (r) => formatInr(r.sla_penalty_inr) },
              {
                key: "status",
                header: "Status",
                render: (r) =>
                  HEALTHY_STATUSES.includes(r.status) ? (
                    <Badge tone="green">{r.status === "ON_TRACK" ? "On track" : "Plan approved"}</Badge>
                  ) : (
                    <Badge tone="red">At risk</Badge>
                  ),
                text: (r) => r.status,
              },
              {
                key: "tg",
                header: "Customer on Telegram",
                render: (r) => <TelegramInvite path={`/api/v1/orders/${encodeURIComponent(r.order_id)}/telegram-invite`} connected={Boolean(r.telegram_connected)} canEdit={canEdit} />,
              },
            ]}
            actions={canEdit ? (r) => <Btn variant="quiet" small onClick={() => setDrawer({ row: r })}>Edit</Btn> : undefined}
          />
        )
      )}
      <Drawer open={Boolean(drawer)} title={drawer?.row ? `Edit order ${drawer.row.order_id}` : "Add order"} onClose={() => setDrawer(null)}>
        {drawer && <OrderForm key={drawer.row?.order_id ?? "new"} initial={drawer.row} onDone={done} onCancel={() => setDrawer(null)} />}
      </Drawer>
    </>
  );
}
