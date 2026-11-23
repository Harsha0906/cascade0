"use client";

import React, { useState } from "react";
import { Zap } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { apiFetch } from "@/lib/session";

export default function LoginPage() {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!supabase) {
      setError("Supabase is not configured (NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY missing).");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const { data, error: authError } =
        mode === "signin"
          ? await supabase.auth.signInWithPassword({ email, password })
          : await supabase.auth.signUp({ email, password });
      if (authError) {
        setError(authError.message);
        return;
      }
      if (!data.session) {
        setNotice("Check your email to confirm your account, then sign in.");
        return;
      }
      // Signed in: does this user belong to a factory? The backend answers 404 on /factory if not.
      const res = await apiFetch("/api/v1/factory");
      // No factory yet: the setup wizard creates one.
      window.location.assign(res.status === 404 ? "/setup" : "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <form onSubmit={submit} className="island-card-static w-full max-w-sm p-6 flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-2xl bg-acid flex items-center justify-center shadow-pill shrink-0">
            <Zap className="w-5 h-5 text-charcoal-900 fill-charcoal-900" />
          </div>
          <h1 className="text-base font-extrabold text-charcoal-900 tracking-tight">
            CASCADE<span className="text-forest font-medium">ZERO</span>
          </h1>
        </div>
        <input
          type="email"
          required
          autoComplete="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="px-3.5 py-2 rounded-xl bg-white/50 border border-white/60 text-sm font-mono text-charcoal-900"
        />
        <input
          type="password"
          required
          autoComplete={mode === "signin" ? "current-password" : "new-password"}
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="px-3.5 py-2 rounded-xl bg-white/50 border border-white/60 text-sm font-mono text-charcoal-900"
        />
        {error && <p className="text-xs font-mono text-coral break-words">{error}</p>}
        {notice && <p className="text-xs font-mono text-charcoal-800 break-words">{notice}</p>}
        <button
          type="submit"
          disabled={busy}
          className="px-3.5 py-2 rounded-xl bg-charcoal-900 text-white text-xs font-mono font-bold disabled:opacity-50"
        >
          {busy ? "Working…" : mode === "signin" ? "Sign in" : "Create account"}
        </button>
        <button
          type="button"
          onClick={() => {
            setMode(mode === "signin" ? "signup" : "signin");
            setError(null);
            setNotice(null);
          }}
          className="text-xs font-mono text-charcoal-700 hover:text-charcoal-950"
        >
          {mode === "signin" ? "No account? Sign up" : "Have an account? Sign in"}
        </button>
      </form>
    </main>
  );
}
