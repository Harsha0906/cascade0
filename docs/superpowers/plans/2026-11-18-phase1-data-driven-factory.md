# Phase 1 — Data-Driven Factory Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The solver, agents and Sourcing Agent read vendors, production lines and factory settings from the database through one validated `FactoryModel`, so a different factory needs data, not code.

**Architecture:** New module `backend/app/factory_model.py` owns the domain dataclasses, the DB loader and validation. `solver.py` loses every plant constant and takes `model: FactoryModel` plus `line_speeds: Mapping[str, int]`. Overtime becomes per line with a shared elapsed-hours variable. Graph and Sourcing hold the model per run; two tool stubs whose results were discarded are deleted.

**Tech Stack:** Python 3.14, FastAPI, PuLP 4.2 (HiGHS), LangGraph, Pydantic v2, Supabase (Postgres) with in-memory mirror, Next.js 14 / TypeScript.

**Spec:** `docs/superpowers/plans/2026-11-18-cascadezero-roadmap.md` (Phase 1 section + Definition of Done).

## Global Constraints

- Tests: unittest (pytest not installed). Run from `backend/`: `PYTHONIOENCODING=utf-8 python -W ignore -m unittest discover -s tests -t .`
- Every test module imports `from tests import _offline_env` before any `app` import (keeps tests offline).
- Frontend gate: `cd frontend && node_modules/.bin/tsc --noEmit -p .` exits 0.
- Default factory id: `apex-volt-blr2` (env `FACTORY_ID` overrides).
- Supplier `sourcing_role` values: exactly `PRIMARY`, `BACKUP`, `EXPEDITE`. `PRIMARY` suppliers are never recovery options.
- Delay-shock probability for a vendor = `traffic_risk_pct + weather_risk_pct` (existing columns).
- Reliability comes from `vendor_history.reliability_score_pct`; a backup/expedite vendor with no history row is a `FactoryDataError`.
- `UNCOVERED_UNIT_PENALTY = 1_000_000` stays a solver constant (modelling device, not factory data).
- Seed values must reproduce today's demo vendors exactly (lead, sigma, ranges, reliability, cost, capacity).
- Commit after each task on branch `improve/solver-security-sourcing-agent` with the attribution line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Intended behaviour changes (everything else must stay the same)

| Scenario (shortfall, delay, speed) | Before | After | Why |
|---|---|---|---|
| S1 (150, 48, 50) | PLAN_B ₹1,80,000 | PLAN_B ₹1,80,000 | unchanged |
| S2 (25, 6, 85) | PLAN_C ₹45,000 (2h × both lines) | PLAN_C ₹33,750 (2h + 1h) | overtime now chosen per line |
| S3 (350, 72, 25) | PLAN_B ₹3,82,500 | PLAN_B ₹3,82,500 | unchanged |
| Over capacity (1000, 72, 25) | PLAN_C, capacity exhausted | same | unchanged |

Seed overtime changes from "38 units/h for ₹22,500/h on Lines 1 & 3 combined" to "19 units/h for ₹11,250/h **per line**" (identical totals; the old DB rows listed 38/22,500 per line, which contradicted the solver).

## Review Focus

