# Phase 4 — Inventory-Based Shortfall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The shortfall for a disrupted order is computed from stock, inbound shipments and order demand, so an alert only has to describe the disruption ("Chennai shipment delayed 48h").

**Architecture:** Migration 006 adds `items`, `stock_levels`, `inbound_shipments`, `order_lines`, `orders.priority` and `factories.stock_item_code`, and makes `scenarios.shortfall_units` nullable. A pure function in `app/inventory.py` computes the shortfall:

`shortfall = max(0, demand − (on_hand + inbound arriving before the deadline − demand reserved by higher-priority orders))`

For the planning item, shipments from the delayed supplier are shifted by the delay. The detective uses this whenever the order has inventory data. The source of the number is recorded and shown. CSV importers for Tally/Excel exports validate each row and report bad rows, never guess.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / LangGraph / PuLP; Supabase Postgres; Next.js 14 + Zustand; vitest.

**Spec:** `docs/superpowers/plans/2026-11-18-cascadezero-roadmap.md` — "Phase 4", "Principles", "Definition of Done".

## Global Constraints

- Numbers come from data and solvers, never from code constants or the LLM. Fail loudly with a clear error naming the field: 422 for user input, row-level errors for CSV.
- Done when: "Importing the sample Tally CSVs and reporting 'Chennai shipment delayed 48h' yields the shortfall without the user typing a number; malformed CSV rows are reported, not guessed."
- **Shortfall precedence:**
  1. An explicit override (slider/API `override_shortfall_units`) wins.
  2. Otherwise, when the order has inventory data (order lines for the factory's planning item), the computed value wins, even if the alert text states a number. The response reports both, and the narration says the alert's number was not used.
  3. Otherwise the number stated in the alert is used.
  4. Otherwise → 422 "shortfall_units not stated and order {id} has no inventory data".
  `shortfall_source` ∈ {"override", "inventory", "alert_text"} is in the run and the API response.
- Time: inbound ETAs and order deadlines are compared in hours from the run's `now` (UTC). The deadline is `now + orders.hours_remaining`. Functions take `now` as a parameter, so tests are deterministic.
- Single planning item: the MILP plans one item, `factories.stock_item_code`. Other items' shortfalls are reported but not planned (stated in the README).
- **Backend tests:** `cd backend && PYTHONIOENCODING=utf-8 python -W ignore -m unittest discover -s tests -t .`; the frontend runs `npm test` and `node_modules/.bin/tsc --noEmit -p .`.
- **Safety:** `backend/.env` points at the live Supabase/Gemini. Every probe imports `tests._offline_env` first.
- **Code hygiene:** raw-string regexes; control-char scan `[]`; one commit per task ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never commit `.env*`, `frontend/tsconfig.tsbuildinfo` or `__pycache__`.
- **Changed results (justified):**
  - Scenario 1's preset drops its typed shortfall (NULL). It now uses inventory: on hand 350, Chennai inbound 500 due in 20 h, EV-402 needs 500, deadline 38 h, delay 48 h → 150 short. That is the same number as today, now derived from data.
  - Scenarios 2 and 3 keep their stated shortfall as explicit what-ifs (labelled "override").

## Review Focus

1. A CSV with a bad quantity ("12a", "-5", empty), a bad date, an unknown item, or an unknown supplier/order → that row is listed with line number and reason, valid rows import, and nothing is defaulted. *Test in Task 3.*
2. An inbound shipment arriving exactly at the deadline, or after the delay shifts it past the deadline → counted / not counted consistently. The boundary is `eta_hours <= deadline_hours` counts. *Test in Task 2.*
3. Higher-priority orders reserve stock first; equal priority → earlier deadline first, then order id. A lower-priority order's demand never reduces this order's supply. *Test in Task 2.*
4. An order with inventory data, and an alert that also types a different number → the computed number is used and both are reported. *Test in Task 4.*
5. An order without order lines for the planning item and no stated number → 422 naming the order, nothing written. *Test in Task 4.*

---

### Task 1: Migration 006 and inventory data access

**Files:**
- Create: `supabase/migrations/006_inventory.sql`
- Modify: `supabase/schema.sql`, `backend/app/db.py` (seed rows, mirror tables, `REQUIRED_MIGRATION_LEVEL = 6`, mirror `schema_migrations` 1–6, helpers)
- Modify: `backend/app/factory_model.py` (`FactoryModel.stock_item_code: str` loaded from `factories.stock_item_code`; missing → `FactoryDataError` naming the column)
- Test: `backend/tests/test_inventory_data.py` (new), plus existing migration-level tests updated 5 → 6

**Interfaces:**
- **SQL** (re-run safe; guard requires `schema_migrations` version 5):
  - `items(factory_id TEXT NOT NULL, item_code TEXT NOT NULL, name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'pcs', PRIMARY KEY(factory_id, item_code))`
  - `stock_levels(factory_id TEXT NOT NULL, item_code TEXT NOT NULL, on_hand_qty INT NOT NULL CHECK (on_hand_qty >= 0), as_of TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY(factory_id, item_code))`
  - `inbound_shipments(shipment_id TEXT PRIMARY KEY, factory_id TEXT NOT NULL, item_code TEXT NOT NULL, supplier_id TEXT NOT NULL, qty INT NOT NULL CHECK (qty > 0), eta TIMESTAMPTZ NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN')`
  - `order_lines(order_id TEXT NOT NULL, item_code TEXT NOT NULL, qty INT NOT NULL CHECK (qty > 0), PRIMARY KEY(order_id, item_code))`
  - `ALTER TABLE orders ADD COLUMN IF NOT EXISTS priority INT NOT NULL DEFAULT 100`
  - `ALTER TABLE factories ADD COLUMN IF NOT EXISTS stock_item_code TEXT`
  - `ALTER TABLE scenarios ALTER COLUMN shortfall_units DROP NOT NULL`
  - RLS on with anon read policies; version 6.
  - **Demo seed:**
    - item `CASING` "Aluminium Battery Casing"
    - stock 350
    - shipment `SHP-CHN-0001` (SUP-CHN-01, CASING, 500, eta `NOW() + 20 hours`)
    - order lines EV-402 → CASING 500 and EV-405 → CASING 300
    - priorities EV-402 = 10, EV-405 = 20
    - `factories.stock_item_code = 'CASING'` for apex-volt-blr2
    - `UPDATE scenarios SET shortfall_units = NULL WHERE factory_id='apex-volt-blr2' AND scenario_id = 1`
- **Python (`db.py`, all fail-loud in supabase mode):**
  - `get_items(factory_id)`
  - `get_stock_levels(factory_id) -> dict[item_code, int]`
  - `get_inbound_shipments(factory_id, status="OPEN") -> list[dict]`
  - `get_order_lines(order_ids: Sequence[str]) -> list[dict]`
  - `reset_to_seed` restores these seeds; the shipment's eta = reset time + 20 h.

- [ ] **Step 1:** Failing tests:
  - offline helpers return the demo seeds (stock CASING 350; one OPEN shipment of 500 from SUP-CHN-01 with eta ≈ now+20 h ±1 min; order lines EV-402 500 / EV-405 300; priorities 10/20)
  - `load_factory_model().stock_item_code == "CASING"`
  - a factory row without `stock_item_code` → FactoryDataError naming it
  - `/healthz` required level 6
  - `get_scenarios` scenario 1 has `shortfall_units is None`
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Full suite green. Tests that relied on scenario 1's typed 150 must still pass after Task 4; until then, if scenario-1 API tests fail because shortfall is NULL and the pipeline can't compute yet, list them (interim, Task 4 restores).
- [ ] **Step 5:** Commit `feat: inventory tables and seeds (migration 006)`.

### Task 2: `compute_shortfall`

**Files:**
- Create: `backend/app/inventory.py`
- Test: `backend/tests/test_inventory.py` (new)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) ShipmentView(shipment_id: str, supplier_id: str, qty: int, eta_hours: float, delayed_by_hours: float, counted: bool)`
  - `@dataclass(frozen=True) ShortfallBreakdown(order_id: str, item_code: str, demand: int, on_hand: int, inbound_before_deadline: int, reserved_for_higher_priority: int, available: int, shortfall: int, deadline_hours: float, shipments: tuple[ShipmentView, ...])` with `to_dict()` (JSON-safe) and `explanation() -> str`, e.g. `"500 needed − (350 on hand + 0 inbound before the 38h deadline − 0 reserved for higher-priority orders) = 150 short"`
  - `class InventoryDataError(DisruptionResolutionError)`
  - `compute_shortfall(order_id: str, item_code: str, orders: Sequence[dict], order_lines: Sequence[dict], stock: Mapping[str, int], shipments: Sequence[dict], now: datetime, delayed_supplier_id: Optional[str] = None, delay_hours: float = 0) -> ShortfallBreakdown`

  `orders` rows carry `order_id`, `hours_remaining`, `priority` and `status`. `shipments` rows carry `shipment_id`, `supplier_id`, `item_code`, `qty`, `eta` (ISO string or datetime) and `status`.

**Rules:**
- **Demand** = the `qty` of the order's line for `item_code`. No line → `InventoryDataError("order {id} has no line for item {item}")`.
- **On hand** = `stock[item_code]`. Missing → `InventoryDataError` naming the item.
- **Shipments:** only `OPEN` ones for the item count.
  - `eta_hours = (eta − now)` in hours, plus `delay_hours` if `supplier_id == delayed_supplier_id`.
  - A shipment counts if `eta_hours <= deadline_hours`.
  - Already-arrived shipments (eta_hours ≤ 0) count. Note in the code that they should have been booked into stock.
- **Reserved** = Σ demand for the item of other orders that are not finished and rank ahead. Finished statuses are `DELIVERED`, `CANCELLED` and `RISK_ACCEPTED`. Ranking is by `(priority, hours_remaining, order_id)` ascending.
- **Available** = `on_hand + inbound_before_deadline − reserved`. It may be negative; the shortfall is `max(0, demand − available)`.

- [ ] **Step 1: Failing tests** (fixed `now`):
  - The demo numbers with a 48 h Chennai delay → 150, with the explanation string as above.
  - No delay → 0 short (850 available).
  - A 6 h delay → 0.
  - The ETA exactly at the deadline counts; 1 minute later it doesn't.
  - EV-405 (priority 20): EV-402 reserves 500 → available 350+500−500 = 350 vs demand 300 → 0. With a 48 h delay, EV-405's deadline of 110 h still counts the shipment (68 h).
  - Equal priority → the earlier deadline reserves first.
  - A finished higher-priority order doesn't reserve.
  - Missing line / missing stock → InventoryDataError naming them.
  - A non-OPEN shipment is ignored.
  - `to_dict` passes `json.dumps`.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Passes.
- [ ] **Step 5:** Commit `feat: compute shortfall from stock, inbound and priorities`.

### Task 3: CSV importers (Tally/Excel) with row-level validation

**Files:**
- Create: `backend/app/importers.py`, `samples/tally/stock_summary.csv`, `samples/tally/open_purchase_orders.csv`, `samples/tally/sales_order_lines.csv`, `samples/tally/README.md` (formats)
- Modify: `backend/app/main.py`:
  - three new endpoints
  - the existing `/api/v1/ingest/erp-csv`: required numeric columns (no silent 0 defaults), sets `factory_id` = default factory, and preserves the existing `status`/`shortfall_units` on update instead of overwriting them
- Test: `backend/tests/test_importers.py` (new), `tests/test_api.py`

**Interfaces:**
- **Pure parsers** (no DB) return `ImportResult(rows: list[dict], errors: list[{"line": int, "error": str}])`:
  - `parse_stock_summary(csv_text, factory_id, known_items)`
  - `parse_open_purchase_orders(csv_text, factory_id, known_items, known_suppliers, today)`
  - `parse_sales_order_lines(csv_text, known_orders, known_items)`
- **Headers** are case-insensitive, with aliases:
  - item code: `item_code` | `Item Code` | `Stock Item Code`
  - item name: `item_name` | `Item Name` | `Name of Item` (stock: creates/updates `items` when the code is new)
  - quantity: `on_hand_qty` | `Closing Quantity` | `Quantity` | `Pending Quantity` | `Qty`
  - PO/shipment id: `shipment_id` | `PO Number` | `Voucher No`
  - supplier: `supplier_id` | `Supplier Code` | `Party Code`
  - due date: `eta` | `Due Date` | `Due on`
  - order: `order_id` | `Order No` | `Sales Order No`
- **Quantities:** digits with optional thousands separators (`1,200` / `1,20,000`), optionally followed by one unit word (`500 Nos`, `500 pcs`). Anything else, negative or empty → row error.
- **Dates:** `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY` and `DD-Mon-YYYY` (Tally `20-Nov-2026`), plus an optional `HH:MM`. ETA = that date/time in IST (UTC+5:30), converted to UTC; a date alone → 17:00 IST. Unparseable → row error.
- **Unknowns:** an unknown supplier, item or order → row error. Duplicate keys within one file → the second is a row error.
- **Endpoints** (API key required; body `{filename, csv_content}` like erp-csv):
  - `POST /api/v1/ingest/stock-summary`
  - `POST /api/v1/ingest/open-purchase-orders`
  - `POST /api/v1/ingest/sales-order-lines`

  Each returns `{success, filename, imported_count, errors}` (`success` = no errors) and upserts only valid rows, fail-loud through db.
- **Sample CSVs** reproduce the demo seeds: stock CASING 350; PO `SHP-CHN-0001` 500 from SUP-CHN-01 due "tomorrow" — the README explains that the date must be edited to a near-future date; lines EV-402/500 and EV-405/300.

- [ ] **Step 1:** Failing tests:
  - Each parser on its sample file → 0 errors and the exact rows.
  - A file mixing good rows with `12a`, `-5`, empty qty, `31-02-2026`, unknown item, unknown supplier, unknown order and a duplicate id → the right line numbers and reasons, good rows kept.
  - `1,200 Nos` → 1200.
  - `20-Nov-2026` → 2026-11-20T11:30Z.
  - The API: an import followed by `get_stock_levels` reflects it.
  - erp-csv: a row missing `sla_penalty_inr` → row error (no silent 0); an imported order gets `factory_id`.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Passes; full suite green.
- [ ] **Step 5:** Commit `feat: Tally/Excel CSV importers with row-level validation`.

### Task 4: Pipeline uses the computed shortfall

**Files:**
- Modify: `backend/app/disruption.py` (`resolve_disruption` gains `shortfall_resolver: Optional[Callable[[str, Optional[str], int], Optional[ShortfallBreakdown]]] = None`)
- Modify: `backend/app/agents/graph.py` (the detective builds the resolver from db data with `now = datetime.now(timezone.utc)`; state gains `shortfall_source`, `shortfall_breakdown`, `alert_stated_shortfall`)
- Modify: `backend/app/main.py` (`extracted_parameters` gains `shortfall_source`, `shortfall_breakdown` (dict or null) and `alert_stated_shortfall`; `run_cascade_pipeline` accepts `now: Optional[datetime] = None` for tests)
- Modify: `backend/app/agents/sourcing.py` (if needed: the sourced re-plan keeps the parent's shortfall)
- Test: `backend/tests/test_inventory_pipeline.py` (new); existing scenario tests

**Interfaces:**
- **Resolver** — `shortfall_resolver(order_id, supplier_id, delay_hours)` returns a `ShortfallBreakdown`. It returns `None` when the order has no order line for the factory's `stock_item_code` (no inventory data). It propagates `InventoryDataError` for broken data, e.g. a missing stock row → 422.
- **Precedence** is per Global Constraints. When the alert stated a number but inventory was used, it is kept as `alert_stated_shortfall` and the detective's log says `"alert said N; using inventory: <explanation>"`.
- **No source** — no override, no inventory and no alert number → `DisruptionResolutionError("shortfall_units not stated and order {id} has no inventory data")`.

- [ ] **Step 1: Failing tests** (offline, demo seeds, fixed `now`):
  - `"Chennai shipment delayed 48h"` → resolves the supplier, delay 48, order. The single-order rule doesn't apply (two orders exist), so the test text is `"Chennai shipment delayed 48h, order EV-402"`. Result: shortfall 150, source `inventory`.
  - The same with `"..., 999 units short"` → 150, `alert_stated_shortfall` 999.
  - The slider override 120 → 120, source `override`.
  - EV-405 with a 48 h delay → 0 short, and the pipeline still completes. With no lines throttled and 0 short, the recommended plan has `total_mitigation_cost_inr == 0` and `confidence_pct == 100`.
  - Delete EV-402's order line, then the text with no number → 422 naming EV-402, nothing written.
  - Scenario 1 via the API → `shortfall_source == "inventory"`, 150, PLAN_B.
  - Scenarios 2 and 3 → source `override` (preset numbers), recommendations unchanged (PLAN_C / PLAN_B).
  - The Done-when flow: import the three sample CSVs through the API into a fresh offline mirror (after deleting the seeded inventory rows), then the alert → 150.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** The full suite is green; scenarios 1/2/3 give PLAN_B/PLAN_C/PLAN_B.
- [ ] **Step 5:** Commit `feat: shortfall computed from inventory in the pipeline`.

### Task 5: Frontend — show where the shortfall came from; import the CSVs

**Files:**
- Modify: `frontend/src/lib/twinGraph.ts` (new helper `shortfallText(params)`)
- Modify: `frontend/src/lib/twinGraph.test.ts`
- Modify: `frontend/src/store/useFactoryStore.ts` (keep `extracted_parameters` of the last run)
- Modify: `frontend/src/components/ExecutiveStoryView.tsx` (show the explanation)
- Modify: `frontend/src/components/CrisisSandboxModal.tsx` (shortfall input optional: blank = "from inventory")
- Modify: `frontend/src/components/TopKpiBar.tsx` (the upload button lets the user pick the file type: Orders (erp-csv) / Stock summary / Open purchase orders / Sales order lines; shows the row errors list, not just the first)

**Interfaces:**
- `shortfallText(p: {shortfall_units: number; shortfall_source: "override" | "inventory" | "alert_text"; shortfall_breakdown?: {explanation?: string} | null; alert_stated_shortfall?: number | null}): string`:
  - inventory → the backend's explanation string (`ShortfallBreakdown.to_dict()` must include `"explanation"`; add it in Task 2 if missing) + `" (alert said N; not used)"` when an alert number was ignored
  - override → `"N short (set manually)"`
  - alert_text → `"N short (from the alert; no inventory data for this order)"`
- The sandbox sends `override_shortfall_units` only when the field is non-empty.

- [ ] **Step 1:** vitest cases for the three sources plus the ignored-alert suffix → fail.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** `npm test`, tsc 0.
- [ ] **Step 4:** Browser check (controller, with the backend up): scenario 1 shows "500 needed − (350 on hand + 0 inbound … ) = 150 short"; importing `samples/tally/stock_summary.csv` reports 0 errors; a deliberately broken CSV lists its row errors.
- [ ] **Step 5:** Commit `feat: dashboard shows shortfall source; CSV import picker`.

### Task 6: Docs, live migration, gate

- [ ] **Step 1:** README:
  - inventory model and shortfall formula
  - precedence rules and the single planning item limitation
  - the CSV formats (link to `samples/tally/README.md`) and import endpoints
  - migration 006
  - "What Is Real vs Simulated" row for shortfall
- [ ] **Step 2:** Roadmap: Phase 4 marked done with a one-line summary.
- [ ] **Step 3:** Gate:
  - backend suite, npm test, tsc
  - control-char scan
  - offline scenarios 1/2/3 → PLAN_B/PLAN_C/PLAN_B
  - the Done-when flow test green
- [ ] **Step 4 (controller):** Apply 006 to the live Supabase; `/healthz` level 6 ready.
- [ ] **Step 5:** Commit `docs: inventory-based shortfall`; final whole-branch review; fix wave.
