# CascadeZero — Roadmap to a Production-Quality System

_Created 2026-11-18. Baseline: commit `abf1f16` on branch `improve/solver-security-sourcing-agent`
(panel score 5.7/10). This document is the spec for every phase plan in this folder._

## Goal

Turn CascadeZero from "an honest demo of one fictional plant" into a system any discrete
manufacturer can configure with its own data, trust with real decisions, and run reliably —
then add a free two-way chat channel (Telegram).

## Principles (apply to every phase)

1. **Numbers come from data and solvers, never from code constants or the LLM.** The LLM reads
   free text and explains; the optimiser decides; a human approves.
2. **Fail loudly.** Missing or invalid data produces a clear error naming the field — never a
   silent default, a fallback that hides failure, or a fake "Optimal".
3. **Every claim in the UI or README is true of the code.** Anything simulated is labelled.
4. **Each phase ships working software**: tests green, type-check clean, demo still works.

## Definition of Done (gate for every phase)

- [ ] All backend tests pass: `cd backend && python -m unittest discover -s tests -t .`
- [ ] Frontend type-check passes: `cd frontend && node_modules/.bin/tsc --noEmit -p .`
- [ ] New behaviour has tests written first (red → green), including the phase's Review Focus cases.
- [ ] The three demo scenarios still produce sensible, explainable recommendations (or the
      changed result is listed and justified in the phase plan).
- [ ] No secrets in the diff (`.env`, `.env.local` stay gitignored; staged-diff secret scan clean).
- [ ] README "What Is Real vs Simulated" table updated if behaviour changed.
- [ ] One commit per task; an independent review of the whole phase before merging.

"No flaws" is the target; the honest mechanism for approaching it is this gate plus an
independent review after every phase, not a promise. Anything found later becomes a task.

---

## Phase order and why this order

| # | Phase | Depends on | Why it comes here |
|---|---|---|---|
| 1 | Data-driven factory model | — | Every later phase needs vendors/lines/settings to be data, not code |
| 2 | Durable persistence, fail-loud DB | 1 | Long-running agents (2+, 6) and audits need state that survives restarts |
| 3 | Generic disruptions + data-driven digital twin | 1 | Removes the last "Line 2 / EV-402" assumptions from input, state and UI |
| 4 | Inventory-based shortfall (ERP data) | 1, 3 | Shortfall must come from stock and orders, not from a chat message |
| 5 | Disruption-aware risk + learned vendor reliability | 1, 2, 4 | Risk must react to the actual disruption and real delivery history |
| 6 | Client Agent — true multi-agent system | 2, 5 | Needs durable sessions and meaningful risk to negotiate deadlines |
| 7 | Identity and multi-tenancy | 1, 2 | Real approver identity; each factory sees only its own data |
| 8 | AI quality: evals and observability | 3, 6 | Measures extraction accuracy and narration honesty on the final agent set |
| 9 | Ship-ready: deploy, CI, frontend robustness, accessibility | all | Hardening once behaviour is stable |
| 10 | Telegram channel | 2, 6, 7 | Free two-way chat, built on the finished core |

---

## Phase 1 — Data-driven factory model

**What changes.** Vendors (capacity, price, lead time, risk, reliability), production lines
(rated output, overtime rate/output/limit), and factory settings (QA time, safety stock,
production hours) are loaded from the database into a validated `FactoryModel`. The solver,
agents and Sourcing Agent take that model as input. Overtime is modelled per line.

**Why.** Judge 1: "a demo, not a product… vendors are Python constants… a plant with 40 vendors
cannot use any of it." Judge 3: "every constant is hard-coded; the suppliers and production_lines
tables are never read by the solver."

**How.** New `app/factory_model.py` (dataclasses + loader + validation); migration
`003_factory_model.sql` adds the missing columns and a `factories` table; solver functions take
`model` and `line_speeds` instead of module constants; tool stubs whose results were discarded
are removed. Detailed plan: `2026-11-18-phase1-data-driven-factory.md`.

**Done when.** A second, different factory defined only as data (no code edits) produces correct
plans in tests; invalid factory data raises `FactoryDataError` naming the fields; the demo
scenarios still recommend the same plan types.