1. **Factory rows missing a required column** (Supabase reachable, migration 003 not applied) → `FactoryDataError` whose message names the column and `003_factory_model.sql`; the API returns 503 with that message. Test in Task 2, API test in Task 5.
2. **Factory without an `EXPEDITE` vendor** → Plan A is omitted, the Ops node logs "no expedite option", the pipeline still recommends a plan. Tests in Task 3 (solver) and Task 4 (graph).
3. **Factory without overtime lines** → a throughput gap is reported as uncovered (`feasible=False`), never a crash or division by zero. Test in Task 3.
4. **Invalid numbers in data** (negative capacity, reliability > 100, lead ≤ 0, `delay_min > delay_max`) → `FactoryDataError` listing every bad field at once. Test in Task 2.
5. **Vendor override for an unknown supplier id** → `FactoryDataError`, not a silently ignored override. Test in Task 1.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `backend/app/factory_model.py` | `Vendor`, `ProductionLine`, `FactoryModel`, `FactoryDataError`, `load_factory_model()` |
| Create `supabase/migrations/003_factory_model.sql` | `factories` table, new supplier/line/order columns, seed updates, RLS read policy |
| Modify `supabase/schema.sql` | Same columns and seed for fresh installs |
| Modify `backend/app/db.py` | Seed rows (new fields, `_SEED_FACTORIES`), mirror `factories` table, reset reseeds it, `get_full_state` factory name from data |
| Modify `backend/app/config.py` | `DEFAULT_FACTORY_ID`; remove `FACTORY_NAME` constant |
| Modify `backend/app/solver.py` | Remove plant constants; all public functions take `model` + `line_speeds` |
| Modify `backend/app/schemas.py` | `throughput_gap_units` (rename), `overtime_line_hours` on `PlaybookOption` |
| Modify `backend/app/agents/graph.py` | Model in state; Ops optional; vendor lookups via model; stubs removed |
| Modify `backend/app/agents/tools.py` | Delete `check_air_charter_and_max_overtime`, `query_regional_vendors_and_memory`; pass model to solver |
| Modify `backend/app/agents/sourcing.py` | Model-based vendor lookup; expedite-charter logic by role and `flat_cost` |
| Modify `backend/app/main.py` | 503 on `FactoryDataError`; overtime line status from playbook; `GET /api/v1/factory` |
| Modify `frontend/src/store/useFactoryStore.ts` | Read `throughput_gap_units` |
| Create `backend/tests/test_factory_model.py` | Tasks 1–2 tests |
| Modify `backend/tests/test_solver.py`, `test_api.py`, `test_sourcing.py` | Use the model; new Review Focus tests |
| Modify `README.md` | "What Is Real vs Simulated": vendor row now "from database" |

---

### Task 1: Domain model (pure, no database)

**Files:**
- Create: `backend/app/factory_model.py`, `backend/tests/factories.py`
- Test: `backend/tests/test_factory_model.py`

**Interfaces:**
- Produces:
  - `tests/factories.py: small_factory() -> FactoryModel` — the second, non-demo factory used by every later task's tests (defined below)
  - `class FactoryDataError(ValueError)`
  - `@dataclass(frozen=True) class Vendor` — fields exactly as today's `solver.Vendor` plus `sourcing_role: str` (last field): `supplier_id, name, tier, route, max_units, unit_cost, flat_cost, lead_hours, lead_sigma, delay_shock_pct, delay_shock_range: tuple[float,float], reliability_pct, unreliability_delay_range: tuple[float,float], min_lead_hours, sourcing_role`
  - `@dataclass(frozen=True) class ProductionLine(line_id: str, name: str, rated_units_per_hour: float, ot_units_per_hour: int, ot_cost_per_hour: int, max_ot_hours: int)`
  - `@dataclass(frozen=True) class FactoryModel(factory_id: str, name: str, stock_item_name: str, qa_dispatch_hours: float, safety_stock_units: int, production_hours_in_window: float, vendors: tuple[Vendor, ...], lines: tuple[ProductionLine, ...])` with:
    - `vendor(supplier_id: str) -> Vendor` (raises `FactoryDataError` if unknown)
    - `expedite_vendor_id -> Optional[str]` (property; first vendor with role `EXPEDITE`, else `None`)
    - `overtime_lines -> tuple[ProductionLine, ...]` (property; lines with `ot_units_per_hour > 0 and max_ot_hours > 0`)
    - `throughput_gap(line_speeds: Mapping[str, int]) -> int` = ceil(Σ rated_uph × (1 − clamp(speed,0,100)/100) × production_hours_in_window) over listed lines; unknown line id raises `FactoryDataError`
    - `with_vendor_overrides(overrides: Mapping[str, Mapping[str, Any]] | None) -> FactoryModel` — same semantics as today's `solver.effective_vendors` (keys `max_units, unit_cost, flat_cost, lead_hours`; `max_units <= 0` drops the vendor); unknown supplier id raises `FactoryDataError`

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_factory_model.py`, plus `small_factory()` in `backend/tests/factories.py`: factory `test-plant`, production window 10h, QA 2h, safety stock 30; vendors `V1` BACKUP 100u ₹500/u lead 4h reliability 90, `V2` BACKUP 200u ₹900/u lead 6h reliability 85, `V3` EXPEDITE 300u flat ₹2,00,000 lead 3h reliability 99 (all with sigma 0.5, shock 5%, ranges (1,2)/(1,2), min lead 1); lines `L-A` (rated 10/h, no overtime) and `L-B` (rated 10/h, overtime 20 u/h ₹5,000/h max 6h):

```python
def test_throughput_gap_sums_listed_lines(self):
    self.assertEqual(small_factory().throughput_gap({"L-A": 50}), 50)          # 10*0.5*10
    self.assertEqual(small_factory().throughput_gap({"L-A": 50, "L-B": 80}), 70)
    self.assertEqual(small_factory().throughput_gap({"L-A": 100}), 0)

