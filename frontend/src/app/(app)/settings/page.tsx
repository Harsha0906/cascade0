"use client";

import React, { useState } from "react";
import { callApi } from "@/lib/api";
import { useFactoryStore } from "@/store/useFactoryStore";
import { Banner, Btn, Card, PageHeader } from "@/components/ui";
import { useShell } from "@/components/ShellContext";
import { DEMO_FACTORY_ID } from "@/lib/demo";

export default function SettingsPage() {
  const { factoryId, role, email } = useShell();
  const resetFactory = useFactoryStore((s) => s.resetFactory);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const isDemoOwner = factoryId === DEMO_FACTORY_ID && role === "owner";

  const reset = async () => {
    if (!window.confirm("Reset the demo factory to its starting data? Your changes to it will be lost.")) return;
    setBusy(true);
    setMsg(null);
    const r = await callApi("/api/v1/reset", "POST", { factory_id: DEMO_FACTORY_ID });
    setBusy(false);
    if (!r.ok) return setMsg({ ok: false, text: r.error });
    await resetFactory().catch(() => undefined);
    setMsg({ ok: true, text: "Demo factory reset." });
  };

  return (
    <>
      <PageHeader title="Settings" />
      <div className="space-y-5">
        <Card className="p-5">
          <h2 className="font-display text-lg font-bold">Your account</h2>
          <p className="mt-1 text-charcoal-700">{email ?? "Signed in"} · {role}</p>
        </Card>

        <Card className="p-5">
          <h2 className="font-display text-lg font-bold">How suppliers are contacted</h2>
          <p className="mt-1 text-charcoal-700 max-w-xl">
            This is set by whoever runs the server, with the <code className="rounded bg-ground px-1.5 py-0.5 text-sm">SOURCING_MODE</code> setting.
            In <strong>simulated</strong> mode, nothing is sent: you type in each supplier's reply yourself.
            In <strong>telegram</strong> or <strong>whatsapp</strong> mode, enquiries go to suppliers' chats and their replies come back by themselves.
            It can't be changed from this page.
          </p>
        </Card>

        {isDemoOwner && (
          <Card className="p-5">
            <h2 className="font-display text-lg font-bold">Demo factory</h2>
            <p className="mt-1 mb-4 text-charcoal-700 max-w-xl">Put the sample factory back to its starting data. Useful before showing the product to someone.</p>
            <Btn variant="danger" busy={busy} onClick={reset}>Reset demo factory</Btn>
            {msg && <div className="mt-3"><Banner tone={msg.ok ? "green" : "red"}>{msg.text}</Banner></div>}
          </Card>
        )}
      </div>
    </>
  );
}
