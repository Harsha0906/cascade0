"use client";

import React, { useState } from "react";
import { Send } from "lucide-react";
import { callApi } from "@/lib/api";
import { Badge, Banner, Btn, CopyButton } from "./ui";

/** "Telegram invite link" button: creates a one-time link and shows it with a Copy button. */
export function TelegramInvite({ path, connected, canEdit }: { path: string; connected: boolean; canEdit: boolean }) {
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState<{ url: string; expires: string | null } | null>(null);
  const [error, setError] = useState("");

  const create = async () => {
    setBusy(true);
    setError("");
    const r = await callApi(path, "POST");
    setBusy(false);
    if (!r.ok) return setError(r.error);
    setLink({ url: r.data.link, expires: r.data.expires_at ?? null });
  };

  return (
    <div className="flex flex-col items-start gap-2 md:items-end">
      <div className="flex items-center gap-2">
        {connected && <Badge tone="green">Connected ✓</Badge>}
        {canEdit && (
          <Btn variant="quiet" small busy={busy} onClick={create}>
            <Send className="h-4 w-4" aria-hidden /> Telegram invite link
          </Btn>
        )}
      </div>
      {error && <Banner>{error}</Banner>}
      {link && (
        <div className="w-full max-w-sm rounded-xl border border-rule bg-white p-3 text-left text-sm whitespace-normal">
          <p className="break-all font-semibold select-all">{link.url}</p>
          <p className="mt-1 text-charcoal-600">Send this to them. They tap Start once, and they are connected.</p>
          {link.expires && <p className="text-[13px] text-charcoal-500">Works once, until {new Date(link.expires).toLocaleDateString("en-IN")}.</p>}
          <div className="mt-2"><CopyButton text={link.url} label="Copy link" /></div>
        </div>
      )}
    </div>
  );
}