def test_unknown_line_rejected(self):
    with self.assertRaises(FactoryDataError):
        small_factory().throughput_gap({"L-Z": 50})

def test_overtime_lines_and_expedite(self):
    m = small_factory()
    self.assertEqual([l.line_id for l in m.overtime_lines], ["L-B"])
    self.assertEqual(m.expedite_vendor_id, "V3")

def test_overrides_replace_and_drop(self):
    m = small_factory().with_vendor_overrides({"V1": {"max_units": 40, "unit_cost": 520}, "V3": {"max_units": 0}})
    self.assertEqual((m.vendor("V1").max_units, m.vendor("V1").unit_cost), (40, 520))
    self.assertIsNone(m.expedite_vendor_id)

def test_override_for_unknown_vendor_rejected(self):          # Review Focus 5
    with self.assertRaises(FactoryDataError):
        small_factory().with_vendor_overrides({"NOPE": {"max_units": 5}})
```

- [ ] **Step 2: Run to verify failure** — `python -m unittest tests.test_factory_model -v` → `ModuleNotFoundError: app.factory_model`.
- [ ] **Step 3: Implement** `backend/app/factory_model.py` with the interfaces above (dataclasses use `dataclasses.replace`; `FactoryModel` is frozen, so overrides return a new model).
- [ ] **Step 4: Run to verify pass** — same command → OK (5 tests).
- [ ] **Step 5: Commit** — `git add backend/app/factory_model.py backend/tests/test_factory_model.py && git commit -m "feat: add FactoryModel domain types"`

---

### Task 2: Database schema, seed data and validated loader

**Files:**
- Create: `supabase/migrations/003_factory_model.sql`
- Modify: `supabase/schema.sql`, `backend/app/db.py`, `backend/app/config.py`, `backend/app/factory_model.py`
- Test: `backend/tests/test_factory_model.py`

**Interfaces:**
- Consumes: Task 1 types.
- Produces: `load_factory_model(factory_id: str | None = None) -> FactoryModel` (default `settings.DEFAULT_FACTORY_ID`); `settings.DEFAULT_FACTORY_ID: str`; db mirror table `factories`; `db.get_factory_row(factory_id) -> dict | None`.

Schema additions (migration uses `ADD COLUMN IF NOT EXISTS`, then `UPDATE` seed rows; `schema.sql` gets the same columns and seed values):
- `factories(id TEXT PK, name TEXT NOT NULL, stock_item_name TEXT NOT NULL, qa_dispatch_hours FLOAT NOT NULL, safety_stock_units INT NOT NULL, production_hours_in_window FLOAT NOT NULL)` + RLS `SELECT` policy for `anon, authenticated` + realtime publication.
- `suppliers`: `factory_id TEXT`, `sourcing_role TEXT`, `lead_time_sigma_hours FLOAT`, `delay_shock_min_hours FLOAT`, `delay_shock_max_hours FLOAT`, `unreliable_delay_min_hours FLOAT`, `unreliable_delay_max_hours FLOAT`, `min_lead_hours FLOAT`.
- `production_lines`: `factory_id TEXT`, `rated_units_per_hour FLOAT`.
- `orders`: `factory_id TEXT` (unused until Phase 7; added now so tenancy needs no second data migration).

Seed values (`factory_id = 'apex-volt-blr2'` everywhere):

| Row | role | sigma | shock min/max | unreliable min/max | min lead |
|---|---|---|---|---|---|
| SUP-CHN-01 | PRIMARY | 1.0 | 1.0 / 3.0 | 2.0 / 4.0 | 8.0 |
| SUP-PNY-02 | BACKUP | 0.45 | 1.0 / 2.5 | 1.5 / 3.0 | 2.0 |
| SUP-HSR-03 | BACKUP | 1.1 | 2.0 / 4.0 | 2.5 / 5.0 | 4.0 |
| SUP-AIR-04 | EXPEDITE | 0.25 | 1.0 / 2.0 | 1.0 / 2.0 | 4.5 |

Lines: LINE-1 rated 19, OT 19 u/h ₹11,250/h max 8 · LINE-2 rated 19, no OT (0/0/0) · LINE-3 rated 14, OT 19 u/h ₹11,250/h max 8.
Factory: `apex-volt-blr2`, "Apex Volt EV Battery Plant (Bengaluru Unit-2)", "Aluminium Battery Casing", QA 2.5, safety stock 50, production window 16.

- [ ] **Step 1: Write the failing tests** (append to `test_factory_model.py`):

```python
def test_demo_factory_loads_and_matches_previous_constants(self):
    m = load_factory_model()                       # offline → in-memory mirror seed
    p = m.vendor("SUP-PNY-02")
    self.assertEqual((p.max_units, p.unit_cost, p.lead_hours, p.lead_sigma, p.delay_shock_pct,
                      p.delay_shock_range, p.reliability_pct, p.min_lead_hours),
                     (200, 600, 4.0, 0.45, 6.0, (1.0, 2.5), 93.3, 2.0))
    self.assertEqual(m.vendor("SUP-AIR-04").flat_cost, 600_000)
    self.assertEqual(m.expedite_vendor_id, "SUP-AIR-04")
    self.assertNotIn("SUP-CHN-01", [v.supplier_id for v in m.vendors])   # PRIMARY excluded
    self.assertEqual(m.throughput_gap({"LINE-2": 50}), 152)
    self.assertEqual(sorted(l.line_id for l in m.overtime_lines), ["LINE-1", "LINE-3"])

