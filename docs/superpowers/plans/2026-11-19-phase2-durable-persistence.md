# Phase 2 — Durable Persistence, Fail-Loud Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analysis runs, Sourcing sessions, execution receipts and webhook deliveries are stored in the database; a live-database failure returns 503 instead of silently using in-memory data; plan execution is one atomic, idempotent transaction.

**Architecture:** `app/db.py` gains an explicit storage mode (`supabase` | `offline`) and raises `DatabaseError` on any live failure (the in-memory mirror is used only in offline mode). Migration `004_durable_state.sql` adds four JSON-payload tables, a `schema_migrations` table and a Postgres function `execute_plan_tx`. `run_store` and the Sourcing Agent become thin repositories over those tables with no process-local state. FastAPI maps `DatabaseError` → 503 and exposes `/healthz`.

**Tech Stack:** Python 3.14, FastAPI, supabase-py (PostgREST + `rpc`), Postgres/PL-pgSQL, unittest.

**Spec:** `docs/superpowers/plans/2026-11-18-cascadezero-roadmap.md` (Phase 2 section, Principles, Definition of Done, "Carried forward from Phase 1 → Phase 2").

## Global Constraints

- Tests: unittest only; run from `backend/`: `PYTHONIOENCODING=utf-8 python -W ignore -m unittest discover -s tests -t .` (89 passing at start). Every test module imports `from tests import _offline_env` first; tests never touch a live database.
- Frontend gate unchanged: `cd frontend && node_modules/.bin/tsc --noEmit -p .` exits 0.
- Storage mode: `settings.storage_mode` = `"supabase"` when `SUPABASE_URL` and a server key are set, else `"offline"`. Production (`CASCADE_ENV=production`) refuses to start in offline mode.
- In `supabase` mode no code path may read or write the in-memory mirror. Every live failure raises `DatabaseError`; the API answers **503** `{"detail": "Database unavailable: <operation> <table>"}` (never the raw driver message, which may contain URLs).
- Required migration level: **4** (`db.REQUIRED_MIGRATION_LEVEL = 4`). Migration files 001–003 already exist; 004 records levels 1–4 in `schema_migrations`.
- New tables store a full JSON `payload` column plus the columns needed for lookup/uniqueness only.
- Every persisted payload must survive `json.loads(json.dumps(payload))` unchanged.
- Commit after each task on branch `phase2/durable-persistence`, message ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- The SQL in migration 004 cannot be executed in this environment; it is reviewed by reading and applied by the user (Task 7).

## Review Focus

1. **Supabase configured but unreachable or erroring** → every endpoint that touches data returns 503 "Database unavailable"; no response ever contains seed/mirror data. Tests in Task 1.
2. **Migration 004 not applied while Supabase is configured** → `/healthz` reports `ready: false` with the current level; execution fails with 503 (missing function), not a 500 or a partial write. Tests in Task 6 (health) and Task 5 (missing-function error mapping).
3. **Two approvals of the same analysis at the same moment** (double click, two workers, WhatsApp + dashboard) → exactly one purchase order and one receipt; the other request gets the same receipt (`already_executed: true`) or 409. Test in Task 5.
4. **Backend restarts in the middle of a Sourcing round** → the pending enquiries, offers and round survive; the next vendor reply completes the round. Test in Task 4.
5. **Meta delivers the same webhook message twice** → processed once (one pipeline run / one recorded vendor reply). Test in Task 6.

---

## File Structure

| File | Responsibility |
|---|---|
| Modify `backend/app/db.py` | Storage mode, `DatabaseError`, `AlreadyExecutedError`, fail-loud helpers, new mirror tables, `call_function`, `migration_level`, `execute_plan_tx`, `get_receipt`, `record_webhook_event` |
| Modify `backend/app/config.py` | `storage_mode` property; production refuses offline mode |
| Create `supabase/migrations/004_durable_state.sql` | Tables, `schema_migrations`, `execute_plan_tx` function, RLS |
| Modify `supabase/schema.sql` | Comment pointing fresh installs to 001–004 in order (no duplication of 004) |
| Modify `backend/app/factory_model.py` | `FactoryModel.to_dict()` / `FactoryModel.from_dict()` |
| Rewrite `backend/app/run_store.py` | Repository over `analysis_runs` (no module-level state) |
| Create `backend/app/agents/sourcing_store.py` | Repository over `sourcing_sessions` with optimistic versioning |
| Modify `backend/app/agents/sourcing.py` | Use `sourcing_store`; session (de)serialisation; retry on version conflict |
| Modify `backend/app/main.py` | 503 handler, transactional `_execute`, webhook de-duplication, `/healthz`, startup migration check |
| Create `backend/tests/fake_supabase.py` | Minimal fake client: configurable failure, records calls |
| Create `backend/tests/test_persistence.py` | Tasks 1–6 tests |
| Modify `README.md` | Storage modes, migration 004, `/healthz` |

