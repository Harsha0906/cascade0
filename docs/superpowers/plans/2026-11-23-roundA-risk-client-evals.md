# Round A — Disruption-Aware Risk, Learned Reliability, Client Agent, AI Evals

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver roadmap Phases 5, 6 and 8 in one round. Risk reacts to the reported disruption; vendor reliability is learned from recorded deliveries; a real Client Agent negotiates deadline extensions and coordinates with the Sourcing Agent; extraction quality is measured by an eval command; narration can't invent numbers.

**Architecture:**
- Migration 007 adds `delivery_outcomes` and `order_coordination`.
- Reliability = Beta posterior: the seed history is the prior, recorded outcomes update it, and the loader computes it.
- Disruptions resolve an affected route, and any weather alert. Vendors on the blocked route get their lead time shifted, through `FactoryModel.with_vendor_overrides`, in both the MILP and the Monte Carlo. A weather alert raises the shock probability.
- The Client Agent (`app/agents/client.py`) works through a durable coordination record. It reacts to Sourcing failures, and its accepted or refused answers drive the next Sourcing round. Ops/CFO become labelled "planning scenarios".
- An eval dataset plus `python -m app.evals` report per-field accuracy. A narration guard rejects any number not in the facts.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / LangGraph / PuLP; Supabase Postgres; Next.js 14; vitest.

**Spec:** `docs/superpowers/plans/2026-11-18-cascadezero-roadmap.md` — Phases 5, 6, 8; Principles; Definition of Done. The user approved compressing the phases into rounds ("start round A").

## Global Constraints

- Numbers come from data, solvers or recorded outcomes — never code constants or the LLM. Fail loudly (422 user input, 503 bad factory data).
- **Done when:**
  - **Phase 5:**
    - a route-blocked or tight-deadline scenario changes the winner versus the unblocked case (tested);
    - recording late deliveries lowers that vendor's reliability (tested).
  - **Phase 6:**
    - a test shows the Client Agent's accepted extension changing the Sourcing Agent's enquiries and the final plan;
    - every component labelled "agent" perceives, decides and acts.
  - **Phase 8:**
    - `python -m app.evals` prints per-field accuracy;
    - narration with an invented number falls back to the template (tested).
- **Human sign-off:**
  - The Client Agent never sends anything to a client without an explicit approval call (`approved_by`).
  - Sending uses the existing WhatsApp/simulated channel pattern of the Sourcing Agent (`SOURCING_MODE`).
- **Gate:**
  - backend `cd backend && PYTHONIOENCODING=utf-8 python -W ignore -m unittest discover -s tests -t .`
  - frontend `npm test` and `node_modules/.bin/tsc --noEmit -p .`
  - scenarios 1/2/3 still give PLAN_B / PLAN_C / PLAN_B unless a task lists and justifies a change