def test_missing_column_names_migration(self):                 # Review Focus 1
    with mock.patch("app.factory_model.get_all_suppliers",
                    return_value=[{**_SEED_SUPPLIERS[1], "lead_time_sigma_hours": None}]):
        with self.assertRaisesRegex(FactoryDataError, "lead_time_sigma_hours.*003_factory_model"):
            load_factory_model()

def test_invalid_values_all_reported(self):                    # Review Focus 4
    bad = {**_SEED_SUPPLIERS[1], "max_available_qty": -5, "delay_shock_min_hours": 3.0, "delay_shock_max_hours": 1.0}
    with mock.patch("app.factory_model.get_all_suppliers", return_value=[bad]):
        with self.assertRaises(FactoryDataError) as ctx:
            load_factory_model()
    self.assertIn("max_available_qty", str(ctx.exception))
    self.assertIn("delay_shock", str(ctx.exception))

def test_unknown_factory_id(self):
    with self.assertRaisesRegex(FactoryDataError, "no-such-plant"):
        load_factory_model("no-such-plant")
```

- [ ] **Step 2: Run to verify failure** — `python -m unittest tests.test_factory_model -v` → `ImportError: cannot import name 'load_factory_model'`.
- [ ] **Step 3: Implement**
  - `config.py`: `DEFAULT_FACTORY_ID: str = os.getenv("FACTORY_ID", "apex-volt-blr2")`; delete `FACTORY_NAME`.
  - `db.py`: add the new fields to `_SEED_SUPPLIERS` / `_SEED_PRODUCTION_LINES` / `_SEED_ORDERS`, add `_SEED_FACTORIES`, `InMemoryMirror.factories`, `get_factory_row(factory_id)`, reset upserts factories; `get_full_state()["factory_name"]` reads the default factory row (fall back to the id if missing).
  - `factory_model.py`: `load_factory_model` reads the factory row, suppliers, vendor_history and lines for that `factory_id` (import `get_all_suppliers`, `get_all_production_lines`, `fetch_all`, `get_factory_row` from `app.db` at module level so tests can patch them); collects **all** problems into one `FactoryDataError` message; a `None`/missing required column produces `"<table>.<column> missing — apply supabase/migrations/003_factory_model.sql"`.
  - Migration + `schema.sql` per the tables above.
- [ ] **Step 4: Run to verify pass** — `python -m unittest tests.test_factory_model -v` → OK (9 tests); full suite still green.
- [ ] **Step 5: Commit** — `git commit -m "feat: load validated factory model from database"` (include migration, schema, db, config, tests).

---

### Task 3: Solver takes the factory model (per-line overtime)

**Files:**
- Modify: `backend/app/solver.py`, `backend/app/schemas.py`
- Test: `backend/tests/test_solver.py` (rewrite fixtures to use `load_factory_model()` and `tests.factories.small_factory()`)

**Interfaces:**
- Consumes: `FactoryModel`, `FactoryDataError` (Task 1), `load_factory_model` (Task 2).
- Produces (all in `app.solver`; old names `PEENYA, HOSUR, AIR, VENDORS, effective_vendors, line2_throughput_gap, OVERTIME_*, SAFETY_STOCK_UNITS, QA_DISPATCH_HOURS, LINE2_*` are deleted):
  - `solve_pulp_milp(model: FactoryModel, shortfall_units: int, line_speeds: Mapping[str, int], deadline_hours: float, force_vendor_id: str | None = None, allowed_vendor_ids: list[str] | None = None, min_vendor_reliability_pct: float = 0.0) -> dict` — returns today's keys plus `"overtime_line_hours": dict[str, int]` and `"throughput_gap_units"` (replaces `line2_throughput_gap_units`); `"overtime_hours"` = elapsed overtime window `H`. If `force_vendor_id` is not in the (filtered) model, return the infeasible dict with status `"Infeasible: forced vendor unavailable"`.
  - `simulate_monte_carlo(model: FactoryModel, strategy_type, units_by_vendor, overtime_hours, deadline_hours, fully_covered=True, delay_hours=0, iterations=1000, seed=42) -> dict` (uses `model.qa_dispatch_hours`)
  - `generate_playbooks(model: FactoryModel, shortfall_units: int, delay_hours: int, line_speeds: Mapping[str, int], order_id: str, sla_penalty_inr: int, partial_penalty_inr: int, deadline_hours: float, client: str, cfo_min_vendor_reliability_pct: float = 0.0, vendor_overrides=None, confirmed_vendor_ids=None) -> SolverResult` — Plan A only when the (overridden) model has an expedite vendor; Plan C OT-only uses `solve_pulp_milp(..., shortfall_units=0, allowed_vendor_ids=[])` and is feasible only if `shortfall <= model.safety_stock_units`.
  - `build_shift_broadcast_msg(model, overtime_line_hours: dict[str,int], units_target, order_id, client) -> str` (lists line names from the model)
  - `build_tally_xml(po_number, playbook, model) -> str` (company = `model.name`, stock item = `model.stock_item_name`)
  - `schemas.PlaybookOption.overtime_line_hours: dict[str, int] = {}`; `schemas.SolverResult.throughput_gap_units: int = 0` (field `line2_throughput_gap_units` removed).

MILP change (the part the signature does not determine):

```
variables: h_l ∈ Z ∩ [0, max_ot_hours_l] for each overtime line;  H ≥ h_l  (continuous, elapsed window)
objective += Σ ot_cost_l · h_l  +  1 · H  +  0.01 · Σ x_v
                # ₹1/h tie-break: prefer balanced lines; ₹0.01/unit: never allocate more units
                # than needed from a zero-unit-cost (flat-fee) vendor. Reported costs exclude both.
