"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check } from "lucide-react";
import { callApi } from "@/lib/api";
import { useApiData } from "@/lib/useApiData";
import { supabase } from "@/lib/supabase";
import { DEMO_FACTORY_ID } from "@/lib/demo";
import { RISK_PROFILES } from "@/lib/forms";
import { formatInr, groupIndian, roleLabel } from "@/lib/format";
import { Banner, Btn, Card, Loading } from "@/components/ui";
import { FactoryForm, LineForm, OrderForm, SupplierForm } from "@/components/EntityForms";
import { ImportButtons, LINE_IMPORT, ORDER_IMPORTS, STOCK_IMPORTS, SUPPLIER_IMPORT } from "@/components/ImportButtons";

const STEPS = ["Your factory", "Production lines", "Suppliers", "Orders and stock"];

function Progress({ step, onStep, maxStep }: { step: number; onStep: (n: number) => void; maxStep: number }) {
  return (
    <ol className="mb-8 flex flex-wrap gap-2" aria-label="Setup steps">
      {STEPS.map((label, i) => (
        <li key={label}>
          <button
            disabled={i > maxStep}
            onClick={() => onStep(i)}
            aria-current={i === step ? "step" : undefined}
            className={`flex items-center gap-2 rounded-full py-1.5 pl-1.5 pr-4 text-[15px] font-semibold disabled:opacity-50 ${i === step ? "bg-forest text-white" : "bg-white text-charcoal-700 border border-rule"}`}
          >
            <span className={`grid h-6 w-6 place-items-center rounded-full text-sm ${i === step ? "bg-acid text-acid-text" : i < step ? "bg-forest text-white" : "bg-ground"}`}>
              {i < step ? <Check className="h-3.5 w-3.5" aria-hidden /> : i + 1}
            </span>
            {label}
          </button>
        </li>
      ))}
    </ol>
  );
}

function Nav({ onBack, onNext, nextLabel = "Next", skippable }: { onBack?: () => void; onNext: () => void; nextLabel?: string; skippable?: boolean }) {
  return (
    <div className="mt-8 flex flex-wrap items-center gap-3 border-t border-rule pt-5">
      {onBack && <Btn variant="quiet" onClick={onBack}>Back</Btn>}
      <Btn onClick={onNext}>{nextLabel}</Btn>
      {skippable && <button onClick={onNext} className="text-[15px] font-semibold text-charcoal-600 underline underline-offset-4 hover:text-charcoal-900">Skip for now</button>}
    </div>
  );
}

function BasicsStep({ settings, onDone }: { settings: any | null; onDone: () => void }) {
  return (
    <>
      <h2 className="font-display text-2xl font-extrabold">Tell us about your factory</h2>
      <p className="mb-5 mt-1 max-w-xl text-charcoal-700">A few basics. You can change any of this later on the Factory page.</p>
      {settings ? (
        <>
          <Banner tone="green">{settings.name} is set up.</Banner>
          <Nav onNext={onDone} nextLabel="Continue" />
        </>
      ) : (
        <Card className="p-5"><FactoryForm onDone={onDone} /></Card>
      )}
    </>
  );
}

function LinesStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const lines = useApiData<{ lines: any[] }>("/api/v1/lines");
  const list = lines.data?.lines ?? [];
  const [formKey, setFormKey] = useState(0);
  return (
    <>
      <h2 className="font-display text-2xl font-extrabold">Your production lines</h2>
      <p className="mb-5 mt-1 max-w-xl text-charcoal-700">Add each line with how fast it normally runs. If you run overtime, say how much extra it gives.</p>
      {lines.error && <Banner>{lines.error}</Banner>}
      {list.length > 0 && (
        <ul className="mb-5 divide-y divide-rule rounded-2xl border border-rule bg-paper">
          {list.map((l) => (
            <li key={l.line_id} className="flex justify-between gap-3 px-4 py-3"><span className="font-semibold">{l.name}</span><span className="text-charcoal-700">{groupIndian(l.rated_units_per_hour)} units / h</span></li>
          ))}
        </ul>
      )}
      <Card className="p-5"><LineForm key={formKey} onDone={() => { setFormKey((k) => k + 1); void lines.reload(); }} /></Card>
      <div className="mt-4"><ImportButtons kinds={[LINE_IMPORT]} onDone={lines.reload} /></div>
      <Nav onBack={onBack} onNext={onNext} skippable={list.length === 0} nextLabel={list.length ? "Next" : "Next without lines"} />
    </>
  );
}

function SuppliersStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const sup = useApiData<{ suppliers: any[] }>("/api/v1/suppliers");
  const list = sup.data?.suppliers ?? [];
  const [formKey, setFormKey] = useState(0);
  return (
    <>
      <h2 className="font-display text-2xl font-extrabold">Your suppliers</h2>
      <p className="mb-5 mt-1 max-w-xl text-charcoal-700">The people you would call if parts run short. Say how reliable each one is, and we will plan around it.</p>
      <dl className="mb-5 grid gap-2 rounded-2xl border border-rule bg-paper p-4 text-[15px] sm:grid-cols-3">
        {Object.entries(RISK_PROFILES).map(([k, v]) => (
          <div key={k}><dt className="font-semibold capitalize">{k} risk</dt><dd className="text-charcoal-700">{v}</dd></div>
        ))}
      </dl>
      {sup.error && <Banner>{sup.error}</Banner>}
      {list.length > 0 && (
        <ul className="mb-5 divide-y divide-rule rounded-2xl border border-rule bg-paper">
          {list.map((s) => (
            <li key={s.id} className="flex justify-between gap-3 px-4 py-3"><span className="font-semibold">{s.name}</span><span className="text-charcoal-700">{roleLabel(s.sourcing_role)}</span></li>
          ))}
        </ul>
      )}
      <Card className="p-5"><SupplierForm key={formKey} onDone={() => { setFormKey((k) => k + 1); void sup.reload(); }} /></Card>
      <div className="mt-4"><ImportButtons kinds={[SUPPLIER_IMPORT]} onDone={sup.reload} /></div>
      <Nav onBack={onBack} onNext={onNext} skippable={list.length === 0} nextLabel={list.length ? "Next" : "Next without suppliers"} />
    </>
  );
}

