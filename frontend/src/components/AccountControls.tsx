"use client";

import React, { useEffect, useState } from "react";
import { LogOut, Send } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { apiFetch } from "@/lib/session";

/** Signed-in user email, Sign out, and a one-time Telegram link code. */
export function AccountControls() {
  const [email, setEmail] = useState<string | null>(null);
  const [linkMsg, setLinkMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!supabase) return;
    void supabase.auth.getSession().then(({ data }) => setEmail(data.session?.user.email ?? null));
    const { data } = supabase.auth.onAuthStateChange((_e, session) => setEmail(session?.user.email ?? null));
    return () => data.subscription.unsubscribe();
  }, []);

  const linkTelegram = async () => {
    setLinkMsg("Requesting code…");
    try {
      const res = await apiFetch("/api/v1/channels/link-code", { method: "POST" });
      if (res.status === 404) {
        setLinkMsg("Telegram linking is not available yet on this server.");
        return;
      }
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setLinkMsg(String(body.detail || `Could not get a code (HTTP ${res.status})`));
        return;
      }
      const expiry = body.expires_at
        ? ` Expires ${new Date(body.expires_at).toLocaleTimeString()}.`
        : body.expires_in_seconds
        ? ` Expires in ${Math.round(body.expires_in_seconds / 60)} min.`
        : "";
      setLinkMsg(`Link code: ${body.code}.${expiry} Send it to the Telegram bot.`);
    } catch {
      setLinkMsg("Could not reach the backend.");
    }
  };

  const signOut = async () => {
    await supabase?.auth.signOut();
    window.location.assign("/login");
  };

  if (!email) return null;
  return (
    <div className="flex items-center gap-2 flex-wrap text-xs font-mono">
      <span className="text-charcoal-700 truncate max-w-[180px]" title={email}>{email}</span>
      <button
        onClick={linkTelegram}
        className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-white/40 border border-white/50 font-bold text-charcoal-900 hover:bg-white/60"
      >
        <Send className="w-3.5 h-3.5" /> Link Telegram
      </button>
      <button
        onClick={signOut}
        className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-white/40 border border-white/50 font-bold text-charcoal-900 hover:bg-white/60"
      >
        <LogOut className="w-3.5 h-3.5" /> Sign out
      </button>
      {linkMsg && <span className="text-charcoal-800 break-words w-full">{linkMsg}</span>}
    </div>
  );
}