## Phase 2 — Durable persistence, fail-loud database

**What changes.** Analysis runs, Sourcing sessions, enquiries and execution receipts are stored
in Postgres. When Supabase is configured, a failed write raises instead of silently writing to
the in-memory mirror (the mirror stays only for explicit offline/demo mode). Plan execution
(PO insert + order/supplier/line updates) runs as one database transaction (Postgres function
via `rpc`). Webhook messages are de-duplicated by Meta message id.

**Why.** Judge 5: "silent split-brain persistence… a PO insert that fails is reported as success";
"runs and idempotency live only in process memory, lost on restart, break with >1 worker."

**How.** Tables `analysis_runs`, `sourcing_sessions`, `execution_receipts`, `webhook_events`;
`run_store` and `sourcing` read/write them through a repository module; `OFFLINE_MODE` setting
selects the mirror explicitly; a `/healthz` endpoint checks DB connectivity and migration level.

**Done when.** Restarting the backend mid-sourcing loses nothing; killing the DB makes writes
return 503 (not fake success); duplicate webhook deliveries are processed once; two workers
cannot both execute the same run.

## Phase 3 — Generic disruptions + data-driven digital twin

**What changes.** A disruption names any affected line(s), supplier(s), part and order —
not `line2_*` fields. Extraction returns `affected_lines: [{line_id, speed_pct, temp_c}]`,
`affected_supplier_id`, `affected_order_id`, validated against the factory model. The digital
twin canvas renders nodes from factory data instead of five hard-coded nodes.

**Why.** "EV-402", "LINE-2", "Lines 1 & 3" and `line2_speed_pct` appear in 25+ places across
backend and frontend; a different factory cannot express its own disruption.

**How.** New extraction schema + mapping step that resolves names to IDs (fuzzy match against the
model, rejected if unknown); `line_speeds` dict flows through graph state; frontend store builds
nodes/edges from `/api/v1/factory`; scenario presets become data.

**Done when.** A disruption on any line/order of the second test factory runs end-to-end; no
`line2_` or `EV-402` literals remain outside seed data and tests.

## Phase 4 — Inventory-based shortfall

**What changes.** Shortfall = demand for the affected order − (on-hand stock + inbound quantities
arriving before the deadline − allocations to higher-priority orders). The chat alert only
describes the disruption (which shipment/line, how long); the numbers come from data.

**Why.** Judge 1: "no data wedge… the shortfall comes from regex or Gemini reading a free-text
message, not from stock positions. Without master data the MILP optimises made-up numbers."

**How.** Tables `items`, `stock_levels`, `inbound_shipments`, order lines; CSV importers for the
common Tally/Excel exports (stock summary, open purchase orders, sales order register) with
row-level validation; a `compute_shortfall(order_id, disruption)` function with tests.

**Done when.** Importing the sample Tally CSVs and reporting "Chennai shipment delayed 48h"
yields the shortfall without the user typing a number; malformed CSV rows are reported, not
guessed.

## Phase 5 — Disruption-aware risk + learned reliability

**What changes.** Monte Carlo lead-time distributions depend on the reported disruption (route
blocked → that route's vendors get longer/variable leads; weather alerts raise shock
probability). Vendor reliability is computed from recorded promised-vs-actual delivery dates
(Bayesian update from the seed prior), and every executed PO records its outcome.

**Why.** Judge 3: "the MC rarely changes the decision… P=100% in all three preset scenarios";
Judge 1: "made-up reliability percentages… no vendor-performance learning loop."

**How.** `delivery_outcomes` table; `reliability(vendor)` = Beta posterior; a route→vendor map in
the factory model; MC reads disruption context; Wilson CI stays.

**Done when.** A tight-deadline or route-blocked scenario changes the winner versus the
unblocked case (tested); recording late deliveries lowers that vendor's reliability (tested).

## Phase 6 — Client Agent (true multi-agent)

