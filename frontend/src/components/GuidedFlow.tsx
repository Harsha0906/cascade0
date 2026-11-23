"use client";

import React, { useState } from "react";
import { Check, ChevronDown, FileText, Zap } from "lucide-react";
import { useFactoryStore, type PlaybookOption } from "@/store/useFactoryStore";
import { PROBLEM_SUPPLIER_STATUSES, focusOrder, shortfallText, throttledLinesText } from "@/lib/twinGraph";
import { formatHours, formatInr, formatInrShort, groupIndian, plural } from "@/lib/format";
import { FLOW_STEPS, costLine, onTimeChance, planSummary, planTitle, stepIndex, type FlowStep } from "@/lib/plainPlan";
import { SourcingPanel } from "./SourcingPanel";
import { ClientPanel } from "./ClientPanel";
import { Badge, Banner, Btn, Card } from "./ui";

function Stepper({ step, onStep }: { step: FlowStep; onStep: (s: FlowStep) => void }) {
  const cur = stepIndex(step);
  return (
    <ol className="mb-6 flex items-center gap-1 overflow-x-auto" aria-label="Steps">
      {FLOW_STEPS.map((s, i) => {
        const state = i < cur ? "done" : i === cur ? "now" : "next";
        return (
          <li key={s.id} className="flex items-center gap-1">
            <button
              onClick={() => onStep(s.id)}
              aria-current={state === "now" ? "step" : undefined}
              className={`flex items-center gap-2 whitespace-nowrap rounded-full py-1.5 pl-1.5 pr-4 text-[15px] font-semibold ${
                state === "now" ? "bg-forest text-white" : "text-charcoal-700 hover:bg-white"
              }`}
            >
              <span className={`grid h-6 w-6 place-items-center rounded-full text-sm ${state === "now" ? "bg-acid text-acid-text" : state === "done" ? "bg-forest text-white" : "bg-ground text-charcoal-600"}`}>
                {state === "done" ? <Check className="h-3.5 w-3.5" aria-hidden /> : i + 1}
              </span>
              {s.label}
            </button>
            {i < FLOW_STEPS.length - 1 && <span className="h-px w-5 bg-rule" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}

function ImpactStep({ onNext }: { onNext: () => void }) {
  const { orders, productionLines, suppliers, activeOrderId, shortfallInfo } = useFactoryStore();
  const order = focusOrder(orders, activeOrderId);
  const short = shortfallInfo?.shortfall_units ?? order?.shortfall_units ?? 0;
  const lines = throttledLinesText(productionLines);
  const delayed = suppliers.filter((s) => PROBLEM_SUPPLIER_STATUSES.includes(s.status));
  if (!order) return <Banner tone="grey">No order is affected.</Banner>;
  return (
    <div className="space-y-4">
      <Card className="p-6">
        <p className="text-charcoal-600">Order {order.order_id} for {order.client}</p>
        <p className="mt-1 font-display text-[40px] font-extrabold leading-none tracking-tight text-alert">{plural(short, "unit")} short</p>
        {shortfallInfo && <p className="mt-3 max-w-xl text-charcoal-700">{shortfallText(shortfallInfo)}</p>}
        <dl className="mt-5 grid gap-4 sm:grid-cols-3">
          <div><dt className="text-sm text-charcoal-600">Penalty if late</dt><dd className="text-xl font-bold">{formatInr(order.sla_penalty_inr)}</dd></div>
          <div><dt className="text-sm text-charcoal-600">Needed</dt><dd className="text-xl font-bold">{groupIndian(order.required_qty)} units</dd></div>
          <div><dt className="text-sm text-charcoal-600">Due</dt><dd className="text-xl font-bold">{formatHours(order.hours_remaining)}</dd></div>
        </dl>
      </Card>
      <Card className="p-5">
        <h2 className="mb-2 font-display text-lg font-bold">What is affected</h2>
        <ul className="space-y-1.5 text-charcoal-800">
          <li>{lines ? `Production: ${lines}.` : "All production lines are running normally."}</li>
          <li>
            {delayed.length
              ? `Suppliers delayed: ${delayed.map((s) => `${s.name.split(" (")[0]}${s.delay_hours ? ` (${s.delay_hours} h late)` : ""}`).join(", ")}.`
              : "No supplier is reporting a delay."}
          </li>
        </ul>
      </Card>
      <Btn onClick={onNext}>See your plans</Btn>
    </div>
  );
}

function PlanCard({ plan, index, chosen, onChoose }: { plan: PlaybookOption; index: number; chosen: boolean; onChoose: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <article className={`flex flex-col rounded-2xl border bg-paper p-5 ${chosen ? "border-forest ring-2 ring-forest" : "border-rule"}`}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-display text-lg font-bold">{planTitle(plan, index)}</h3>
        {plan.recommended && <Badge tone="lime">Recommended</Badge>}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-3">
        <div><dt className="text-sm text-charcoal-600">Cost</dt><dd className="text-xl font-bold">{costLine(plan)}</dd></div>
        <div><dt className="text-sm text-charcoal-600">On-time chance</dt><dd className="text-xl font-bold">{onTimeChance(plan)}</dd></div>
      </dl>
      <p className="mt-3 flex-1 text-charcoal-800">{planSummary(plan)}</p>
      {!plan.feasible && <p className="mt-2 text-sm font-semibold text-alert">Not enough capacity: {plural(plan.uncovered_units, "unit")} would still be short.</p>}
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="mt-3 flex items-center gap-1 text-sm font-semibold text-forest">
        Why this plan? <ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <div className="mt-2 space-y-1.5 rounded-xl bg-ground p-3 text-sm text-charcoal-800">
          <p>{plan.description}</p>
          <p>Expected cost including penalty risk: <strong>{formatInrShort(plan.expected_cost_inr)}</strong></p>
          <p>Penalty this avoids: <strong>{formatInrShort(plan.sla_penalty_prevented_inr)}</strong>; you keep <strong>{formatInrShort(plan.net_sla_saved_inr)}</strong> after paying for the plan.</p>
          {plan.confidence_ci_low_pct != null && <p>On-time chance is most likely between {Math.round(plan.confidence_ci_low_pct)}% and {Math.round(plan.confidence_ci_high_pct ?? plan.confidence_pct)}%.</p>}
          {plan.vendor_allocations.length > 0 && (
            <ul className="list-disc pl-5">
              {plan.vendor_allocations.map((a) => (
                <li key={a.supplier_id}>{a.supplier_name.split(" (")[0]}: {plural(a.units_allocated, "unit")}, {formatInrShort(a.total_cost_inr)}, arrives in {a.lead_time_hours} h</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <Btn variant={chosen ? "primary" : "quiet"} className="mt-4" onClick={onChoose} aria-pressed={chosen}>
        {chosen ? <><Check className="h-4 w-4" aria-hidden /> Chosen</> : "Choose this plan"}
      </Btn>
    </article>
  );
}

function PlansStep({ onNext }: { onNext: () => void }) {
  const { playbooks, selectedPlaybookId, selectPlaybook, solverMeta } = useFactoryStore();
  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-charcoal-700">
        We compared the ways you could still deliver. The recommended plan is the cheapest one that is safe enough, counting the penalty you risk if it fails.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        {playbooks.map((p, i) => (
          <PlanCard key={p.id} plan={p} index={i} chosen={p.id === selectedPlaybookId} onChoose={() => selectPlaybook(p.id)} />
        ))}
      </div>
      {solverMeta?.capacity_exhausted && <Banner tone="grey">Even with every option, you cannot fully cover this order. Asking the customer for more time may be needed.</Banner>}
      <Btn onClick={onNext}>Next: ask suppliers</Btn>
    </div>
  );
}

function AskStep({ onNext }: { onNext: () => void }) {
  return (
    <div className="space-y-5">
      <Card className="p-5">
        <h2 className="font-display text-lg font-bold">Ask your suppliers first</h2>
        <p className="mb-3 mt-1 text-charcoal-700">Send a quick question to the suppliers in your plan before you commit. Nothing is ordered yet.</p>
        <SourcingPanel />
      </Card>
      <Card className="p-5">
        <h2 className="font-display text-lg font-bold">Ask the customer for more time</h2>
        <p className="mb-3 mt-1 text-charcoal-700">If the plan is tight, you can ask for a few extra hours. You review the message before it is sent.</p>
        <ClientPanel />
      </Card>
      <Btn onClick={onNext}>Next: approve</Btn>
    </div>
  );
}

function ApproveStep() {
  const { playbooks, selectedPlaybookId, executePlaybook, isExecuting, lastError, statusMode, executionReceipt, openReceiptModal, orders, activeOrderId } = useFactoryStore();
  const plan = playbooks.find((p) => p.id === selectedPlaybookId) ?? playbooks.find((p) => p.recommended);
  const order = focusOrder(orders, activeOrderId);
  if (!plan) return <Banner tone="grey">Choose a plan first.</Banner>;
  const done = statusMode === "PROTECTED" || Boolean(executionReceipt);
  const index = playbooks.findIndex((p) => p.id === plan.id);
  const lineHours = Object.entries(plan.overtime_line_hours ?? {}).filter(([, h]) => h > 0);
  return (
    <Card className="p-6">
      <p className="text-charcoal-600">{done ? "Approved" : "Ready to approve"}</p>
      <h2 className="font-display text-2xl font-extrabold">{planTitle(plan, index)}</h2>
      <p className="mt-1 text-charcoal-800">{planSummary(plan)} {costLine(plan)} spend, {onTimeChance(plan)} on-time chance.</p>
      <p className="mt-4 font-semibold">Approving prepares these drafts. Nothing is sent automatically.</p>
      <ul className="mt-2 space-y-1.5 text-charcoal-800">
        <li className="flex gap-2"><Check className="mt-1 h-4 w-4 shrink-0 text-forest" aria-hidden />{plan.vendor_allocations.length ? `Purchase order for ${plan.vendor_allocations.map((a) => a.supplier_name.split(" (")[0]).join(", ")}.` : "No supplier order needed."}</li>
        <li className="flex gap-2"><Check className="mt-1 h-4 w-4 shrink-0 text-forest" aria-hidden />{plan.overtime_hours ? `Overtime notice: ${lineHours.map(([l, h]) => `${l} ${h} h`).join(", ") || `${plan.overtime_hours} h`}.` : "No overtime notice needed."}</li>
        <li className="flex gap-2"><Check className="mt-1 h-4 w-4 shrink-0 text-forest" aria-hidden />Message to {order?.client || "the customer"} with the on-time chance.</li>
      </ul>
      <div className="mt-6">
        {done ? (
          <Btn onClick={openReceiptModal}><FileText className="h-4 w-4" aria-hidden /> View the drafts</Btn>
        ) : (
          <Btn variant="accent" busy={isExecuting} disabled={!plan.feasible} onClick={() => executePlaybook(plan.id)}>
            <Zap className="h-4 w-4" aria-hidden /> Approve this plan
          </Btn>
        )}
      </div>
      {lastError && <div className="mt-3"><Banner>{lastError}</Banner></div>}
    </Card>
  );
}

/** The four-step problem flow: Impact, Plans, Ask suppliers, Approve. */
export function GuidedFlow() {
  const statusMode = useFactoryStore((s) => s.statusMode);
  const [step, setStep] = useState<FlowStep>(statusMode === "PROTECTED" ? "approve" : "impact");
  const go = (s: FlowStep) => () => setStep(s);
  return (
    <div>
      <Stepper step={step} onStep={setStep} />
      {step === "impact" && <ImpactStep onNext={go("plans")} />}
      {step === "plans" && <PlansStep onNext={go("ask")} />}
      {step === "ask" && <AskStep onNext={go("approve")} />}
      {step === "approve" && <ApproveStep />}
    </div>
  );
}
