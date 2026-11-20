# Phase 3 — Generic Disruptions + Data-Driven Digital Twin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A disruption can name any line(s), supplier and order of the configured factory, and the digital twin draws whatever lines, suppliers and orders that factory has.

**Architecture:** Extraction (Gemini or regex) returns *references as written* (`"Line 2"`, `"Chennai Precision"`). A new resolution step in `app/disruption.py` maps them to ids from the `FactoryModel` and the factory's orders. If a reference is unknown or ambiguous, it raises a 422 that lists the valid choices, and this happens before any database write. The graph carries `line_impacts` / `line_speeds` / `affected_supplier_id` instead of `line2_*`. Scenario presets move into a `scenarios` table (migration 005). The frontend builds React Flow nodes from `/api/v1/factory` + `/api/v1/state` with a pure, unit-tested `buildTwinGraph`.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / LangGraph / PuLP; Supabase Postgres; Next.js 14 + Zustand + @xyflow/react; vitest (new, frontend unit tests).

**Spec:** `docs/superpowers/plans/2026-11-18-cascadezero-roadmap.md` — "Phase 3", "Principles", "Definition of Done", "Carried forward → Phase 3".

## Global Constraints

- Numbers come from data and solvers, never from code constants or the LLM. No silent defaults: the old regex defaults (delay 48 h, speed 50 %, temp 89 °C, shortfall 150, order EV-402) are removed.
- Fail loudly: missing/invalid input → clear error naming the field (HTTP 422 for user input, 503 for bad factory data).
- Done when: "A disruption on any line/order of the second test factory runs end-to-end; no `line2_` or `EV-402` literals remain outside seed data and tests." Seed data = `backend/app/db.py` seed lists, `supabase/schema.sql`, `supabase/migrations/*.sql`.
- Backend tests: `cd backend && python -m unittest discover -s tests -t .` (use `PYTHONIOENCODING=utf-8`). Frontend: `cd frontend && node_modules/.bin/tsc --noEmit -p .` and `npm test`.
- Regexes are raw strings; no control characters in source (scan with `python -c "import pathlib;print([str(p) for p in pathlib.Path('.').rglob('*.py') if b'\x08' in p.read_bytes()])"` → `[]`).
- One commit per task, message ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.env*`, `frontend/tsconfig.tsbuildinfo`, `__pycache__`.
- The three demo scenarios must give the same recommendations as today (scenario 1 → PLAN_B): presets carry the same numbers, now from the `scenarios` table.
- **Changed behaviour (justified):** a free-text alert that states no shortfall, a line without a speed, or a delay with no resolvable supplier now gets a 422 / WhatsApp reply naming what is missing. Before, it silently used invented defaults.

## Review Focus

1. An alert naming a line, supplier or order the factory doesn't have ("Line 9", "EV-999") → 422 listing the valid ids, and **no** supplier/line/order row is modified. *Test in Task 4.*
2. An ambiguous reference ("Welding Line" matches all three welding lines) → 422 naming the candidates, not a guess. *Test in Task 2.*
3. A vague WhatsApp alert with no numbers → the sender gets a reply saying what is missing; the webhook returns 200, not 500. *Test in Task 5.*
4. Line ids that collide after sanitising (`L-B` and `L_B`) → the MILP stays correct. *Test in Task 1.*
5. A factory with a different number of lines, vendors and orders → every one gets a node and edges; a 503 from `/api/v1/factory` shows an error card instead of crashing the canvas. *Tests in Task 6.*

---

### Task 1: Solver — index-based variable names, generic result fields

**Files:**
- Modify: `backend/app/solver.py` (`_var_name` at ~89, variable creation at ~155-157, `SolverResult` construction at ~722-728, CLI block at ~743-765)
- Modify: `backend/app/schemas.py:103-118` (`SolverResult`)
- Test: `backend/tests/test_solver.py`

**Interfaces:**
- Produces: `SolverResult.line_speeds: dict[str, int]`, which replaces `line2_speed_pct`. Variables are named `x_{i}`, `y_{i}` and `h_{j}` by the vendor/line index in the model.

- [ ] **Step 1: Write failing tests**
```python
def test_colliding_ids_do_not_collide_in_milp(self):
    # small_factory() with lines "L-B" (OT 20u/h, 6h) and "L_B" (OT 10u/h, 2h), and vendors "V-1" and "V_1"
    lp = solve_pulp_milp(model, shortfall=50, line_speeds={"L-B": 50}, deadline=40)
    self.assertEqual(set(lp["overtime_line_hours"]) <= {"L-B", "L_B"}, True)
    self.assertTrue(lp["feasible"])          # both vendors usable → 50 units covered
