"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  AlertTriangle,
  Boxes,
  ClipboardList,
  Factory as FactoryIcon,
  Home,
  LogOut,
  Settings,
  SlidersHorizontal,
  Truck,
  Users,
} from "lucide-react";
import { supabase } from "@/lib/supabase";
import { callApi } from "@/lib/api";
import { useFactoryStore } from "@/store/useFactoryStore";
import { ShellProvider, type ShellInfo } from "./ShellContext";
import { CrisisSandboxModal } from "./CrisisSandboxModal";
import { ExecutionModal } from "./ExecutionModal";
import { Banner, Loading } from "./ui";

const NAV = [
  { href: "/", label: "Today", icon: Home },
  { href: "/problems", label: "Problems", icon: AlertTriangle },
  { href: "/orders", label: "Orders", icon: ClipboardList },
  { href: "/suppliers", label: "Suppliers", icon: Truck },
  { href: "/stock", label: "Stock", icon: Boxes },
  { href: "/factory", label: "Factory", icon: FactoryIcon },
  { href: "/team", label: "Team", icon: Users },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;
const ADVANCED = { href: "/advanced", label: "Advanced", icon: SlidersHorizontal } as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { fetchInitialState, initRealtimeSubscriptions, isReceiptModalOpen, closeReceiptModal, statusMode } = useFactoryStore();
  const [info, setInfo] = useState<ShellInfo | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [s, session] = await Promise.all([
        callApi("/api/v1/factory/settings"),
        supabase ? supabase.auth.getSession() : Promise.resolve(null),
      ]);
      if (cancelled) return;
      if (s.status === 404) {
        router.replace("/setup");
        return;
      }
      if (!s.ok) {
        setError(s.error);
        return;
      }
      setInfo({
        factoryId: s.data.id,
        factoryName: s.data.name,
        role: s.data.role ?? "viewer",
        email: session?.data.session?.user.email ?? null,
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    if (!info) return;
    void fetchInitialState();
    const unsubscribe = initRealtimeSubscriptions();
    return () => unsubscribe();
  }, [info, fetchInitialState, initRealtimeSubscriptions]);

  const signOut = async () => {
    await supabase?.auth.signOut();
    window.location.assign("/login");
  };

  if (!info) {
    return (
      <div className="app-root min-h-screen grid place-items-center px-4">
        {error ? <div className="max-w-md"><Banner>{error}</Banner></div> : <Loading label="Opening your factory…" />}
      </div>
    );
  }

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  const link = (n: { href: string; label: string; icon: React.ComponentType<{ className?: string }> }, mobile = false) => {
    const Icon = n.icon;
    const active = isActive(n.href);
    const alert = n.href === "/problems" && statusMode === "CRISIS";
    return (
      <Link
        key={n.href}
        href={n.href}
        aria-current={active ? "page" : undefined}
        className={
          mobile
            ? `relative flex min-w-[68px] shrink-0 flex-col items-center gap-0.5 px-2 py-2 text-xs font-semibold ${active ? "text-forest" : "text-charcoal-600"}`
            : `relative flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-[15px] font-semibold transition-colors ${active ? "bg-forest text-white" : "text-charcoal-700 hover:bg-white"}`
        }
      >
        <Icon className={mobile ? "h-5 w-5" : "h-[18px] w-[18px]"} />
        {n.label}
        {alert && <span aria-label="needs attention" className="status-dot absolute right-3 top-3 h-2.5 w-2.5 rounded-full bg-alert md:static md:ml-auto" />}
        {mobile && active && <span className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-forest" />}
      </Link>
    );
  };

  return (
    <ShellProvider value={info}>
      <div className="app-root min-h-screen md:flex">
        <aside className="hidden md:flex md:w-60 shrink-0 flex-col border-r border-rule bg-ground/60 px-3 py-5 sticky top-0 h-screen">
          <Link href="/" className="mb-6 flex items-center gap-2 px-2">
            <span className="h-6 w-6 rounded-md bg-acid grid place-items-center"><span className="h-2.5 w-2.5 rounded-sm bg-forest" /></span>
            <span className="font-display text-lg font-extrabold tracking-tight">CascadeZero</span>
          </Link>
          <nav aria-label="Main" className="flex flex-col gap-1">{NAV.map((n) => link(n))}</nav>
          <div className="mt-auto border-t border-rule pt-3">{link(ADVANCED)}</div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col pb-20 md:pb-0">
          <header className="flex items-center justify-between gap-3 border-b border-rule bg-paper px-4 py-3 md:px-8">
            <div className="min-w-0">
              <p className="truncate font-display text-base font-bold">{info.factoryName}</p>
            </div>
            <div className="flex items-center gap-3 text-sm">
              {info.email && <span className="hidden sm:inline max-w-[220px] truncate text-charcoal-600" title={info.email}>{info.email}</span>}
              <button onClick={signOut} className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-semibold text-charcoal-800 hover:bg-ground">
                <LogOut className="h-4 w-4" aria-hidden /> Sign out
              </button>
            </div>
          </header>
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
        </div>

        <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 flex overflow-x-auto border-t border-rule bg-paper md:hidden">
          {[...NAV, ADVANCED].map((n) => link(n, true))}
        </nav>
      </div>
      <CrisisSandboxModal />
      <ExecutionModal isOpen={isReceiptModalOpen} onClose={closeReceiptModal} />
    </ShellProvider>
  );
}