---

### Task 1: Fail-loud database layer

**Files:** Modify `backend/app/db.py`, `backend/app/config.py`, `backend/app/main.py`; Create `backend/tests/fake_supabase.py`, `backend/tests/test_persistence.py`

**Interfaces:**
- Produces:
  - `settings.storage_mode -> Literal["supabase", "offline"]`; `settings.security_problems()` adds "offline storage in production" when production and offline.
  - `class db.DatabaseError(RuntimeError)` with attributes `operation: str`, `table: str`; `str()` = `"<operation> <table> failed"` (driver message kept only in the log).
  - `db._get_supabase()`: returns `None` only in offline mode; in supabase mode a client-creation failure raises `DatabaseError("connect", "supabase")`.
  - Every helper (`fetch_all`, `fetch_by_id`, `upsert_row`, `insert_row`, `update_rows`, `delete_all`, `get_vendor_history`, `get_agent_logs`, `reset_to_seed`) in supabase mode raises `DatabaseError` on any exception and never touches `_mirror`.
  - `tests/fake_supabase.py`: `FailingClient()` — any `.table(...)...execute()` or `.rpc(...).execute()` raises `RuntimeError("boom https://secret.example")`.
  - `main.py`: `@app.exception_handler(db.DatabaseError)` → 503 `{"detail": "Database unavailable: <operation> <table>"}`; the Meta/Twilio webhooks catch `DatabaseError` like `FactoryDataError` (generic reply, detail only in the log).

- [ ] **Step 1: Write failing tests** in `test_persistence.py` (patch `app.db._get_supabase` to return `FailingClient()`):

```python
def test_live_read_failure_raises_not_mirror(self):
    with mock.patch("app.db._get_supabase", return_value=FailingClient()):
        with self.assertRaises(db.DatabaseError):
            db.fetch_all("suppliers")

def test_live_write_failure_raises(self):
    with mock.patch("app.db._get_supabase", return_value=FailingClient()):
        with self.assertRaises(db.DatabaseError):
            db.update_rows("orders", "order_id", "EV-402", {"status": "X"})
    self.assertNotEqual(db.get_order("EV-402")["status"], "X")    # mirror untouched

def test_api_returns_503_without_leaking_driver_text(self):         # Review Focus 1
    with mock.patch("app.db._get_supabase", return_value=FailingClient()):
        r = self.client.get("/api/v1/state")
    self.assertEqual(r.status_code, 503)
    self.assertTrue(r.json()["detail"].startswith("Database unavailable"))
    self.assertNotIn("secret.example", r.text)

def test_configured_but_unconnectable_raises(self):
    with mock.patch.object(db.settings, "SUPABASE_URL", "https://x"), \
         mock.patch.object(db.settings, "SUPABASE_SERVICE_ROLE_KEY", "k"), \
         mock.patch("supabase.create_client", side_effect=RuntimeError("down")), \
         mock.patch.object(db, "_supabase_client", None):
        with self.assertRaises(db.DatabaseError):
            db._get_supabase()

def test_offline_mode_still_works(self):
    self.assertEqual(db.settings.storage_mode, "offline")
    self.assertTrue(db.fetch_all("suppliers"))
```

- [ ] **Step 2: Run** `python -m unittest tests.test_persistence -v` → failures (no `DatabaseError`, mirror fallback).
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** the focused tests → OK; full suite → all pass.
- [ ] **Step 5: Commit** `feat: fail-loud database layer with explicit storage mode`

---