capacity:  Σ ot_units_l · h_l + u_cap ≥ model.throughput_gap(line_speeds)
deadline:  lead_v · y_v + H + qa ≤ deadline  for each vendor;   H + qa ≤ deadline
```

- [ ] **Step 1: Write the failing tests** (replace constant imports in `test_solver.py`; keep every existing test's intent):

```python
DEMO = load_factory_model()
S = lambda speed: {"LINE-2": speed}

def test_demo_scenarios_regression(self):
    r1 = generate_playbooks(DEMO, 150, 48, S(50), **ORDER)
    r2 = generate_playbooks(DEMO, 25, 6, S(85), **ORDER)
    r3 = generate_playbooks(DEMO, 350, 72, S(25), **ORDER)
    win = lambda r: next(p for p in r.playbooks if p.recommended)
    self.assertEqual((r1.recommended_plan_id, win(r1).total_mitigation_cost_inr), ("PLAN_B", 180_000))
    self.assertEqual((r2.recommended_plan_id, win(r2).total_mitigation_cost_inr), ("PLAN_C", 33_750))
    self.assertEqual((r3.recommended_plan_id, win(r3).total_mitigation_cost_inr), ("PLAN_B", 382_500))
    self.assertEqual(win(r1).overtime_line_hours, {"LINE-1": 4, "LINE-3": 4})