def test_solver_result_reports_line_speeds(self):
    res = generate_playbooks(small_factory(), 40, 5, {"L-B": 60}, order_id="WO-1", sla_penalty_inr=100_000,
                             partial_penalty_inr=20_000, deadline_hours=30, client="Client")
    self.assertEqual(res.line_speeds, {"L-B": 60})
```
- [ ] **Step 2:** Run `python -m unittest tests.test_solver -v` → the first test fails with PuLP's duplicate-name error, the second with an AttributeError.
- [ ] **Step 3:** Delete `_var_name`; name variables by index (`f"x_{i}"` etc.). Replace `line2_speed_pct=` with `line_speeds=dict(line_speeds)`. Delete the `if __name__ == "__main__":` CLI block, because it hard-codes EV-402.
- [ ] **Step 4:** The full backend suite passes.
- [ ] **Step 5:** Commit `fix: index-based MILP variable names; SolverResult reports line_speeds`.

### Task 2: Disruption extraction schema and resolution

**Files:**
- Create: `backend/app/disruption.py`
- Modify: `backend/app/schemas.py:19-55` (`DisruptionExtraction`)
- Test: `backend/tests/test_disruption.py` (new)

**Interfaces:**
- Produces (schemas.py):
  - `LineImpactExtraction(line: str, speed_pct: Optional[int] (0..100), temp_celsius: Optional[float])`
  - `DisruptionExtraction(source_channel: str = "WHATSAPP", delay_hours: Optional[int] = None, affected_lines: list[LineImpactExtraction] = [], affected_supplier: Optional[str] = None, affected_order: Optional[str] = None, shortfall_units: Optional[int] = None, crisis_headline: str = "", raw_summary: str = "")`

  No field carries a numeric or id default.
- Produces (disruption.py):
  - `class DisruptionResolutionError(SolverInputError)`. Subclassing means main.py's existing 422 handling and WhatsApp replies apply.
  - `@dataclass(frozen=True) LineImpact(line_id: str, speed_pct: int, temp_celsius: Optional[float])`
  - `@dataclass(frozen=True) DisruptionOverrides(delay_hours: Optional[int] = None, shortfall_units: Optional[int] = None, line_speeds: Optional[Mapping[str, int]] = None, order_id: Optional[str] = None)`
  - `@dataclass(frozen=True) ResolvedDisruption(delay_hours: int, line_impacts: tuple[LineImpact, ...], supplier_id: Optional[str], order_id: str, shortfall_units: int, headline: str)` with a property `line_speeds -> dict[str, int]` and `to_dict()` (JSON-safe).
  - `resolve_reference(text: str, candidates: Mapping[str, str], kind: str) -> str` — `candidates` maps id → name.
  - `resolve_disruption(extraction: DisruptionExtraction, model: FactoryModel, order_ids: Sequence[str], overrides: DisruptionOverrides | None = None) -> ResolvedDisruption`

**Matching rule for `resolve_reference`** (`_norm(s)` = lowercase with non-alphanumerics removed):
1. `_norm(text)` equals one id's or one name's norm.
2. Otherwise `_norm(text)` is a substring of exactly one candidate's norm, either its id or its name.
3. Otherwise `difflib.get_close_matches(cutoff=0.85)` over all norms yields exactly one candidate.

If 2 or 3 yields several candidates, raise "Ambiguous {kind} '{text}': matches {ids}". If none match, raise "Unknown {kind} '{text}'. Known: {id (name), …}".

**Resolution rules:**
- Overrides win field by field.
- `delay_hours` defaults to 0 when unstated.
- `shortfall_units` must be stated: otherwise raise "shortfall_units not stated".
- Each line needs a speed: otherwise raise "speed for line {id} not stated".
- A line named twice → error.
- `overrides.line_speeds` replaces the extracted lines entirely. Its ids must be exact line ids and its speeds 0..100.
- Order: override → extracted reference → the factory's only order. If none of these applies, raise an error that lists the order ids.
- Supplier: the extracted reference if given. Otherwise, when `delay_hours > 0`, the factory's single `PRIMARY` vendor. If there is none or more than one, raise "name the delayed supplier". With no delay and no reference, it is `None`.
- `headline` is the extraction's headline when non-empty. Otherwise it is built from the resolved names, e.g. `"Chennai Precision Casings +48h; Robotic Welding Line 2 at 50%; 150 short on #EV-402"`.

- [ ] **Step 1: Write failing tests** (demo model via `load_factory_model()` in offline mode, plus `small_factory()`):
  - `"Line 2"` → `LINE-2`
  - `"Welding Line 2"` → `LINE-2`
  - `"Welding Line"` → raises Ambiguous, and the message names LINE-1/2/3
  - `"Line 9"` → raises Unknown, and the message contains `LINE-1`
  - `"Chennai Precision"` → `SUP-CHN-01`
  - `"ev-402"` → `EV-402`
  - overrides beat extraction
  - missing shortfall → raises
  - line without speed → raises
  - delay with no supplier → PRIMARY `SUP-CHN-01`
  - `small_factory` (no PRIMARY) with delay and no supplier → raises
  - `override line_speeds={"LINE-9": 50}` → raises
  - speed 101 → raises
  - two orders and no order named → raises, listing both ids
- [ ] **Step 2:** Run `python -m unittest tests.test_disruption -v` → fails with ImportError.
- [ ] **Step 3:** Implement the schemas and `app/disruption.py`.
- [ ] **Step 4:** The test passes. Some existing tests construct `DisruptionExtraction` with `line2_*` fields; leave them failing until Task 3 (note them in the report).
- [ ] **Step 5:** Commit `feat: disruption references resolved against the factory model`.

### Task 3: Model-aware extraction (Gemini prompt + regex fallback)

**Files:**
- Modify: `backend/app/agents/tools.py:35-122` (`extract_disruption_entities`)
- Test: `backend/tests/test_disruption.py`

**Interfaces:**
- Consumes: `DisruptionExtraction`, `LineImpactExtraction` (Task 2).
- Produces: `extract_disruption_entities(raw_text: str, model: FactoryModel, order_ids: Sequence[str]) -> tuple[DisruptionExtraction, str]`. The source is `"gemini:<model>"` or `"regex-fallback"`, as before.

**Gemini prompt:** names the factory and lists `LINE-ID — name`, `SUPPLIER-ID — name` and the order ids. It asks for each reference as one of those ids, and for fields to be left null when the text does not state them ("never invent numbers").

**Regex fallback:**
- **Delay:** keep the existing hours regex, but with `\b` after the unit.
- **Shortfall:** keep the existing regex, and also accept the stock item name's last word (e.g. "casings"). Do not assume the default.
- **Lines:** for each model line, build a mention pattern from its id with separators flexible: `re.escape` per alphanumeric chunk, joined by `[\s\-_]?`, with word boundaries. Also match its full name, case-insensitive. A line's speed is the first `(\d{1,3})\s*%` after its mention and before the next line mention, within 80 chars. Its temperature is the existing temperature regex in the same window.
- **Supplier:** match the id, or the longest prefix of at least 2 words of the name before `" ("`, appearing in the text.
- **Order:** match any order id, word-bounded and case-insensitive.

- [ ] **Step 1: Write failing tests** (regex path; `GEMINI_API_KEY` unset by `_offline_env`):
  - Scenario 1 text → `affected_lines == [("Robotic Welding Line 2" or "LINE-2" resolved → LINE-2, 50, 89.0)]`, supplier resolves to `SUP-CHN-01`, order `EV-402`, delay 48, shortfall 150.
  - `"Truck breakdown, 120 casings short on EV-402, Line 2 at 60%, 24h delay"` → (LINE-2, 60), 120, 24.
  - `"Line 1 at 70% and Line 3 at 40%, 90 units short on EV-405"` → two impacts with the right speeds.
  - The second factory: `"L-B at 40%, 80 units short on WO-77, 5h delay from Vendor V1"` → (L-B, 40), V1, WO-77.
  - `"flood on the highway"` → every field None/empty, so resolution raises "shortfall_units not stated".
- [ ] **Step 2:** Run → fails (wrong signature).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `tests.test_disruption` → passes.
- [ ] **Step 5:** Commit `feat: model-aware disruption extraction (any line, supplier, order)`.

### Task 4: Graph, blast radius and arbitrator use resolved disruptions

**Files:**
- Modify: `backend/app/agents/graph.py` — state at 134-163, `_ctx` 171-177, detective 182-251, arbitrator 429-471, `run_cascade_pipeline` 519-544
- Modify: `backend/app/agents/tools.py:127-178` (`query_blast_radius_sql`)
- Modify: `backend/tests/factories.py` — add `seed_second_factory()`
- Test: `backend/tests/test_disruption.py`, existing `tests/test_api.py`

**Interfaces:**
- Consumes: Task 2 `resolve_disruption`, `ResolvedDisruption`, `DisruptionOverrides`; Task 3 `extract_disruption_entities(raw, model, order_ids)`.
- Produces:
  - `run_cascade_pipeline(raw_message: str, source_channel: str = "WEB_DASHBOARD", override_delay_hours: Optional[int] = None, override_shortfall_units: Optional[int] = None, override_line_speeds: Optional[Dict[str, int]] = None, order_id: Optional[str] = None, factory_id: Optional[str] = None) -> Dict`
  - The final state contains `line_impacts: List[{"line_id","speed_pct","temp_celsius"}]`, `line_speeds: Dict[str,int]`, `affected_supplier_id: Optional[str]`, `order_id`, `delay_hours`, `shortfall_units` and `crisis_headline`. There are no `line2_*` keys.
  - `query_blast_radius_sql(model: FactoryModel, disruption: ResolvedDisruption) -> Dict` returns:
    - `order_id`, `client`, `shortfall_units`
    - `sla_penalty_inr`, `partial_delay_penalty_inr`, `hours_remaining` — all taken from the order row, with no fallbacks
    - `inbound_delay_hours`, `affected_supplier_id`, `line_impacts`
    - `blast_radius_severity`: `"COMPOUND"` when there is both a supplier delay and a line impact, otherwise `"SUPPLY"`, `"CAPACITY"` or `"LOW"`
  - Writes:
    - the supplier → `DELAYED` + `delay_hours`, when present
    - each impacted line → `status` `"THROTTLED"` if speed < 100, else `"NORMAL"`, plus `speed_pct` and `temp_celsius` when given
    - the order → `BREACH_RISK` + `shortfall_units`
  - `seed_second_factory() -> None` (tests): inserts into the offline mirror, through `db.insert_row`, the factories row `test-plant`, suppliers V1/V2/V3 with history rows, lines L-A/L-B and order `WO-77` (`hours_remaining` 30, penalty 400000, partial 80000), all with `factory_id="test-plant"`. Values match `small_factory()`.

The detective resolves *before* any write: unknown references raise `DisruptionResolutionError` with nothing written. The order list passed to resolution is the orders whose `factory_id == model.factory_id`. Remove `_ctx` / arbitrator fallbacks (`38`, `2_500_000`, `"EV-402"`, `"Ather-Grid Mobility Corp"`, `500_000`); the values come from `blast_radius`. Narration text uses line names and the supplier name from the model.

- [ ] **Step 1: Write failing tests:**
  - `test_pipeline_on_second_factory`: `seed_second_factory()`, then `run_cascade_pipeline("L-B at 40%, 80 units short on WO-77, 5h delay from Vendor V1", factory_id="test-plant")`. Assert:
    - `line_speeds == {"L-B": 40}`, `order_id == "WO-77"`, `affected_supplier_id == "V1"`
    - at least one playbook
    - the mirror line L-B has `speed_pct` 40 and status THROTTLED
    - WO-77 status is BREACH_RISK
  - `test_unknown_reference_writes_nothing`: snapshot suppliers/lines/orders, run `"Line 9 at 40%, 80 units short on EV-402"` → raises `DisruptionResolutionError`, and the snapshot is unchanged.
  - `test_multi_line_disruption`: `override_line_speeds={"LINE-1": 70, "LINE-3": 40}` → both lines are in `line_impacts`, and `throughput_gap_units` equals `model.throughput_gap({...})`.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `tests.test_disruption tests.test_solver` → passes. `test_api` may still fail on `line2_*` API fields until Task 5; list them.
- [ ] **Step 5:** Commit `feat: pipeline runs on resolved disruptions for any factory`.

### Task 5: API, scenarios table, sourcing and remaining backend literals

**Files:**
- Create: `supabase/migrations/005_generic_disruptions.sql`
- Modify: `supabase/schema.sql`, `backend/app/db.py` (seed scenarios, mirror table, `REQUIRED_MIGRATION_LEVEL = 5`, mirror `schema_migrations` 1–5, `get_scenarios`)
- Modify: `backend/app/schemas.py` (`SimulateCrisisRequest`, `PlcTelemetryRequest`)
- Modify: `backend/app/main.py`:
  - `SCENARIO_*` 104-125 → deleted
  - `_run_pipeline` 128-146
  - simulate-crisis 259-300
  - `_status_text` 325-335
  - the webhook hello text at ~514
  - PLC 542-550
  - `_execute` order at ~676
  - the new `GET /api/v1/scenarios`
- Modify: `backend/app/agents/sourcing.py:255-262` (RFQ wording), `:440-455` (run fields)
- Test: `backend/tests/test_api.py`, `tests/test_sourcing.py`, `tests/test_persistence.py` (migration level 5)

**Interfaces:**
- Produces:
  - **Migration 005** (re-run safe; the guard raises unless `schema_migrations` has version 4):
    - `scenarios(factory_id TEXT NOT NULL, scenario_id INT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '', raw_message TEXT NOT NULL, delay_hours INT NOT NULL, shortfall_units INT NOT NULL, line_speeds JSONB NOT NULL DEFAULT '{}', order_id TEXT NOT NULL, PRIMARY KEY (factory_id, scenario_id))` — RLS on with an anon read policy. It is seeded with today's three apex scenarios: text from `SCENARIO_PROMPTS`, numbers from `SCENARIO_DEFAULTS` as `{"LINE-2": speed}`, order `EV-402`, and titles "NH48 flood + Line 2 overheat", "Minor toll delay", "Supplier collapse".
    - Adds to `disruption_events` `factory_id TEXT`, `order_id TEXT`, `affected_supplier_id TEXT` and `line_impacts JSONB NOT NULL DEFAULT '[]'`.
    - Inserts version 5.
  - `db.get_scenarios(factory_id: str) -> list[dict]`, ordered by `scenario_id`.
  - `GET /api/v1/scenarios` (open, read-only) → `[{scenario_id, title, summary, raw_message, delay_hours, shortfall_units, line_speeds, order_id}]` for the default factory.
  - `SimulateCrisisRequest`:
    - `scenario_id: Optional[int] = Field(None, ge=1)` — unknown → 404
    - `raw_message`, `source_channel`, `override_delay_hours`, `override_shortfall_units` as now
    - `override_line_speeds: Optional[dict[str, int]]` — every value is 0..100 (validator); unknown ids → 422 via resolution
    - `order_id: Optional[str] = Field(None, max_length=32)`
    - `override_line2_speed_pct` is removed
  - simulate-crisis `extracted_parameters`: `{delay_hours, line_impacts: [{line_id, name, speed_pct, temp_celsius}], affected_supplier_id, shortfall_units, affected_order_id, source, overridden_by_preset_or_slider}`.
  - The `disruption_events` insert writes `factory_id`, `order_id`, `affected_supplier_id`, `line_impacts` (not `line2_speed_pct`).
  - `PlcTelemetryRequest.line_id: str` is required, with no default; an unknown line → 404.
  - `_status_text()` lists every line whose status is not `NORMAL` (name, status, speed, temp) and every order not `ON_TRACK` (id, client, status, penalty). Otherwise it says "All lines normal; all orders on track."
  - `_execute` uses `run["order_id"]` (KeyError impossible: the run always has it).
  - Sourcing:
    - `run["line_speeds"]` and `run["order_id"]` are required, with no `LINE-2`/`EV-402` fallbacks.
    - For flat-fee vendors the RFQ reads `"a dedicated delivery of {n} {item} for a flat fee"` instead of "an air charter".

- [ ] **Step 1: Write failing tests:**
  - `GET /api/v1/scenarios` returns 3 rows, and scenario 1 has `line_speeds == {"LINE-2": 50}`.
  - Simulating scenario 1 still recommends `PLAN_B`, and `extracted_parameters.line_impacts[0].line_id == "LINE-2"`.
  - `scenario_id: 9` → 404.
  - `override_line_speeds: {"LINE-1": 120}` → 422.
  - `override_line_speeds: {"LINE-9": 50}` → 422 naming `LINE-1`.
  - Custom text `"... Line 2 at 60%, 24h delay"` → `line_impacts[0].speed_pct == 60`.
  - A Meta webhook text `"flood on the highway"` → 200, and the sender's reply contains `"shortfall"`.
  - PLC without `line_id` → 422.
  - PLC `line_id: "LINE-9"` → 404.
  - `_status_text` after scenario 1 contains "Robotic Welding Line 2" and "EV-402", read from data.
  - Execute after a second-factory run (`run_store.save_run` of the Task 4 result) marks `WO-77` with the recovery status.
  - RFQ text for a flat-fee vendor contains "flat fee" and not "air charter".
  - `/healthz` `required_migration_level == 5`.
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Implement. Update every existing test that used `line2_*` / `override_line2_speed_pct`, keeping its intent.
- [ ] **Step 4:** The full suite passes. Then run `grep -rnE "line2_|EV-402|LINE-2" backend/app` → hits only in `db.py` seed lists.
- [ ] **Step 5:** Commit `feat: generic disruption API, data-driven scenarios (migration 005)`.

### Task 6: Frontend data layer and data-driven twin canvas

**Files:**
- Modify: `frontend/package.json` (devDependency `"vitest": "2.1.9"`, script `"test": "vitest run"`)
- Create: `frontend/src/lib/twinGraph.ts`, `frontend/src/lib/twinGraph.test.ts`
- Modify:
  - `frontend/src/store/useFactoryStore.ts` — types; hydrate fetches `/api/v1/factory` + `/api/v1/scenarios`; remove `INITIAL_NODES/EDGES` 215-280 and the hard-coded updater 588-705
  - `frontend/src/components/CustomNodes.tsx` — rewritten
  - `frontend/src/components/FlowCanvas.tsx`

**Interfaces:**
- Produces (`twinGraph.ts`):
  - Types `FactoryInfo {factory_id; name; vendors: {supplier_id; name; sourcing_role; max_units; unit_cost; flat_cost; lead_hours; reliability_pct}[]; lines: {line_id; name; rated_units_per_hour; ot_units_per_hour; ot_cost_per_hour; max_ot_hours}[]}` and `Scenario {scenario_id; title; summary; raw_message; delay_hours; shortfall_units; line_speeds: Record<string, number>; order_id}`.
  - `focusOrder(orders: OrderRow[], preferredOrderId?: string | null): OrderRow | null`. Order of preference:
    - the preferred id if present
    - otherwise the at-risk order (status not `ON_TRACK`) with the highest `sla_penalty_inr`
    - otherwise the order with the highest `sla_penalty_inr`
    - `null` when there are no orders
  - `buildTwinGraph(input: { factory: FactoryInfo; suppliers: SupplierRow[]; lines: ProductionLineRow[]; orders: OrderRow[]; playbook?: Playbook | null; focusOrderId?: string | null }): { nodes: Node[]; edges: Edge[] }`
    - **Node ids:** `supplier:<id>`, `line:<line_id>`, `order:<order_id>`.
    - **Node types:** `"supplier" | "line" | "order"`.
    - **Columns:** x = 0 / 400 / 800, y = index × 180.
    - **Which rows:** only the factory's vendors and lines. Orders are filtered to `factory_id === factory.factory_id` when the row has `factory_id`.
    - **Supplier node data:** `{supplierId, name, role, status, delayHours, inboundQty, allocatedUnits}`, where allocated units come from the playbook's `vendor_allocations`.
    - **Line node data:** `{lineId, name, status, speedPct, tempC, otHours}`, where OT hours come from the playbook's `overtime_line_hours`.
    - **Order node data:** `{orderId, client, status, shortfall, penaltyInr, isFocus}`.
    - **Edges:** every supplier → every line, and every line → every order. An edge is `animated` and red-styled when its source is `DELAYED` or `THROTTLED`.
- Produces (store): state `factory: FactoryInfo | null`, `factoryError: string | null`, `scenarios: Scenario[]`, `activeOrderId: string | null`; `nodes`/`edges` are recomputed via `buildTwinGraph` whenever state or the selected playbook changes.
  - `simulateCrisis(scenarioId)` stays.
  - `simulateCustom(input: {raw_message?: string; override_delay_hours?: number; override_shortfall_units?: number; override_line_speeds?: Record<string, number>; order_id?: string})` POSTs to simulate-crisis.
  - After a run, `activeOrderId = extracted_parameters.affected_order_id`.
- Produces (`CustomNodes.tsx`): `nodeTypes = { supplier: SupplierNode, line: LineNode, order: OrderNode }`, in the existing visual style (island cards, status colours: DELAYED/THROTTLED/BREACH_RISK red, recovery statuses green). FlowCanvas selects vendor history by `node.data.supplierId`. When `factoryError` is set, the canvas renders an error card with that message.

- [ ] **Step 1:** `npm install -D vitest@2.1.9`. Write failing tests in `twinGraph.test.ts`:
  - With the demo factory fixture (4 vendors, 3 lines, 2 orders): 9 nodes and 4×3 + 3×2 = 18 edges.
  - With a 2-vendor/2-line/1-order fixture: 5 nodes and 6 edges.
  - A `DELAYED` supplier's outgoing edges are animated.
  - A playbook allocating 60 to V1 → V1 node `allocatedUnits === 60`.
  - `focusOrder` prefers the given id; otherwise it picks the highest-penalty at-risk order; with an empty list it returns `null`.
  - Orders of another factory are excluded.
- [ ] **Step 2:** `npm test` → fails (module missing).
- [ ] **Step 3:** Implement `twinGraph.ts`, the store changes, `CustomNodes`, `FlowCanvas`.
- [ ] **Step 4:** `npm test` passes; `node_modules/.bin/tsc --noEmit -p .` exits 0.
- [ ] **Step 5:** Commit `feat: digital twin rendered from factory data`.

### Task 7: Frontend surfaces without demo literals

**Files:**
- Modify:
  - `frontend/src/components/CrisisSandboxModal.tsx`
  - `ExecutiveStoryView.tsx`
  - `TopKpiBar.tsx`
  - `ExecutionModal.tsx`
  - `frontend/src/app/mobile/page.tsx`

**Interfaces:**
- Consumes: Task 6 store fields (`factory`, `scenarios`, `activeOrderId`, `simulateCustom`) and `focusOrder`.

**Required behaviour:**
- **CrisisSandboxModal:**
  - The preset cards are the store's `scenarios` (title, summary; clicking runs `simulateCrisis(scenario_id)`).
  - The order `<select>` lists the factory's orders (`#id (client: qty / ₹penalty SLA)`).
  - There is one speed slider (0–100) per factory line, labelled with the line name. Only lines moved below 100 are sent, as `override_line_speeds`.
  - The free-text placeholder is built from the first line's name and the first order id.
  - The structured submit calls `simulateCustom`.