- **Safety:** `backend/.env` points at the live Supabase and Gemini. Every probe imports `tests._offline_env` first, and evals run offline unless `--live` is passed explicitly. Never commit `.env*`, `frontend/tsconfig.tsbuildinfo` or `__pycache__`.
- **Hygiene:** raw-string regexes; control-char/BOM scan `[]`; commits end `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Compressed review policy (user-approved):** one review per task, scaled to risk; one final whole-round review plus one fix wave.

## Review Focus

1. A route named in the alert that matches no vendor route → it is ignored with a note in the response (it is not a planning input), never guessed onto a vendor. *(Task 2)*
2. A delivery outcome for an unknown supplier, or with `delivered_at` before `promised_at − 30 days`, or with a missing date → 422. Reliability never leaves [0, 100]. *(Task 1)*
3. A client answer recorded twice, a conflicting answer, or an answer before the request is approved → 409. *(Task 3)*
4. Sourcing ends without full cover while a Client Agent request is already open → no duplicate draft. *(Task 3)*
5. Narration that writes a number in a different format (e.g. "₹1.8L" for 180000, "1,80,000") → accepted when it equals a fact. Any number not in the facts → template. *(Task 5)*

---

### Task 1: Learned vendor reliability (Phase 5a)

**Files:**
- Create: `supabase/migrations/007_learning_and_coordination.sql` (its `delivery_outcomes` part — Task 3 appends `order_coordination` to the same file)
- Create: `backend/app/reliability.py`
- Modify: `backend/app/db.py`, `backend/app/factory_model.py` (loader), `backend/app/main.py` (endpoints, and pending outcomes on execute), `supabase/schema.sql`
- Test: `backend/tests/test_reliability.py`

**Interfaces:**
- **SQL:**
  - `delivery_outcomes(id BIGSERIAL PK, factory_id TEXT NOT NULL, supplier_id TEXT NOT NULL, po_number TEXT NOT NULL, units INT NOT NULL CHECK (units > 0), promised_at TIMESTAMPTZ NOT NULL, delivered_at TIMESTAMPTZ, status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DELIVERED')), recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (po_number, supplier_id))`
  - RLS on with an anon read policy; the guard requires version 6; version 7.
- **`reliability.py`:**
  - `beta_reliability(prior_on_time: int, prior_total: int, outcomes_on_time: int, outcomes_total: int) -> float`: the posterior mean with α = prior_on_time + outcomes_on_time + 1 and β = (prior_total − prior_on_time) + (outcomes_total − outcomes_on_time) + 1. Returns % rounded to 1 decimal.
  - `on_time(promised_at, delivered_at, grace_hours: float = 2.0) -> bool`.
- **Loader:** `Vendor.reliability_pct` = `beta_reliability(vendor_history.on_time_deliveries, vendor_history.past_orders_count, …DELIVERED outcomes for that supplier)`. The `reliability_score_pct` column is no longer the source. Document the prior: the seed history counts as past deliveries. The demo values shift slightly: e.g. 48/50 → 94.2 vs 96.0. List the new values in the report, and check scenarios 1/2/3 keep their winners.
- **API (API key):**
  - `POST /api/v1/deliveries` `{po_number, supplier_id, delivered_at}` sets a PENDING outcome to DELIVERED. Unknown → 404; already delivered → 409.
  - `GET /api/v1/deliveries?status=PENDING`.
  - `_execute` inserts one PENDING outcome per vendor allocation: `promised_at` = execution time + the vendor's `lead_hours`. It sits inside the same transaction path — offline under `_execute_lock` writes, live via an extra `p_outcomes JSONB` param on `execute_plan_tx`. Add this in 007 with `CREATE OR REPLACE FUNCTION` and keep the 8-param signature compatible by giving the new param a default `'[]'`.
- `GET /api/v1/factory` vendors gain `reliability_pct` (already there), `prior_total` and `outcomes_total`.

- [ ] Tests first:
  - `beta_reliability(48, 50, 0, 0) == 94.2`
  - three late deliveries for SUP-HSR-03 lower its reliability, strictly less than before
  - on-time deliveries raise it
  - an unknown supplier → 404; a double record → 409
  - execute creates PENDING outcomes, one per allocated vendor
  - scenarios 1/2/3 winners unchanged
  - control-char scan
- [ ] Commit `feat: vendor reliability learned from recorded deliveries`

### Task 2: Disruption-aware risk (Phase 5b)

**Files:**
- Modify: `backend/app/schemas.py`, `backend/app/disruption.py`, `backend/app/agents/tools.py` (regex: weather cues, route mention), `backend/app/agents/graph.py`, `backend/app/solver.py`
- Test: `backend/tests/test_disruption_risk.py`

**Interfaces:**
- **Extraction:** `DisruptionExtraction` gains `affected_route: Optional[str]` and `weather_alert: bool = False`.
  - The regex sets `weather_alert` on the cues flood, cyclone, heavy rain, storm, landslide, waterlogging.
  - `affected_route` = a substring of any vendor's `route` (normalised) found in the text, e.g. "NH48", "Hosur".
- **`ResolvedDisruption`** gains:
  - `blocked_route: Optional[str]`: the resolved route string. It is the delayed supplier's route if a supplier is delayed and no route is named; otherwise the named route, if it matches exactly one vendor route.
  - `weather_alert: bool`.
- **`risk_adjusted_model(model, disruption) -> FactoryModel`** (in `disruption.py`): every vendor whose `route == blocked_route` gets `lead_hours += delay_hours`. `min_lead_hours` follows via a new override key `min_lead_hours`; extend `with_vendor_overrides` to accept it and `delay_shock_pct`. With `weather_alert`, every vendor's `delay_shock_pct = min(90, 2 × delay_shock_pct)`.
- **Graph:** the detective stores the risk-adjusted model, and every later node (Ops, CFO, arbitrator, MC) uses it. `extracted_parameters` gains `blocked_route`, `weather_alert` and `route_note` (Review Focus 1).

- [ ] Tests first:
  - **Done-when:** scenario-1 numbers with an extra alert "Hosur corridor blocked 30h" make SUP-HSR-03 infeasible or slower, so the recommended plan or its allocation differs from the unblocked run (assert the winner or the allocation for SUP-HSR-03 changes).
  - **Tight deadline:** the same disruption with `hours_remaining` cut so the expedite vendor is needed → the winner changes to PLAN_A (assert).
  - **Weather:** a weather alert lowers the MC confidence of a road-vendor plan versus no alert.
  - **Unknown route:** an unknown route text → `route_note` set, no change to the model.
  - scenarios 1/2/3 still B/C/B, or a listed, justified change.
- [ ] Commit `feat: risk reacts to blocked routes and weather alerts`

### Task 3: Client Agent backend (Phase 6a)

**Files:**
- Modify: `supabase/migrations/007_learning_and_coordination.sql` (append), `supabase/schema.sql`, `backend/app/db.py`
- Create: `backend/app/agents/client.py`
- Modify: `backend/app/agents/sourcing.py` (hooks), `backend/app/main.py` (endpoints), `backend/app/solver.py` (the renegotiation probability is replaced by the actual answer when known)
- Test: `backend/tests/test_client_agent.py`

**Interfaces:**
- **SQL:** `order_coordination(root_run_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, factory_id TEXT NOT NULL, status TEXT NOT NULL, version INT NOT NULL, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`, with optimistic concurrency like `sourcing_sessions`.
- **`client.py`:**
  - `class ClientAgentError(Exception)` with `status_code`.
  - `draft_extension(run_id: str, extension_hours: int, reason: str = "") -> dict`:
    - **Perceives:** the run, the order, and the sourcing state.
    - **Decides:**
      - `extension_hours` must be > 0.
      - The text quotes only data: order id, client, original deadline, new deadline, the cause from the disruption headline, and an offered partial-penalty figure from the order row.
    - **Acts:** stores `DRAFTED`.
  - `approve_extension(run_id, approved_by) -> dict` → `SENT` via the channel. Simulated mode records it; WhatsApp mode uses the client number on the order if the column exists, otherwise 409 "no client contact".
  - `record_client_answer(run_id, accepted: bool, text: str = "", new_deadline_hours: Optional[int] = None, entered_by: str = "operator") -> dict`:
    - Accepted:
      - status `ACCEPTED`;
      - the order's `due_at` is extended;
      - a **re-plan** runs with the longer deadline, so slower vendors become feasible;
      - if a sourcing session exists for the root run, `sourcing.restart_with_plan(...)` re-asks vendors per the new plan.
    - Refused:
      - status `REFUSED`;
      - the re-plan forces expedite to be allowed (the Ops/expedite plan becomes the sourcing target);
      - sourcing restarts widened to include the EXPEDITE vendor.
    - Duplicate, conflicting, or before SENT → 409.
  - `on_sourcing_failed(run_id)`: called by Sourcing when a session ends without full cover. It drafts an extension request automatically (status `DRAFTED`, `drafted_by: "sourcing_failure"`), and does nothing if a coordination record is already open (Review Focus 4).
  - `view(run_id) -> dict`.
- **`sourcing.py`:**
  - `restart_with_plan(root_run_id: str, playbook: dict, reason: str) -> dict` starts a new round on the new plan, with RFQs only for unconfirmed needs.
  - `_finish` with a not-fully-covered status calls `client.on_sourcing_failed`.
- **Solver:** when a coordination record has `ACCEPTED`/`REFUSED` for the order, PLAN_C's acceptance probability is 1.0 / 0.0 instead of `renegotiation_acceptance_prob`.
- **API (API key on writes):**
  - `POST /api/v1/client/draft {run_id, extension_hours, reason?}`
  - `POST /api/v1/client/approve {run_id, approved_by}`
  - `POST /api/v1/client/answer {run_id, accepted, text?, new_deadline_hours?}`
  - `GET /api/v1/client/{run_id}`

- [ ] Tests first:
  - **Done-when:** a scenario where sourcing for the cost plan fails (vendors decline) → the Client Agent auto-drafts. Approve, then answer accepted +48h → the re-plan makes a slower vendor feasible → the Sourcing Agent sends new RFQs to a vendor it had not asked before (or asks different units), and the final recommended plan differs from before. Assert all three.
  - Refused → the next sourcing round includes the EXPEDITE vendor.
  - Review Focus 3 and 4.
  - Every outbound message is blocked before approval.
- [ ] Commit `feat: Client Agent negotiates deadlines and coordinates with Sourcing`

### Task 4: Honest agent labels + Client Agent panel (Phase 6b)

**Files:**
- Modify: `backend/app/agents/graph.py` (agent_name/agent_role strings and narration prompts)
- Modify: `frontend/src/components/AgentPipelineStrip.tsx`, `ExecutiveStoryView.tsx`
- Create: `frontend/src/components/ClientPanel.tsx`
- Modify: `frontend/src/store/useFactoryStore.ts`, `frontend/src/app/page.tsx` (mount the panel next to SourcingPanel), README agent table
- Test: vitest for a new pure helper `clientStatusText(record)`; backend test asserting log names

**Interfaces:**
- Names:
  - "Operations Hawk" → "Speed scenario (expedite-first)"
  - "CFO Watchdog" → "Cost scenario (cheapest feasible)"
  - "Blast-Radius Detective" → "Disruption Detective (agent)"
  - "Arbitrator" stays a solver step: "Arbitrator (solver ranking)"
- Narration prompts no longer say "You are … VP of Finance". They say "Explain this planning scenario's computed result."
- The README table lists which components are agents (Detective: perceives the alert, decides the resolution, acts on state; Sourcing; Client) and which are scenarios or solvers.
- **`ClientPanel`:**
  - shows the coordination status;
  - draft text with Approve & send;
  - an Accepted (+hours) / Refused answer form;
  - errors from the API shown verbatim.

- [ ] vitest + backend tests first; `npm test`, tsc 0, backend suite
- [ ] Commit `feat: honest agent labels; Client Agent panel`

### Task 5: AI quality — evals, narration guard, latency/tokens (Phase 8)

**Files:**
- Create: `backend/evals/disruptions.jsonl` (≥ 50 rows: English, Hinglish, noisy/typo, multi-line, no-number vague, unknown references)
- Create: `backend/evals/vendor_replies.jsonl` (≥ 20 rows)
- Create: `backend/app/evals.py`
- Modify: `backend/app/agents/graph.py` (guard plus trace timing/tokens), `backend/app/agents/tools.py` / `sourcing.py` (timing for extraction calls)
- Test: `backend/tests/test_evals.py`, `backend/tests/test_narration.py`

**Interfaces:**
- **Dataset rows:**
  - disruptions: `{"text": str, "expected": {"delay_hours": int|null, "lines": {line_id: speed}|{}, "supplier_id": str|null, "order_id": str|null, "shortfall_units": int|null, "error": "unknown_line"|"ambiguous"|... |null}}`
  - vendor replies: `{"text", "rfq_units", "expected": {"accepted": bool, "units": int|null, "unit_price_inr": int|null, "eta_hours": float|null}}`
- **`python -m app.evals [--path regex|gemini|both] [--live]`**:
  - Without `--live` it forces offline mode and the regex path only; gemini needs `--live`.
  - Prints a table: per field, the counts of correct / wrong / missed / spurious, and precision/recall.
  - Exits 0. `run_evals(path) -> dict` is importable.
- **`narration_is_grounded(text: str, facts: dict) -> bool`:**
  - Extract numbers from the text (handle ₹, commas, Indian grouping, "L"/"lakh", "Cr", %, decimals).
  - Every number must equal some number in the flattened facts (± rounding at the printed precision, and lakh/crore scaling).
  - Small integers 1–10 are allowed only if they are in the facts. Otherwise → template, with mode `"template-guarded"`.
- **Trace:** each `llm_trace` entry gains `latency_ms`, plus `input_tokens`/`output_tokens` when the Gemini response has usage metadata.

- [ ] Tests first:
  - `run_evals("regex")` runs offline with ≥ 50 rows and returns per-field metrics; the regex `order_id` recall is ≥ 0.9 on the dataset (or record the actual number and assert ≥ the recorded baseline).
  - The guard accepts "₹1.8L" for 180000 and "1,80,000"; rejects an invented "₹2.5L".
  - A mocked Gemini narration with an invented number → template, mode `"template-guarded"`.
  - Trace entries carry `latency_ms`.
- [ ] Commit `feat: extraction evals, grounded narration guard, latency/token tracing`

### Task 6: Docs, live migration, gate, final review

- [ ] README:
  - learned reliability (formula, prior, endpoints);
  - route/weather risk;
  - Client Agent flow and the human sign-off;
  - the agent vs scenario table;
  - the evals command and current numbers;
  - migration 007.
- [ ] Roadmap: Phases 5, 6 and 8 marked done.
- [ ] Gate (see Global Constraints) plus `python -m app.evals` output in the report.
- [ ] Controller: apply 007 live; `/healthz` level 7 ready; live browser check of the Client Agent panel.
- [ ] Final whole-round review (most capable model) plus one fix wave.
