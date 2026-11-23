"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Send, SlidersHorizontal } from "lucide-react";
import { useFactoryStore } from "@/store/useFactoryStore";
import { riskSummary, statusDetail, statusHeadline } from "@/lib/plainPlan";
import { formatInr } from "@/lib/format";
import { Banner, Btn, Card, INPUT } from "@/components/ui";

function StatusCard() {
  const { orders, statusMode, activeRunId } = useFactoryStore();
  const risk = riskSummary(orders);
  const approved = statusMode === "PROTECTED";
  const bad = risk.count > 0;

  const tone = bad ? "bg-alert text-white" : "bg-forest-deep text-white";
  const headline = approved && !bad ? "Plan approved" : statusHeadline(risk);
  const detail = approved && !bad ? "Your recovery plan is approved. Watch for supplier confirmations." : statusDetail(risk);

  return (
    <section aria-live="polite" className={`rounded-3xl px-6 py-8 sm:px-10 sm:py-10 ${tone}`}>
      <p className="flex items-center gap-2 text-white/80">
        <span className={`status-dot h-2.5 w-2.5 rounded-full ${bad ? "bg-white" : "bg-acid"}`} aria-hidden />
        {bad ? "Needs your attention" : "Today"}
      </p>
      <h1 className={`mt-2 font-display text-[44px] font-extrabold leading-[1.05] tracking-tight sm:text-6xl ${bad ? "text-white" : "text-acid"}`}>
        {headline}
      </h1>
      {bad && <p className="mt-2 text-2xl font-bold sm:text-3xl">{formatInr(risk.penaltyInr)} penalty</p>}
      <p className="mt-3 max-w-lg text-lg text-white/85">{detail}</p>
      {(bad || approved) && activeRunId && (
        <Link href="/problems" className="mt-6 inline-flex items-center gap-2 rounded-xl bg-white px-5 py-2.5 font-semibold text-charcoal-900 hover:bg-acid">
          {approved ? "See your plan" : "See your options"} <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      )}
    </section>
  );
}

function ReportBox() {
  const router = useRouter();
  const { scenarios, scenariosError, simulateCrisis, isSimulating, openCustomCrisisModal } = useFactoryStore();
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  const run = async (scenarioId?: number, custom?: string) => {
    setError("");
    await simulateCrisis(scenarioId, custom);
    const err = useFactoryStore.getState().lastError;
    if (err) setError(err);
    else router.push("/problems");
  };

  return (
    <Card className="p-5 sm:p-6">
      <h2 className="font-display text-xl font-bold">Report a problem</h2>
      <p className="mt-1 text-charcoal-700">Tell us what happened in your own words. We will show what it costs you and your options.</p>
      <form
        className="mt-4 flex flex-col gap-3 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) void run(undefined, text.trim());
        }}
      >
        <input
          aria-label="Describe the problem"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={scenarios[0]?.raw_message ?? "e.g. Chennai shipment delayed 48h"}
          className={`${INPUT} flex-1`}
        />
        <Btn type="submit" busy={isSimulating} disabled={!text.trim()}>
          <Send className="h-4 w-4" aria-hidden /> Check the impact
        </Btn>
      </form>
      {(scenarios.length > 0 || scenariosError) && (
        <div className="mt-5">
          <p className="mb-2 text-sm font-semibold text-charcoal-700">Or try an example</p>
          <div className="flex flex-wrap gap-2">
            {scenarios.map((s) => (
              <Btn key={s.scenario_id} variant="quiet" small disabled={isSimulating} title={s.summary} onClick={() => run(s.scenario_id)}>
                {s.title}
              </Btn>
            ))}
            <Btn variant="quiet" small onClick={openCustomCrisisModal}><SlidersHorizontal className="h-4 w-4" aria-hidden /> Use sliders</Btn>
          </div>
          {scenariosError && <div className="mt-3"><Banner tone="grey">{scenariosError}</Banner></div>}
        </div>
      )}
      {error && <div className="mt-4"><Banner>{error}</Banner></div>}
    </Card>
  );
}

function Activity() {
  const { agentLogs, sourcing } = useFactoryStore();
  const items: { key: string; when: string; text: string }[] = [];
  for (const l of agentLogs) items.push({ key: `log-${l.id}`, when: l.created_at, text: l.message || l.tool_output_summary });
  for (const r of sourcing?.rfqs ?? []) {
    if (r.reply_text) items.push({ key: `rfq-${r.id}`, when: "", text: `${r.supplier_name.split(" (")[0]} replied: “${r.reply_text}”` });
  }
  const recent = items.slice(-6).reverse();
  return (
    <section>
      <h2 className="mb-3 font-display text-xl font-bold">Recent activity</h2>
      {recent.length === 0 ? (
        <p className="text-charcoal-600">Nothing has happened yet. Updates from the system and your suppliers will show up here.</p>
      ) : (
        <Card className="divide-y divide-rule">
          {recent.map((a) => (
            <p key={a.key} className="flex items-start justify-between gap-4 px-4 py-3">
              <span className="min-w-0 break-words text-charcoal-900">{a.text}</span>
              {a.when && <time className="shrink-0 text-sm text-charcoal-500" dateTime={a.when}>{new Date(a.when).toLocaleTimeString("en-IN", { timeStyle: "short" })}</time>}
            </p>
          ))}
        </Card>
      )}
    </section>
  );
}

export default function TodayPage() {
  return (
    <div className="space-y-8">
      <StatusCard />
      <ReportBox />
      <Activity />
    </div>
  );
}