- **ExecutiveStoryView / TopKpiBar / mobile page:**
  - The order shown is `focusOrder(orders, activeOrderId)`.
  - The crisis sentence lists the throttled lines (`name at speed% (temp°C)`) from `production_lines` where `status !== "NORMAL"`.
  - The "all on schedule" text lists the actual orders.
  - The mobile scenario buttons come from `GET /api/v1/scenarios`.
- **ExecutionModal:** the shift notice heading names the lines with overtime in the receipt's playbook (`overtime_line_hours` > 0, mapped to line names); with none it says "No overtime scheduled".

- [ ] **Step 1:** Add vitest cases for any new pure helper you extract: `throttledLinesText(lines)` and `ordersSummary(orders)` in `frontend/src/lib/twinGraph.ts`, and their tests. Run → fail.
- [ ] **Step 2:** Implement the helpers and the components.
- [ ] **Step 3:** `npm test` passes; tsc exits 0. `grep -rnE "EV-402|LINE-2|line2|Line 2|Lines 1 & 3|SUP-(CHN|PNY|HSR|AIR)" frontend/src` → no hits outside `*.test.ts` fixtures.
- [ ] **Step 4:** Browser check (dev server via `preview_start` "frontend", with the backend running):
  - The canvas shows 4 suppliers, 3 lines and 2 orders.
  - Scenario 1 turns `Robotic Welding Line 2` and `EV-402` red and recommends PLAN_B.
  - The sandbox sliders show three lines.
  - Take a screenshot.