def test_second_factory_defined_only_by_data(self):
    r = generate_playbooks(small_factory(), 120, 10, {"L-A": 40}, order_id="X", sla_penalty_inr=500_000,
                           partial_penalty_inr=100_000, deadline_hours=24, client="C")
    b = next(p for p in r.playbooks if p.id == "PLAN_B")
    self.assertEqual({a.supplier_id: a.units_allocated for a in b.vendor_allocations}, {"V1": 100, "V2": 20})
    self.assertEqual(b.total_mitigation_cost_inr, 50_000 + 18_000 + 15_000)   # V1 + V2 + 3h overtime
    self.assertEqual(b.overtime_line_hours, {"L-B": 3})          # gap 10×0.6×10 = 60 → 3h × 20 u/h

def test_flat_fee_vendor_is_not_over_allocated(self):
    r = generate_playbooks(small_factory(), 120, 10, {"L-A": 100}, **SMALL_ORDER)
    a = next(p for p in r.playbooks if p.id == "PLAN_A")
    self.assertEqual(sum(x.units_allocated for x in a.vendor_allocations), 120)

def test_factory_without_expedite_vendor_has_no_plan_a(self):    # Review Focus 2
    m = small_factory().with_vendor_overrides({"V3": {"max_units": 0}})
    r = generate_playbooks(m, 50, 10, {"L-A": 100}, **SMALL_ORDER)
    self.assertNotIn("PLAN_A", [p.id for p in r.playbooks])
    self.assertEqual(sum(p.recommended for p in r.playbooks), 1)

def test_factory_without_overtime_lines_reports_gap_uncovered(self):   # Review Focus 3
    m = replace(small_factory(), lines=(ProductionLine("L-A", "A", 10, 0, 0, 0),))
    lp = solve_pulp_milp(m, 0, {"L-A": 50}, 24)
    self.assertFalse(lp["feasible"])
    self.assertEqual(lp["uncovered_capacity_units"], 50)
