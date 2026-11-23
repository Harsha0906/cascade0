# CascadeZero — Neuro-Symbolic AI Crisis Control Tower & 2.5D Digital Twin

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14.2-black.svg?style=flat&logo=next.js)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-orange.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![PuLP](https://img.shields.io/badge/PuLP-MILP%20Solver-blue.svg?style=flat)](https://coin-or.github.io/pulp/)
[![Supabase](https://img.shields.io/badge/Supabase-Realtime%20Postgres-3ECF8E.svg?style=flat&logo=supabase)](https://supabase.com)
[![TailwindCSS](https://img.shields.io/badge/Tailwind-Rinesk%20Glass-38B2AC.svg?style=flat&logo=tailwind-css)](https://tailwindcss.com)

> **Disruption-response copilot and digital twin for discrete manufacturing (demo plant).**  
> Pairs an **LLM for reading messy alerts and narrating decisions (Gemini, configurable)** with a **PuLP mixed-integer program and Monte Carlo simulation** that make every numeric decision, so the LLM never does the arithmetic. A human approves every plan.

---

## ⚡ The Core Problem: Why LLM-Only Agents Fail in Factories

When an Indian EV battery plant faces compound disruptions (e.g., an NH48 highway flood delaying battery casing trucks while Robotic Welding Line 2 throttles due to thermal overheating), standard generative AI agents fail catastrophically:

1. **Arithmetic Hallucinations:** Generative LLMs cannot reliably perform constrained optimization over 15+ variables (overtime rates, transit delays, tier-2 vendor pricing, SLA penalty tiers).
2. **Subjective Bias:** An operations prompt will charter expensive air freight (\$7,000 flat) to avoid SLA delays; a financial prompt will hoard capital and cause customer SLA breach.
3. **No Shop-Floor Verification:** Generative chat outputs cannot generate valid Tally Prime XML accounting vouchers or Modbus PLC machine speed commands.

### The CascadeZero Solution: Neuro-Symbolic Multi-Agent Architecture

```
                  ┌──────────────────────────────────────────────┐
                  │          UNSTRUCTURED DISRUPTION FEED        │
                  │  (Driver text / simulated PLC / ERP CSV)     │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │          BLAST-RADIUS DETECTIVE AGENT        │
                  │    • Gemini Entity Extractor (NLP)           │
                  │    • Causal Graph SQL Blast-Radius Mapper    │
                  └──────────────────────┬───────────────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   │                                           │
                   ▼                                           ▼
   ┌───────────────────────────────┐           ┌───────────────────────────────┐
   │     OPERATIONS HAWK AGENT     │           │       CFO WATCHDOG AGENT      │
   │  • Objective: Minimize Delay  │ ◄───────► │  • Objective: Maximize Margin │
   │  • Demands: BlueDart Air Cargo│  REBUTTAL │  • Vetoes Air Charter Waste   │
   │  • Authorizes 8h Max Overtime │   CYCLE   │  • Demands Peenya Regional SME│
   └───────────────┬───────────────┘           └───────────────┬───────────────┘
                   │                                           │
                   └─────────────────────┬─────────────────────┘
                                         │ Competing Proposals
                                         ▼
                  ┌──────────────────────────────────────────────┐
                  │       MATHEMATICAL ARBITRATOR AGENT          │
                  │    • Symbolic PuLP MILP Optimization Solver  │
                  │    • 1,000-run seeded Monte Carlo            │
                  │    • Ranks by risk-adjusted expected cost    │
                  └──────────────────────┬───────────────────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   │                                           │
                   ▼                                           ▼
   ┌───────────────────────────────┐           ┌───────────────────────────────┐
   │   2.5D DIGITAL TWIN COCKPIT   │           │      HITL ONE-TAP EXECUTION   │
   │  • Organic Sage Glass (Rinesk)│           │  • Draft Tally Prime XML PO   │
   │  • Executive vs Studio Views  │           │  • Draft shift notice (text)  │
   │  • Custom Scenario Sandbox    │           │  • Draft client SLA notice    │
   └───────────────────────────────┘           └───────────────────────────────┘
```

---

## 🌟 Key Capabilities

### 1. 👔 Executive Story View vs 🏭 2.5D Twin Studio
- **Executive Mode:** Eliminates cognitive clutter. Shows the plain-English crisis narrative, the Ops vs. CFO debate summary, the PuLP mathematical proof, and a single thumb-friendly **`[⚡ APPROVE PLAN B & EXECUTE]`** action.
- **2.5D Twin Studio:** Interactive React Flow canvas built from `/api/v1/factory` and `/api/v1/state` (one node per supplier, line and order), showing causal blast radii for whatever the factory contains.

### 2. 🎛️ Custom Crisis Scenario Studio
- **Preset Scenarios:** NH48 Highway Flood (150 casings), Severe Cyclone Collapse (350 casings with automatic multi-agent rebuttal loop), Attibele Border Toll Strike (180 casings).
- **Freeform Natural Language:** Type any custom message naming any line(s), supplier and order of the factory (*e.g., "Truck breakdown near Krishnagiri, 120 casings short, Line 2 running at 50%"*). See "Disruption format" below.
- **Interactive Sliders:** Adjust shortfall units (25–450u), transit delay (6–96h), and one speed slider per production line (0–100%) on the fly.

### 3. 🏭 Real Shop-Floor SME Integration
- **`cascade_sync.py`:** Watches local on-premise folders for exported Tally ERP / Excel CSV sheets.
- **`simulator_plc.py`:** Generates *synthetic* thermal and speed ticks and POSTs them as JSON over HTTP. It does not speak Modbus/OPC-UA; a real plant needs an edge collector.
- **Draft Tally Prime XML PO:** One Purchase Order voucher per supplier, XML-escaped, with party and inventory entries. Not yet validated against a live Tally instance; ledgers/stock item must exist and GST ledgers are not included.

### 4. 📱 Mobile Field Controller (`/mobile`)
- Dedicated handheld web UI for shop-floor supervisors with one-tap scenario injection and instant recovery authorization.

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10+
- Node.js 18+
- Supabase Account (Free Tier)
- Gemini API Key

### 1. Clone & Set Up Backend

```bash
git clone https://github.com/Harsha0906/cascade0.git
cd cascade0/backend

# Install Python dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env: SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY, CASCADE_API_KEY (optional GEMINI_MODEL; the built-in default is `gemini-3.1-flash-lite`)

# Start FastAPI server
python -m app.main
```
Backend runs at: `http://localhost:8000`

### 2. Set Up Frontend

```bash
cd ../frontend

# Install Node dependencies
npm install

# Configure environment (set CASCADE_API_KEY to the same value as the backend; server-side only)
cp .env.local.example .env.local

# Start Next.js dev server
npm run dev
```
Frontend runs at: `http://localhost:3000`  
Mobile Field Controller: `http://localhost:3000/mobile`

### 3. Database

Run `supabase/schema.sql`, then `supabase/migrations/001_rls_and_audit.sql` in the Supabase SQL editor.
The migration enables Row-Level Security (browser = read-only) and adds approval audit columns.
After it, backend writes require `SUPABASE_SERVICE_ROLE_KEY`.
Then apply `002_sourcing_agent.sql`, `003_factory_model.sql`, `004_durable_state.sql`, `005_generic_disruptions.sql` and `006_inventory.sql` in order.
`004_durable_state.sql` adds `analysis_runs`, `sourcing_sessions`, `execution_receipts`, `webhook_events`,
the atomic `execute_plan_tx` function and a `schema_migrations` table.
`005_generic_disruptions.sql` adds the `scenarios` table (preset disruptions per factory) and new `disruption_events` columns, and records `schema_migrations` level 5.
`006_inventory.sql` adds `items`, `stock_levels`, `inbound_shipments`, `order_lines`, `orders.priority`, `orders.due_at` (absolute deadline, backfilled as now + `hours_remaining` for orders that have none), `factories.stock_item_code` and a nullable `scenarios.shortfall_units`, seeds the demo plant's inventory, and records level 6, which is now required. Its seed `UPDATE`s are guarded so a re-run does not overwrite edited data; re-run it after upgrading to add `due_at`.

Check it with `GET /healthz`, which returns
`{"storage", "db", "migration_level", "required_migration_level", "ready"}` and HTTP 200 when ready,
503 otherwise. The backend logs an error at startup if the database is below level 6 (production refuses to start).

### Storage modes

| Mode | When | Behaviour |
|---|---|---|
| `supabase` | `SUPABASE_URL` and a Supabase key are set | All state is in Postgres. Any database failure raises and the API returns **503**; there is no silent fallback to memory |
| `offline` | No Supabase credentials | State lives in an in-process mirror, lost on restart. Demo and tests only; refused when `CASCADE_ENV=production` |

### 4. Run the Tests

```bash
cd ../backend
python -m unittest discover -s tests -t .
cd ../frontend
npm test        # vitest: digital-twin graph builder and store
```
Offline suite (no Supabase, LLM or WhatsApp calls): solver correctness, infeasibility reporting,
ranking, Monte Carlo sensitivity, Tally XML well-formedness, API auth, webhook signatures,
WhatsApp approver allowlist, idempotent execution and CSV import.

`python test_step6.py` is a separate **live** smoke test that uses the keys in `.env`. It covers:
- Legacy Tally CSV Ingestion
- PLC Overheat Telemetry
- Phone WhatsApp Webhook Emulation
- Multi-Agent Audit Trail Verification
- HITL Tally XML Purchase Order Generation
- Factory Seed Reset

---

## 🧭 Disruption format

An alert (free text via `raw_message`, a WhatsApp message, or a preset) may name **any** line(s), supplier and order of the factory.
Extraction produces a delay, a shortfall, per-line speeds, an affected supplier and an order; `backend/app/disruption.py` maps the references to ids.
Required: a shortfall, a speed for every named line, and a resolvable supplier when there is a delay. Nothing is invented: the old defaults
(48h, 50%, 150 units, `EV-402`) are gone, so a message that omits these is rejected.
Unknown or ambiguous references, a missing shortfall, a line without a speed, a delay with no resolvable supplier and negative numbers return
**422** (or a WhatsApp reply naming what is missing); nothing is written.

- `POST /api/v1/simulate-crisis` takes `{scenario_id? | raw_message?, override_delay_hours?, override_shortfall_units?, override_line_speeds?: {line_id: 0..100}, order_id?}`.
  Neither `scenario_id` nor `raw_message` is a 422. `extracted_parameters` in the response has `delay_hours`, `line_impacts` (`line_id`, `name`, `speed_pct`, `temp_celsius`),
  `affected_supplier_id`, `shortfall_units`, `affected_order_id`, `order_selection`, `other_order_shortfalls`, `source` and `overridden_by_preset_or_slider`.
- `GET /api/v1/scenarios` lists the preset scenarios from the `scenarios` table (migration `005_generic_disruptions.sql`).
- The WhatsApp status reply lists every non-normal line and every at-risk order. Vendor enquiries to flat-fee vendors ask for "a dedicated delivery ... for a flat fee".
- MILP variables are named by index, so ids such as `L-B` and `L_B` cannot collide.

## 📦 Inventory-Based Shortfall

The shortfall is computed from the factory's inventory instead of being typed into the alert (migration `006_inventory.sql`; `backend/app/inventory.py`).

```
available = on_hand + inbound_before_deadline − reserved_for_higher_priority
shortfall = min(demand, max(0, demand − available))
```

The shortfall never exceeds the order's own demand: when higher-priority orders take all the supply
(`available` < 0), the explanation says so instead of charging their deficit to this order.

- **demand**: the order's line quantity for the planning item (`order_lines`).
- **on_hand**: `stock_levels` for that item.
- **inbound_before_deadline**: quantity on `OPEN` inbound shipments whose ETA, shifted by the delay for the delayed supplier's shipments, falls before the order's deadline (boundary inclusive). An OPEN shipment whose original ETA has already passed is *overdue*: it has not arrived, so it is not counted (the explanation reports the overdue quantity).
- **reserved_for_higher_priority**: line quantities of other unfinished orders that rank ahead, ranked by `(priority, hours to deadline, order_id)` (lower priority number wins; default 100). *Unfinished* means any status except `DELIVERED` and `CANCELLED`: an order whose risk was accepted (`RISK_ACCEPTED`, after approving a no-action plan) still ships, so it still reserves stock. An order without a priority is rejected (422), never ranked by a guess.
- **Deadline:** each order has an absolute `due_at`. Every deadline (the inventory check, the blast radius `hours_remaining` and the MILP / Monte Carlo deadline) is `due_at − now`, so it counts down. `hours_remaining` is kept for display and recomputed from `due_at` on every read. An order created before `due_at` existed falls back to its stored `hours_remaining` (static, does not count down); re-import it with a due date. An order already past its due time is rejected (422).
- **Delay scope:** the alert's delay shifts every OPEN shipment from the delayed supplier, not only the one the message refers to.

**Precedence:** explicit override (`override_shortfall_units` / slider) > inventory-computed > number stated in the alert text > **422**. The response's `extracted_parameters` carries `shortfall_source` (`override`, `inventory` or `alert_text`), the full `shortfall_breakdown` and `alert_stated_shortfall` (the number the alert itself stated, if any, when inventory was used; the dashboard mentions it, as "alert said N; not used", only when it differs from the computed value). Missing or malformed inventory data is rejected, not guessed.

**Order selection:** `order_selection` says how the order was chosen: `override` (request `order_id` or preset), `stated` (named in the alert), `only_order` (the factory has one order) or `inventory`. When an alert describes a disruption (a supplier delay or a line impact) but names no order, the shortfall is computed for every open order of the factory with a line for the planning item, and the most urgent order that is short is chosen (the most urgent order when none is short). The narration says so, and `other_order_shortfalls` lists the other orders' computed shortfalls (`[{order_id, shortfall}]`). So "Chennai shipment delayed 48h" on the demo plant resolves to EV-402, 150 short. With no inventory data the alert must still name the order (422).

**Single planning item:** each factory names one `stock_item_code` (the demo plant: `CASING`); the shortfall is computed for that item only. Multi-item bills of material are not modelled.

### Import endpoints

All require the API key. Body `{"filename", "csv_content"}`; response `{success, filename, imported_count, errors, warnings}`. Valid rows are imported even when others fail (`errors` lists `{line, error}`; `warnings` lists skipped or caveated rows).

**Each inventory file is a full snapshot**, so re-import the whole export each time:
- stock summary: an item of the factory not in the file is set to stock 0 (Tally hides zero-balance items);
- open purchase orders: an OPEN PO not in the file is marked `CLOSED` (received or cancelled), so a received PO is never counted both in stock and as inbound;
- sales order lines: the file replaces all lines of each order it lists.

Every zeroing, removal or closure is listed in `warnings` (with `line: null`). Rows with errors are left unchanged, and a file whose header cannot be read changes nothing.

| Endpoint | File |
|---|---|
| `POST /api/v1/ingest/stock-summary` | Tally stock summary (total rows skipped with a warning; optional `Unit`/`UOM` column sets a new item's unit, else `pcs`) |
| `POST /api/v1/ingest/open-purchase-orders` | Open POs; overdue POs are imported with a warning, and a re-import never reopens a received PO. `Pending Quantity` wins over `Quantity` |
| `POST /api/v1/ingest/sales-order-lines` | Order lines per order and item |
| `POST /api/v1/ingest/erp-csv` | Order upsert (required columns validated; updates never overwrite status or shortfall). Deadline from `due_date` (IST) or `hours_remaining` (from import time), stored as `due_at`; optional `priority` (a new order without it gets 100, the lowest) |

Tally header aliases, quantity formats (`1,20,000`, `500 Nos`, `500.00`) and IST dates (`20-Nov-2026`, date alone = 17:00 IST) are documented in [`samples/tally/README.md`](samples/tally/README.md), with sample files that reproduce the demo seed. The dashboard shows the shortfall explanation and its source, and has a CSV import picker.

## ✅ What Is Real vs Simulated

| Component | Status |
|---|---|
| MILP allocation (vendors, per-line overtime, deadline feasibility, throughput gap computed from the factory's line data; disruption inputs are any per-line speeds, a delay and a shortfall) | Real (PuLP + HiGHS/CBC). Infeasible inputs are reported, not hidden |
| Shortfall | Real when computed from inventory (stock, open POs, order lines, order priority) imported from Tally/Excel CSV or the seed; an override or the number in the alert text takes the other precedence paths and is labelled in the UI. Single planning item per factory; no multi-item BOM |
| Plan ranking | Real: argmin of `cost + (1 − P_on_time) × SLA penalty` |
| Monte Carlo on-time probability | Real, seeded; distributions are **assumptions** for the demo plant |
| **Sourcing Agent** | Real agent loop: sends enquiries (not orders) to the vendors in a plan, reads replies (Gemini or regex, English/Hinglish), and re-plans with confirmed capacity/price/ETA, asking the next vendor when one declines, offers less, or times out (max 3 rounds). WhatsApp or simulated channel |
| Speed vs Cost scenarios | Planning scenarios, not agents: each proposal is a solver output (speed = expedite-first, cost = cheapest feasible); the risk check fires on computed risk (weak vendor, infeasibility, confidence gap) and the cost scenario re-solves |
| Disruption extraction | Gemini (given the factory's line, supplier and order ids) or a regex fallback that only takes cue-bound numbers and never guesses; `backend/app/disruption.py` resolves references to ids. Missing or unresolvable input is rejected, never defaulted. The UI shows which path ran |
| Digital twin | Built from the factory model (`/api/v1/factory`) and live state (`/api/v1/state`): one node per supplier, line and order. Layout is generic, not geographic |
| LLM | Extracts parameters from free text and narrates. The UI shows when it fell back to regex/templates |
| Vendor costs, capacities, lead times | Loaded per factory from the database (`suppliers`, `vendor_history`, `production_lines`, `factories`) |
| PLC telemetry | Simulated, HTTP JSON; `line_id` is required (unknown line returns 404) |
| Weather | OpenWeatherMap city weather if a key is set; otherwise shown as offline |
| WhatsApp | Meta Cloud API with HMAC verification; approvals only from allow-listed numbers |
| Analysis runs, sourcing sessions, execution receipts | Stored in Postgres (`analysis_runs`, `sourcing_sessions`, `execution_receipts`); in offline mode in process memory. Approving a run twice returns the original receipt with `already_executed: true`; a different plan for an executed run is a 409 |
| Execution | Generates **drafts** (Tally XML, notices). Nothing is sent to suppliers automatically |

## Which components are agents

| Component | Kind | What it does |
|---|---|---|
| Disruption Detective | **Agent** | Perceives the alert (Gemini or regex extraction), decides the resolution of entities to factory ids, and acts on state (blast-radius update) |
| Sourcing Agent | **Agent** | Sends enquiries to vendors, reads replies, re-plans with confirmed capacity |
| Client Agent | **Agent** | Drafts a deadline-extension request to the client; a named human approves before it is sent; the client's answer triggers a re-plan and restarts sourcing |
| Speed scenario (expedite-first) | Planning scenario | MILP with the expedite vendor forced on, scored by Monte Carlo. Not an agent |
| Cost scenario (cheapest feasible) | Planning scenario | Unconstrained cost-minimal MILP, scored by Monte Carlo. Not an agent |
| Arbitrator (solver ranking) | Solver step | Ranks all playbooks by `cost + (1 − P_on_time) × SLA penalty`. Not an agent |

The LLM only narrates the scenario and solver steps ("explain this computed result"); it makes no decisions there.

## 🤝 Sourcing Agent

The planner's vendor numbers are assumptions; the Sourcing Agent replaces them with what vendors actually say.

1. After an analysis, click **Confirm with suppliers first** (dashboard) or `POST /api/v1/sourcing/start {run_id}`.
2. The agent sends an enquiry to each vendor in the chosen plan — explicitly *not* a purchase order.
3. Replies arrive over WhatsApp (`SOURCING_MODE=whatsapp`, vendor numbers in `suppliers.whatsapp_number`) or are typed on the dashboard (simulated mode, or a reply received by phone).
4. Each reply becomes a structured offer. Declines and timeouts remove that vendor; partial or re-priced offers update capacity, price and lead time for this run only.
5. When no enquiry is outstanding it re-solves. If the best plan needs an unconfirmed vendor, it asks that vendor (next round); otherwise it hands a **confirmed plan** back for human approval (`<run_id>-S<round>`).

Only one PO can ever be created per analysis — the original run and its sourced re-plan share an idempotency key.
Apply `supabase/migrations/002_sourcing_agent.sql` for vendor numbers and the enquiry audit table, then `supabase/migrations/003_factory_model.sql` (must be applied after 002) for the per-factory model the planner reads.

Known limits: WhatsApp messages are de-duplicated by Meta message id and recorded before processing, so a replayed approval or vendor reply never runs twice. If processing fails unexpectedly after recording (database error or other exception) the id is released and the webhook returns 503/500, so Meta's retry is processed; messages that were handled (including error replies sent to the sender) stay recorded.
Sourcing sessions use optimistic concurrency (`version` column; 409 after 3 conflicting retries), but multiple backend workers are not yet supported for sourcing.

## 🔐 Security Setup

- `CASCADE_API_KEY` gates every mutating endpoint. The Next.js middleware injects it server-side; it never reaches the browser. This is an operator-level gate, not per-user auth.
- `META_APP_SECRET` verifies WhatsApp webhook signatures; `WA_APPROVER_NUMBERS` lists who may approve.
- `ALLOWED_ORIGINS` replaces the old `*` CORS policy.
- `CASCADE_ENV=production` refuses to start if any of the above is missing, and disables `/reset` and the Twilio sandbox.
- Execution uses the plan the server computed for a `run_id`, once per run. Costs are never accepted from the client.

## 🏗️ Repository Architecture

```
cascade0/
├── backend/
│   ├── app/
│   │   ├── inventory.py          # Inventory-based shortfall formula
│   │   ├── importers.py          # Tally CSV parsers (stock, POs, order lines)
│   │   ├── agents/
│   │   │   ├── graph.py          # LangGraph 4-Agent Cyclic StateGraph
│   │   │   └── tools.py          # SQL Blast-Radius, Vendor Memory & Gemini Extraction
│   │   ├── config.py             # Pydantic v2 Environment Settings
│   │   ├── db.py                 # Supabase Realtime Client & Seed Engine
│   │   ├── main.py               # FastAPI Endpoints & Webhook Gateways
│   │   ├── schemas.py            # Pydantic Request/Response Models
│   │   └── solver.py             # PuLP MILP Solver & Tally XML Generators
│   ├── cascade_sync.py           # On-Premise Tally Folder Watcher Daemon
│   ├── simulator_plc.py          # Shop-Floor Machine Telemetry Streamer
│   └── test_step6.py             # 6-Step End-to-End Verification Suite
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx          # Dual-Mode Command Center (Executive + Twin)
│   │   │   ├── mobile/page.tsx   # Handheld Mobile Field Controller
│   │   │   └── globals.css       # Anastasia Cherniak "Rinesk" Design System
│   │   ├── components/
│   │   │   ├── TopKpiBar.tsx     # View Mode Switcher & Financial Risk Header
│   │   │   ├── ExecutiveStoryView.tsx # Streamlined 3-Step Decision Flow
│   │   │   ├── CrisisSandboxModal.tsx # Freeform & Slider Crisis Injector
│   │   │   ├── FlowCanvas.tsx    # 2.5D React Flow Digital Twin Canvas
│   │   │   ├── CustomNodes.tsx   # Industrial Supply Chain & Machine Nodes
│   │   │   ├── AgentStream.tsx   # Live Autonomous Agent Audit Trail
│   │   │   ├── PlaybookSidebar.tsx # Multi-Plan Trade-Off Comparison
│   │   │   └── ExecutionModal.tsx# Draft Tally XML PO & notices
│   │   └── store/
│   │       └── useFactoryStore.ts# Zustand Global Factory State & Realtime Sync
│
├── samples/tally/            # Sample Tally CSV exports + format guide
├── supabase/
│   ├── schema.sql                # Tables & seed data
│   └── migrations/               # Row-Level Security & audit columns
├── PRODUCTION_ROADMAP.md         # Commercial B2B SaaS Architecture Blueprint
├── run.md                        # Master Startup & Daemon Command Guide
└── README.md
```

---

## 📄 License
MIT License. Built for industrial discrete manufacturing and resilient AI operations.