**What changes.** A Client Agent drafts the extension request (human sign-off), records the
client's answer, and coordinates with the Sourcing Agent: an accepted new deadline makes slower
vendors feasible → Sourcing re-asks; a refusal widens sourcing (expedite vendor); sourcing
failure triggers the Client Agent. Ops/CFO become "planning scenarios" (no persona claims).

**Why.** Judge 2: "functions in costumes… the debate never changed the winner in nine runs."
Only one genuine agent exists today.

**How.** Shared order-level coordination record; agents react to each other's events through it;
renegotiation probability is replaced by the client's actual answer when available.

**Done when.** A test scenario shows the Client Agent's accepted extension changing the Sourcing
Agent's enquiries and the final plan; every component labelled "agent" perceives, decides and
acts.

## Phase 7 — Identity and multi-tenancy

**What changes.** Supabase Auth login on the dashboard; the backend verifies the user's JWT;
`approved_by` comes from the verified session; every table has `factory_id` and RLS allows a
user to read/write only their factories; WhatsApp/Telegram approvers map to user accounts.

**Why.** Judge 5: "no user auth… the audit trail is self-asserted… RLS gives anon full read
access, including purchase_orders."

**Done when.** Two users in two factories cannot see each other's data (tested with RLS); the
shared operator API key is no longer needed by the browser path.

## Phase 8 — AI quality: evals and observability

**What changes.** A labelled set of 50+ disruption and vendor-reply messages (English, Hinglish,
noisy) with expected fields; an eval command reporting precision/recall per field for Gemini and
regex paths; a guard that rejects narration containing numbers not present in the computed
facts; per-node latency and token logging.

**Why.** Judge 2: "no LLM evals… Gemini output is not validated against the facts."

**Done when.** `python -m app.evals` prints per-field accuracy; narration with an invented number
falls back to the template (tested).

## Phase 9 — Ship-ready

**What changes.** Dockerfiles + docker-compose, GitHub Actions CI (tests, tsc, `next build`),
pinned dependencies, `uvicorn` without reload in production; frontend fetch timeouts, a visible
"backend unreachable" banner, polling when Realtime is off, confirm step on mobile approval,
ARIA labels and text alongside colour status.

**Why.** Judge 5: "no deployment artifacts… 0 aria attributes… backend-down shows stale data."

**Done when.** `docker compose up` runs the whole stack from a clean clone; CI is green on a PR;
an automated accessibility check reports no critical issues.

## Phase 10 — Telegram channel

**What changes.** A channel adapter interface (`send_text`, `send_buttons`, inbound parsing) with
WhatsApp and Telegram implementations; Telegram bot for alerts in, plan out, Approve button,
vendor enquiries/replies. Free; no card.

**Done when.** The full disruption → plan → vendor confirmation → approval loop works on
Telegram with the same tests as the WhatsApp path.

---

## Carried forward from Phase 1 (review findings deferred to their owning phase)

- **Phase 2 (DONE):** `get_factory_row`, `reset_to_seed` and the factory loader fall back to the in-memory seed when a live-DB read fails — must raise instead when Supabase is configured. Migration 003 re-run restores demo seed values (header documents it); replace with a versioned migration level check (`/healthz`). Done: DB failures now raise `DatabaseError` (503) when Supabase is configured; the in-memory mirror is offline-only; `schema_migrations` level 4 is checked at startup and by `/healthz`.
- **Phase 3:** PuLP variable names are sanitised ids (`L-B` and `L_B` collide) — switch to index-based names; RFQ text says "an air charter" for any flat-fee vendor; remaining `LINE-2` / `EV-402` literals in graph/tools/main/sourcing; digital twin "Lines 1 & 3" labels.
- **Phase 6:** forcing the expedite vendor at zero shortfall pays its fee in the objective but not in the reported cost — skip Plan A when shortfall is 0, or report it.
- **Phase 9:** CBC fallback (`COIN_CMD`, needs a CBC binary on PATH) is untested because HiGHS is always present — add a CI job without HiGHS.
- **Minor, any phase:** missing-column hint should say "set the column (or apply 003)"; integer columns accept fractional values and round them; no loader test with two factories in the same database; `SolverInputError` webhook replies still echo the message (sender-input errors).