```

(`ORDER` / `SMALL_ORDER` are kwargs dicts defined at module top: order id, penalties, deadline 38 / 24, client.) Keep the existing infeasibility, tight-deadline, reliability-floor, Monte-Carlo, ranking and Tally tests, rewritten to pass `DEMO` and `S(...)`.

- [ ] **Step 2: Run to verify failure** — `python -m unittest tests.test_solver -v` → `TypeError`/`ImportError` on the new signatures.
- [ ] **Step 3: Implement** the interfaces above in `solver.py` and `schemas.py`. Remove the module-level plant constants and the `__main__` demo block's direct constant use (it should call `load_factory_model()`).
- [ ] **Step 4: Run to verify pass** — `python -m unittest tests.test_solver -v` → all OK. (`test_api` / `test_sourcing` are expected to fail until Task 4.)
- [ ] **Step 5: Commit** — `git commit -m "refactor: solver consumes FactoryModel with per-line overtime"`

---

### Task 4: Agents use the model (graph, tools, Sourcing Agent)

**Files:**
- Modify: `backend/app/agents/graph.py`, `backend/app/agents/tools.py`, `backend/app/agents/sourcing.py`
- Test: `backend/tests/test_sourcing.py`, `backend/tests/test_api.py`, new cases in `backend/tests/test_factory_model.py`

**Interfaces:**
- Consumes: Task 3 solver signatures; `load_factory_model`.
- Produces:
  - Graph state keys added: `factory_id: str`, `factory_model: FactoryModel`, `line_speeds: dict[str, int]` (built as `{"LINE-2": line2_speed}` until Phase 3 generalises extraction). `run_cascade_pipeline(..., factory_id: str | None = None)`.
  - `ops_proposal` may be `None` when `model.expedite_vendor_id is None`; `_needs_rebuttal(cfo, ops)` treats `ops is None` as "no confidence-gap trigger".
  - `tools.run_pulp_milp_and_monte_carlo(model, shortfall_units, delay_hours, line_speeds, **solver_kwargs) -> dict`; `check_air_charter_and_max_overtime` and `query_regional_vendors_and_memory` are deleted (their results were never used).
  - `SourcingSession.params["factory_id"]`; the session's `_solve` loads the model once at session start and stores it on the session (`session.model`); the charter rule is "vendor whose `flat_cost > 0` and `unit_cost == 0`" (quoted price = charter total), not a hard-coded id.

- [ ] **Step 1: Write the failing test** (append to `test_factory_model.py`; uses the offline mirror and patches the loader):

```python
def test_pipeline_runs_for_factory_without_expedite_vendor(self):   # Review Focus 2
    demo = load_factory_model()
    no_air = demo.with_vendor_overrides({"SUP-AIR-04": {"max_units": 0}})
    with mock.patch("app.agents.graph.load_factory_model", return_value=no_air):
        r = run_cascade_pipeline("x", override_shortfall_units=150, override_delay_hours=48,
                                 override_line2_speed_pct=50)
    self.assertIsNone(r["ops_proposal"])
    self.assertNotIn("PLAN_A", [p["id"] for p in r["playbooks"]])
    self.assertIn(r["recommended_plan_id"], {"PLAN_B", "PLAN_C", "PLAN_D"})