function OrdersStep({ onBack, onFinish }: { onBack: () => void; onFinish: () => void }) {
  const orders = useApiData<{ orders: any[] }>("/api/v1/orders");
  const list = orders.data?.orders ?? [];
  const [formKey, setFormKey] = useState(0);
  return (
    <>
      <h2 className="font-display text-2xl font-extrabold">Orders and stock</h2>
      <p className="mb-5 mt-1 max-w-xl text-charcoal-700">Bring in your Tally or Excel files, or add an order by hand. Rows with problems are listed so you can fix them.</p>
      <ImportButtons kinds={[...STOCK_IMPORTS, ...ORDER_IMPORTS]} onDone={orders.reload} />
      <h3 className="mb-3 mt-8 font-display text-lg font-bold">Or add an order by hand</h3>
      {list.length > 0 && (
        <ul className="mb-5 divide-y divide-rule rounded-2xl border border-rule bg-paper">
          {list.map((o) => (
            <li key={o.order_id} className="flex justify-between gap-3 px-4 py-3"><span className="font-semibold">{o.client}</span><span className="text-charcoal-700">{groupIndian(o.required_qty)} units, {formatInr(o.sla_penalty_inr)} if late</span></li>
          ))}
        </ul>
      )}
      <Card className="p-5"><OrderForm key={formKey} onDone={() => { setFormKey((k) => k + 1); void orders.reload(); }} /></Card>
      <Nav onBack={onBack} onNext={onFinish} nextLabel="Done, take me to Today" skippable={false} />
    </>
  );
}

export default function SetupPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState<any | null>(null);
  const [step, setStep] = useState(0);
  const [maxStep, setMaxStep] = useState(0);
  const [canDemo, setCanDemo] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState("");

  const refreshSettings = async () => {
    const s = await callApi("/api/v1/factory/settings");
    setSettings(s.ok ? s.data : null);
    return s.ok;
  };

  useEffect(() => {
    void (async () => {
      if (supabase) {
        const { data } = await supabase.auth.getSession();
        if (!data.session) return window.location.assign("/login");
      }
      const mine = await callApi<{ factories: unknown[] }>("/api/v1/my/factories");
      if (mine.ok && (mine.data?.factories.length ?? 0) > 0) {
        router.replace("/");   // already in a factory: never create another here; the shell offers the picker
        return;
      }
      const exists = await refreshSettings();
      if (exists) {
        setStep(1);
        setMaxStep(3);
      }
      const demo = await callApi(`/api/v1/factory/settings?factory_id=${DEMO_FACTORY_ID}`);
      setCanDemo(demo.ok && demo.data?.role === "owner");
      setLoading(false);
    })();
  }, [router]);

  const goto = (n: number) => {
    setStep(n);
    setMaxStep((m) => Math.max(m, n));
  };

  const loadDemo = async () => {
    setDemoBusy(true);
    setDemoError("");
    const r = await callApi("/api/v1/reset", "POST", { factory_id: DEMO_FACTORY_ID });
    setDemoBusy(false);
    if (!r.ok) return setDemoError(r.error);
    window.location.assign("/");
  };

  const signOut = async () => {
    await supabase?.auth.signOut();
    window.location.assign("/login");
  };

  return (
    <div className="app-root min-h-screen">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-4 py-5">
        <span className="flex items-center gap-2 font-display text-lg font-extrabold tracking-tight">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-acid"><span className="h-2.5 w-2.5 rounded-sm bg-forest" /></span>
          CascadeZero
        </span>
        <button onClick={signOut} className="rounded-lg px-2.5 py-1.5 text-sm font-semibold text-charcoal-700 hover:bg-white">Sign out</button>
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-16">
        {loading ? (
          <Loading />
        ) : (
          <>
            <h1 className="mb-1 font-display text-[32px] font-extrabold leading-tight tracking-tight">Set up your factory</h1>
            <p className="mb-6 text-charcoal-700">Four short steps. You can skip anything and finish it later.</p>
            {canDemo && (
              <Card className="mb-6 flex flex-wrap items-center justify-between gap-3 p-4">
                <p className="max-w-md text-charcoal-800">Just looking around? Load the demo factory with sample lines, suppliers and orders.</p>
                <Btn variant="accent" busy={demoBusy} onClick={loadDemo}>Load demo factory</Btn>
              </Card>
            )}
            {demoError && <div className="mb-4"><Banner>{demoError}</Banner></div>}
            <Progress step={step} onStep={setStep} maxStep={maxStep} />
            {step === 0 && <BasicsStep settings={settings} onDone={async () => { await refreshSettings(); goto(1); }} />}
            {step === 1 && <LinesStep onBack={() => setStep(0)} onNext={() => goto(2)} />}
            {step === 2 && <SuppliersStep onBack={() => setStep(1)} onNext={() => goto(3)} />}
            {step === 3 && <OrdersStep onBack={() => setStep(2)} onFinish={() => router.push("/")} />}
          </>
        )}
      </main>
    </div>
  );
}