### Task 2: Migration 004 and storage for durable state

**Files:** Create `supabase/migrations/004_durable_state.sql`; Modify `supabase/schema.sql`, `backend/app/db.py`; Test `backend/tests/test_persistence.py`

**Interfaces:**
- Produces:
  - Tables (all `ENABLE ROW LEVEL SECURITY`, **no** anon/authenticated policies — service role only):
    - `analysis_runs(run_id TEXT PK, parent_run_id TEXT, factory_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), payload JSONB NOT NULL)` + index on `created_at DESC`
    - `sourcing_sessions(run_id TEXT PK, status TEXT NOT NULL, version INT NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), payload JSONB NOT NULL)`
    - `execution_receipts(root_run_id TEXT PK, run_id TEXT NOT NULL, playbook_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), payload JSONB NOT NULL)`
    - `webhook_events(message_id TEXT PK, received_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`
    - `schema_migrations(version INT PK, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`; `INSERT … VALUES (1),(2),(3),(4) ON CONFLICT DO NOTHING`
  - `execute_plan_tx(p_po JSONB, p_order_id TEXT, p_order_status TEXT, p_supplier_updates JSONB, p_overtime_line_ids TEXT[], p_agent_log JSONB, p_root_run_id TEXT, p_receipt JSONB) RETURNS JSONB` (PL/pgSQL, one implicit transaction): insert `p_receipt` into `execution_receipts` **first** (a duplicate `root_run_id` raises `unique_violation` before any other write), then insert `p_po` into `purchase_orders` (`jsonb_populate_record`), update `orders`, update each supplier in `p_supplier_updates` (`[{supplier_id, inbound_qty}]` → status `PO_DRAFTED`), set `OVERTIME_SCHEDULED` on `p_overtime_line_ids`, insert `p_agent_log` into `agent_logs`; returns `p_receipt`. `GRANT EXECUTE` to `service_role` only.
  - Whole file re-run safe (`IF NOT EXISTS`, `CREATE OR REPLACE FUNCTION`, `ON CONFLICT DO NOTHING`); header says "Apply after 003. Safe to re-run."
  - `db.REQUIRED_MIGRATION_LEVEL = 4`; `db.migration_level() -> int` (max version in `schema_migrations`; a missing table in supabase mode → 0, any other failure → `DatabaseError`); offline mirror seeds versions 1–4.
  - `db.call_function(name: str, params: dict) -> Any` — supabase `rpc(...).execute().data`; offline → `DatabaseError("rpc", name)` (offline equivalents are implemented in Python by the callers' db functions, Task 5).
  - Mirror tables `analysis_runs`, `sourcing_sessions`, `execution_receipts`, `webhook_events`, `schema_migrations`; `reset_to_seed()` clears the first four in both modes (supabase: delete all rows; failure → `DatabaseError`).
  - `schema.sql` header: "Fresh install: run this file, then migrations 001, 002, 003, 004 in order."

- [ ] **Step 1: Write failing tests:**

```python
def test_offline_migration_level_is_required_level(self):
    self.assertEqual(db.migration_level(), db.REQUIRED_MIGRATION_LEVEL)

def test_reset_clears_durable_tables(self):
    db.insert_row("analysis_runs", {"run_id": "R1", "factory_id": "f", "payload": {}})
    db.reset_to_seed()
    self.assertEqual(db.fetch_all("analysis_runs"), [])

def test_call_function_offline_is_an_error(self):
    with self.assertRaises(db.DatabaseError):
        db.call_function("execute_plan_tx", {})
```

- [ ] **Step 2: Run** → fail. **Step 3: Implement** SQL + db changes. **Step 4: Run** focused + full suite → pass.
- [ ] **Step 5: Commit** `feat: migration 004 durable-state tables and execute_plan_tx`

---

### Task 3: Durable analysis runs

**Files:** Modify `backend/app/factory_model.py`; Rewrite `backend/app/run_store.py`; Test `backend/tests/test_persistence.py`, `backend/tests/test_factory_model.py`

**Interfaces:**
- Consumes: `db.upsert_row`, `db.fetch_by_id`, `db.fetch_all` (Task 1).
- Produces:
  - `FactoryModel.to_dict() -> dict` (JSON-safe; tuples become lists) and `@classmethod FactoryModel.from_dict(d) -> FactoryModel` with `FactoryModel.from_dict(m.to_dict()) == m`.
  - `run_store.save_run(result: dict) -> None` — stores `{"run_id", "parent_run_id", "factory_id", "payload"}` in `analysis_runs`; payload = result with `factory_model` replaced by its `to_dict()`; raises `ValueError` if the payload is not JSON-serialisable.
  - `run_store.get_run(run_id: str) -> dict | None` — payload with `factory_model` rehydrated via `from_dict`.
  - `run_store.latest_run_id() -> str | None` — newest `created_at` (supabase: `order("created_at", desc=True).limit(1)`; offline: last inserted).
  - Receipt/claim functions (`get_receipt`, `claim_execution`, `store_receipt`, `release_claim`, `clear`) stay **unchanged** in this task; Task 5 removes them.
  - No module-level dict of runs remains.

- [ ] **Step 1: Write failing tests:**

```python
def test_factory_model_roundtrip(self):
    m = load_factory_model()
    self.assertEqual(FactoryModel.from_dict(json.loads(json.dumps(m.to_dict()))), m)

def test_run_survives_module_reload(self):                       # no process-local state
    sim = self._simulate(1)
    importlib.reload(run_store)
    run = run_store.get_run(sim["run_id"])
    self.assertIsInstance(run["factory_model"], FactoryModel)
    self.assertEqual(run["recommended_plan_id"], sim["recommended_plan_id"])
    self.assertEqual(run_store.latest_run_id(), sim["run_id"])

def test_unknown_run_is_none(self):
    self.assertIsNone(run_store.get_run("RUN-NOPE"))
```

- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** focused + full suite → pass (sourcing's `_finish` and main's `/runs/latest` keep working through the same API).
- [ ] **Step 5: Commit** `feat: persist analysis runs in the database`

---

### Task 4: Durable Sourcing sessions with optimistic concurrency

**Files:** Create `backend/app/agents/sourcing_store.py`; Modify `backend/app/agents/sourcing.py`; Test `backend/tests/test_persistence.py`, `backend/tests/test_sourcing.py`

**Interfaces:**
- Consumes: Task 3 `FactoryModel.to_dict/from_dict`; db helpers.
- Produces:
  - `SourcingSession.to_dict() -> dict` / `SourcingSession.from_dict(d) -> SourcingSession` (RFQs as dicts, `confirmed` as sorted list, model via `FactoryModel`), plus field `version: int = 0`.
  - `sourcing_store.class ConcurrentUpdateError(RuntimeError)`
  - `sourcing_store.load(run_id) -> SourcingSession | None`
  - `sourcing_store.save(session) -> None` — insert when `session.version == 0`, else update **only if** stored version equals `session.version` (supabase: `.update(...).eq("run_id", id).eq("version", v)` and zero returned rows ⇒ conflict; offline: compare under a module lock); on success sets `session.version += 1`; on conflict raises `ConcurrentUpdateError`.
  - `sourcing_store.active() -> list[SourcingSession]` (status `ACTIVE`, newest first).
  - `sourcing.py`: module dict `_sessions` removed; `start_sourcing`, `record_reply`, `view`, `find_open_rfq_by_number` load/save through `sourcing_store`; `record_reply` retries the whole load→apply→save up to 3 times on `ConcurrentUpdateError`, then raises `SourcingError("Sourcing session changed concurrently; retry", 409)`; `clear()` removed (reset clears the table).

- [ ] **Step 1: Write failing tests:**

```python
def test_sourcing_survives_restart_mid_round(self):                # Review Focus 4
    sim = self._simulate(1)
    self._start(sim["run_id"])
    importlib.reload(sourcing_store)                                # drop any process state
    s = self._reply(sim["run_id"], "SUP-PNY-02", "YES 150 pcs @600 in 4h")
    self.assertEqual(s["status"], "COMPLETE")

def test_stale_save_is_rejected(self):
    sim = self._simulate(1); self._start(sim["run_id"])
    a = sourcing_store.load(sim["run_id"]); b = sourcing_store.load(sim["run_id"])
    sourcing_store.save(a)
    with self.assertRaises(sourcing_store.ConcurrentUpdateError):
        sourcing_store.save(b)

def test_reply_retries_after_conflict(self):
    sim = self._simulate(1); self._start(sim["run_id"])
    real_save = sourcing_store.save
    calls = {"n": 0}
    def flaky(session):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sourcing_store.ConcurrentUpdateError()
        return real_save(session)
    with mock.patch.object(sourcing_store, "save", side_effect=flaky):
        s = self._reply(sim["run_id"], "SUP-PNY-02", "YES 150 pcs @600 in 4h")
    self.assertEqual(s["status"], "COMPLETE")
```

- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** focused + full suite (all existing sourcing tests unchanged in intent) → pass.
- [ ] **Step 5: Commit** `feat: persist Sourcing sessions with optimistic concurrency`

---

### Task 5: Atomic, idempotent plan execution

**Files:** Modify `backend/app/db.py`, `backend/app/main.py`, `backend/app/run_store.py`; Test `backend/tests/test_persistence.py`, `backend/tests/test_api.py`

**Interfaces:**
- Consumes: migration 004 function signature (Task 2); `db.call_function`.
- Produces:
  - `class db.AlreadyExecutedError(RuntimeError)` with `root_run_id: str`.
  - `db.execute_plan_tx(po: dict, order_id: str, order_status: str, supplier_updates: list[dict], overtime_line_ids: list[str], agent_log: dict, root_run_id: str, receipt: dict) -> dict` — supabase: `call_function("execute_plan_tx", {...})`; a Postgres unique violation (`code == "23505"` on the API error) → `AlreadyExecutedError`; a missing function (`PGRST202` / "Could not find the function") → `DatabaseError("rpc", "execute_plan_tx")` with a log hint to apply migration 004. Offline: one module-level lock; deep-copy the affected mirror tables, apply the same writes in the same order (receipt first; duplicate → `AlreadyExecutedError`), restore the copies on any exception and re-raise.
  - `db.get_receipt(root_run_id: str) -> dict | None` (payload from `execution_receipts`).
  - `main._execute`: no claim/release; builds the receipt and rows, calls `db.execute_plan_tx` once; on `AlreadyExecutedError` loads the stored receipt → same run+playbook ⇒ return it with `already_executed=True`, else 409 (same detail text as today).
  - `/runs/latest` "executed" uses `db.get_receipt`.
  - `run_store`: `get_receipt`, `claim_execution`, `store_receipt`, `release_claim`, `clear` deleted (and their imports/calls).

- [ ] **Step 1: Write failing tests:**

```python
def test_execution_is_atomic(self):
    sim = self._simulate(1)
    real_update = db.update_rows
    def fail_on_suppliers(table, *a, **k):
        if table == "suppliers":
            raise RuntimeError("mid-transaction failure")
        return real_update(table, *a, **k)
    with mock.patch("app.db.update_rows", side_effect=fail_on_suppliers):
        with self.assertRaises(Exception):
            self.client.post("/api/v1/execute-plan", json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}, headers=KEY)
    self.assertEqual(db.fetch_all("purchase_orders"), [])
    self.assertIsNone(db.get_receipt(sim["run_id"]))
    self.assertNotEqual(db.get_order("EV-402")["status"], "RECOVERY_IN_PROGRESS")

def test_concurrent_approvals_create_one_po(self):                 # Review Focus 3
    sim = self._simulate(1)
    body = {"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda _: self.client.post("/api/v1/execute-plan", json=body, headers=KEY), range(4)))
    self.assertTrue(all(r.status_code == 200 for r in results))
    self.assertEqual(len(db.fetch_all("purchase_orders")), 1)
    self.assertEqual(sum(not r.json()["already_executed"] for r in results), 1)

def test_missing_rpc_function_is_503(self):                         # Review Focus 2
    with mock.patch("app.db.execute_plan_tx", side_effect=db.DatabaseError("rpc", "execute_plan_tx")):
        sim = self._simulate(1)
        r = self.client.post("/api/v1/execute-plan", json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}, headers=KEY)
    self.assertEqual(r.status_code, 503)
```

(The offline transaction must apply its writes through the module's own `insert_row` / `upsert_row` / `update_rows` helpers — called by their module-global names — so the atomicity test's patch of `app.db.update_rows` exercises the rollback. Also add two unit tests with a fake client whose `rpc(...).execute()` raises an error carrying `code`: `"23505"` → `AlreadyExecutedError`; `"PGRST202"` → `DatabaseError("rpc", "execute_plan_tx")`.)

- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** focused + full suite (existing idempotency/409 tests unchanged in intent) → pass.
- [ ] **Step 5: Commit** `feat: atomic idempotent plan execution via execute_plan_tx`

---

### Task 6: Webhook de-duplication, health endpoint, startup migration check

**Files:** Modify `backend/app/db.py`, `backend/app/main.py`, `backend/app/config.py`; Test `backend/tests/test_persistence.py`

**Interfaces:**
- Produces:
  - `db.record_webhook_event(message_id: str) -> bool` — True on first sight; False on duplicate (supabase: insert, `23505` ⇒ False; offline: set membership under lock); other failures → `DatabaseError`.
  - Meta webhook: when `messages[0]["id"]` is present and `record_webhook_event` returns False → return `{"status": "duplicate"}` before any processing.
  - `GET /healthz` (open): body `{"storage": settings.storage_mode, "db": "ok" | "error", "migration_level": int, "required_migration_level": 4, "ready": bool}`; status 200 when ready, else 503. `ready` = db ok and level ≥ required.
  - FastAPI startup event: in supabase mode logs an error when `migration_level() < 4`; in production raises `RuntimeError` (refuse to start). Offline in production is already refused by `security_problems()` (Task 1).

- [ ] **Step 1: Write failing tests:**

```python
def test_duplicate_webhook_processed_once(self):                    # Review Focus 5
    body = _meta_text("919800000001", "Truck stuck, 150 casings short, line 2 at 50%", msg_id="wamid.X1")
    with mock.patch.object(main, "_run_pipeline", wraps=main._run_pipeline) as spy:
        for _ in range(2):
            r = self._post_signed(body)
    self.assertEqual(spy.call_count, 1)
    self.assertEqual(r.json()["status"], "duplicate")

def test_healthz_offline_ready(self):
    r = self.client.get("/healthz")
    self.assertEqual((r.status_code, r.json()["storage"], r.json()["ready"]), (200, "offline", True))

def test_healthz_reports_old_migration_level(self):                 # Review Focus 2
    with mock.patch("app.db.migration_level", return_value=3):
        r = self.client.get("/healthz")
    self.assertEqual(r.status_code, 503)
    self.assertEqual(r.json()["migration_level"], 3)

def test_healthz_db_error(self):
    with mock.patch("app.db.migration_level", side_effect=db.DatabaseError("select", "schema_migrations")):
        r = self.client.get("/healthz")
    self.assertEqual((r.status_code, r.json()["db"]), (503, "error"))
```

(`_meta_text` / `_post_signed` are small helpers in the test module building a signed Meta text-message payload, mirroring `test_api.py`'s `_signed`.)

- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** focused + full suite → pass.
- [ ] **Step 5: Commit** `feat: webhook de-duplication, /healthz and startup migration check`

---

### Task 7: Docs and phase gate

- [ ] **Step 1:** README: "Storage modes" (supabase vs offline, 503 behaviour), Database section adds `004_durable_state.sql`, `/healthz` usage; "What Is Real vs Simulated" row for runs/sessions ("stored in Postgres; in offline mode in process memory").
- [ ] **Step 2:** Roadmap "Carried forward → Phase 2" items marked done (mirror fallback, migration level check).
- [ ] **Step 3:** Full backend suite OK; `tsc --noEmit` exit 0; `grep -n "_mirror" backend/app/db.py` shows mirror access only inside offline branches (reviewed).
- [ ] **Step 4:** Offline API run: scenario 1 → sourcing round → execute → second execute returns `already_executed`; `/healthz` 200.
- [ ] **Step 5:** Independent whole-phase review; fix wave.
- [ ] **Step 6 (user):** apply `003_factory_model.sql` (if not yet) and `004_durable_state.sql` in Supabase, set `SUPABASE_SERVICE_ROLE_KEY`, restart backend, confirm `GET /healthz` → `ready: true`.