```

- [ ] **Step 2: Run to verify failure** — `python -m unittest discover -s tests -t .` → this test plus the `test_api`/`test_sourcing` suites fail on the old solver calls.
- [ ] **Step 3: Implement** the interfaces above. Every `_VENDOR_BY_ID[...]` lookup becomes `model.vendor(...)`; every `AIR`/`VENDORS` import is removed; RFQ text uses `model.stock_item_name` and `model.name`.
- [ ] **Step 4: Run to verify pass** — full suite OK (all previous sourcing/API tests unchanged in intent, plus the new test).
- [ ] **Step 5: Commit** — `git commit -m "refactor: agents and Sourcing Agent read the factory model"`

---

### Task 5: API surface, frontend field rename, docs

**Files:**
- Modify: `backend/app/main.py`, `frontend/src/store/useFactoryStore.ts`, `README.md`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `GET /api/v1/factory` → `{"factory_id", "name", "vendors": [{supplier_id, name, sourcing_role, max_units, unit_cost, flat_cost, lead_hours, reliability_pct}], "lines": [{line_id, name, rated_units_per_hour, ot_units_per_hour, ot_cost_per_hour, max_ot_hours}]}`; `simulate-crisis` returns **503** `{"detail": "Factory data invalid: …"}` on `FactoryDataError`; execution sets `OVERTIME_SCHEDULED` only on lines in the playbook's `overtime_line_hours` with hours > 0.

- [ ] **Step 1: Write the failing tests** (in `test_api.py`):

```python
def test_factory_endpoint_lists_data(self):
    d = self.client.get("/api/v1/factory").json()
    self.assertEqual(d["factory_id"], "apex-volt-blr2")
    self.assertIn("SUP-PNY-02", [v["supplier_id"] for v in d["vendors"]])

def test_invalid_factory_data_is_503_with_reason(self):            # Review Focus 1
    with mock.patch("app.agents.graph.load_factory_model",
                    side_effect=FactoryDataError("suppliers.lead_time_sigma_hours missing — apply supabase/migrations/003_factory_model.sql")):
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY)
    self.assertEqual(r.status_code, 503)
    self.assertIn("003_factory_model", r.json()["detail"])

def test_execution_marks_only_scheduled_overtime_lines(self):
    sim = self._simulate(2)                      # PLAN_C: LINE-1 2h, LINE-3 1h
    self.client.post("/api/v1/execute-plan", json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}, headers=KEY)
    lines = {l["line_id"]: l["status"] for l in self.client.get("/api/v1/state").json()["production_lines"]}
    self.assertEqual((lines["LINE-1"], lines["LINE-3"]), ("OVERTIME_SCHEDULED", "OVERTIME_SCHEDULED"))
    self.assertNotEqual(lines["LINE-2"], "OVERTIME_SCHEDULED")
```

- [ ] **Step 2: Run to verify failure** — `python -m unittest tests.test_api -v` → 404 on `/api/v1/factory`, 500 instead of 503.
- [ ] **Step 3: Implement** the endpoint, the 503 mapping, the execution change; rename `line2_throughput_gap_units` → `throughput_gap_units` in `useFactoryStore.ts`; README table row "Vendor costs, capacities, lead times" → "Loaded per factory from the database (`suppliers`, `vendor_history`, `production_lines`, `factories`)".
- [ ] **Step 4: Run to verify pass** — backend suite OK; `cd frontend && node_modules/.bin/tsc --noEmit -p .` exits 0.
- [ ] **Step 5: Commit** — `git commit -m "feat: factory endpoint, 503 on invalid factory data, per-line overtime status"`

---

### Task 6: Phase gate (Definition of Done)

- [ ] **Step 1:** Full backend suite → OK; tsc → exit 0.
- [ ] **Step 2:** `grep -rnE "PEENYA|HOSUR|\bAIR\b|VENDORS|OVERTIME_COST|SAFETY_STOCK_UNITS|LINE2_RATED|FACTORY_NAME" backend/app` → no matches.
- [ ] **Step 3:** Run backend offline + dashboard; run scenarios 1–3 and one Sourcing round (Peenya partial → Hosur confirm); results match the "Intended behaviour changes" table.
- [ ] **Step 4:** Staged-diff secret scan clean; `git status` shows no `.env` files.
- [ ] **Step 5:** Independent review of the phase diff against this plan and the roadmap's Phase 1 "Done when"; fix findings as new commits.
- [ ] **Step 6:** Apply `003_factory_model.sql` to Supabase (user action) and confirm `GET /api/v1/factory` returns the live rows.