- [ ] **Step 5:** Commit `feat: dashboard, sandbox and mobile views driven by factory data`.

### Task 8: Docs and phase gate

**Files:** `README.md`, `docs/superpowers/plans/2026-11-18-cascadezero-roadmap.md`

- [ ] **Step 1:** README:
  - Document the disruption format (any line/supplier/order; what is required; the 422 behaviour), `GET /api/v1/scenarios`, migration 005 and `npm test`.
  - Update the "What Is Real vs Simulated" rows for extraction and twin.
- [ ] **Step 2:** Roadmap: mark "Carried forward → Phase 3" done (PuLP names, RFQ wording, literals, twin labels).
- [ ] **Step 3:** Gate:
  - full backend suite; `npm test`; tsc exit 0
  - `grep -rnE "line2_|EV-402" backend/app frontend/src` → only `backend/app/db.py` seed lists and `*.test.ts` fixtures
  - control-char scan `[]`
  - all three scenarios via the API give the same recommendation as before Phase 3 (record them)
- [ ] **Step 4 (controller):** Apply 005 to the live Supabase project (via the Supabase connection, as done for 001–004). Confirm `/healthz` reports `migration_level 5, ready: true`.
- [ ] **Step 5:** Commit `docs: generic disruptions, scenarios and data-driven twin`; independent whole-phase review; fix wave.
