"""Fail-loud database layer: live-DB failures raise, never fall back to the mirror."""

import importlib
import json
import unittest
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from fastapi.testclient import TestClient

from app import db, main, run_store
from app.agents import sourcing_store
from app.factory_model import FactoryModel
from tests.fake_supabase import FailingClient, MissingTableError, StubClient

KEY = {"X-API-Key": "test-operator-key"}


class FailLoudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.client.post("/api/v1/reset", headers=KEY)

    def test_live_read_failure_raises_not_mirror(self):
        with mock.patch("app.db._get_supabase", return_value=FailingClient()):
            with self.assertRaises(db.DatabaseError):
                db.fetch_all("suppliers")

    def test_live_write_failure_raises(self):
        with mock.patch("app.db._get_supabase", return_value=FailingClient()):
            with self.assertRaises(db.DatabaseError):
                db.update_rows("orders", "order_id", "EV-402", {"status": "X"})
        self.assertNotEqual(db.get_order("EV-402")["status"], "X")  # mirror untouched

    def test_every_helper_raises_in_live_mode(self):
        calls = [
            lambda: db.fetch_by_id("orders", "order_id", "EV-402"),
            lambda: db.upsert_row("orders", {"order_id": "EV-402", "status": "X"}),
            lambda: db.insert_row("agent_logs", {"run_id": "r"}),
            lambda: db.delete_all("agent_logs"),
            lambda: db.get_vendor_history("SUP-CHN-01"),
            lambda: db.get_agent_logs("r"),
            lambda: db.reset_to_seed(),
        ]
        with mock.patch("app.db._get_supabase", return_value=FailingClient()):
            for call in calls:
                with self.assertRaises(db.DatabaseError):
                    call()

    def test_database_error_message_hides_driver_text(self):
        with mock.patch("app.db._get_supabase", return_value=FailingClient()):
            with self.assertRaises(db.DatabaseError) as cm:
                db.fetch_all("suppliers")
        self.assertEqual(str(cm.exception), "fetch_all suppliers failed")
        self.assertEqual((cm.exception.operation, cm.exception.table), ("fetch_all", "suppliers"))

    def test_api_returns_503_without_leaking_driver_text(self):
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

    def test_production_refuses_offline_storage(self):
        with mock.patch.object(db.settings, "CASCADE_ENV", "production"):
            self.assertTrue(any("offline storage" in p for p in db.settings.security_problems()))


class RunPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.client.post("/api/v1/reset", headers=KEY)

    def _simulate(self, scenario=1):
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": scenario}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_run_survives_module_reload(self):  # no process-local state
        sim = self._simulate(1)
        importlib.reload(run_store)
        run = run_store.get_run(sim["run_id"])
        self.assertIsInstance(run["factory_model"], FactoryModel)
        self.assertEqual(run["recommended_plan_id"], sim["recommended_plan_id"])
        self.assertEqual(run_store.latest_run_id(), sim["run_id"])

    def test_unknown_run_is_none(self):
        self.assertIsNone(run_store.get_run("RUN-NOPE"))

    def test_persisted_payload_is_json_stable(self):
        sim = self._simulate(1)
        payload = db.fetch_by_id("analysis_runs", "run_id", sim["run_id"])["payload"]
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_non_serialisable_payload_rejected(self):
        with self.assertRaises(ValueError):
            run_store.save_run({"run_id": "RUN-BAD", "blob": object()})
        self.assertIsNone(run_store.get_run("RUN-BAD"))

    def test_latest_is_most_recently_saved(self):
        sim = self._simulate(1)
        child = run_store.get_run(sim["run_id"])
        child.update(run_id="RUN-CHILD", parent_run_id=sim["run_id"])
        run_store.save_run(child)
        self.assertEqual(run_store.latest_run_id(), "RUN-CHILD")


class SourcingPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.client.post("/api/v1/reset", headers=KEY)

    def _simulate(self, scenario=1):
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": scenario}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _start(self, run_id):
        r = self.client.post("/api/v1/sourcing/start", json={"run_id": run_id}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _reply(self, run_id, supplier_id, text):
        r = self.client.post(f"/api/v1/sourcing/{run_id}/vendor-reply",
                             json={"supplier_id": supplier_id, "text": text}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_sourcing_survives_restart_mid_round(self):  # Review Focus 4
        sim = self._simulate(1)
        self._start(sim["run_id"])
        importlib.reload(sourcing_store)  # drop any process state
        s = self._reply(sim["run_id"], "SUP-PNY-02", "YES 150 pcs @600 in 4h")
        self.assertEqual(s["status"], "COMPLETE")

    def test_stale_save_is_rejected(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        a = sourcing_store.load(sim["run_id"])
        b = sourcing_store.load(sim["run_id"])
        sourcing_store.save(a)
        with self.assertRaises(sourcing_store.ConcurrentUpdateError):
            sourcing_store.save(b)

    def test_reply_retries_after_conflict(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
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

    def test_persistent_conflict_is_409(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        with mock.patch.object(sourcing_store, "save", side_effect=sourcing_store.ConcurrentUpdateError()):
            r = self.client.post(f"/api/v1/sourcing/{sim['run_id']}/vendor-reply",
                                 json={"supplier_id": "SUP-PNY-02", "text": "YES"}, headers=KEY)
        self.assertEqual(r.status_code, 409)

    def test_insert_race_loser_gets_concurrent_update_error(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        s = sourcing_store.load(sim["run_id"])
        s.version = 0   # pretend a fresh session racing the winner's insert
        row = db.fetch_by_id("sourcing_sessions", "run_id", sim["run_id"])
        with mock.patch.object(db, "fetch_by_id", side_effect=[None, row]),                 mock.patch.object(db, "insert_row", side_effect=db.DatabaseError("insert", "sourcing_sessions")):
            with self.assertRaises(sourcing_store.ConcurrentUpdateError):
                sourcing_store.save(s)

    def test_insert_failure_without_row_reraises(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        s = sourcing_store.load(sim["run_id"])
        s.version = 0
        with mock.patch.object(db, "fetch_by_id", return_value=None),                 mock.patch.object(db, "insert_row", side_effect=db.DatabaseError("insert", "sourcing_sessions")):
            with self.assertRaises(db.DatabaseError):
                sourcing_store.save(s)

    def test_session_round_trips_and_active_lists_it(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        s = sourcing_store.load(sim["run_id"])
        self.assertEqual(s.version, 1)
        self.assertEqual(type(s).from_dict(s.to_dict()).to_dict(), s.to_dict())
        self.assertEqual([x.run_id for x in sourcing_store.active()], [sim["run_id"]])
        self.assertIsNone(sourcing_store.load("RUN-NOPE"))


if __name__ == "__main__":
    unittest.main()


class DurableStateTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()

    def test_offline_migration_level_is_required_level(self):
        self.assertEqual(db.migration_level(), db.REQUIRED_MIGRATION_LEVEL)

    def test_reset_clears_durable_tables(self):
        db.insert_row("analysis_runs", {"run_id": "R1", "factory_id": "f", "payload": {}})
        db.reset_to_seed()
        self.assertEqual(db.fetch_all("analysis_runs"), [])

    def test_call_function_offline_is_an_error(self):
        with self.assertRaises(db.DatabaseError):
            db.call_function("execute_plan_tx", {})

    def test_migration_level_live_max_version(self):
        stub = StubClient(data=[{"version": 4}])
        with mock.patch("app.db._get_supabase", return_value=stub):
            self.assertEqual(db.migration_level(), 4)

    def test_migration_level_missing_table_is_zero(self):
        with mock.patch("app.db._get_supabase", return_value=StubClient(error=MissingTableError())):
            self.assertEqual(db.migration_level(), 0)

    def test_migration_level_other_error_raises(self):
        with mock.patch("app.db._get_supabase", return_value=FailingClient()):
            with self.assertRaises(db.DatabaseError):
                db.migration_level()

    def test_call_function_live_returns_data(self):
        stub = StubClient(data={"ok": True})
        with mock.patch("app.db._get_supabase", return_value=stub):
            self.assertEqual(db.call_function("execute_plan_tx", {}), {"ok": True})

    def test_call_function_live_failure_raises(self):
        with mock.patch("app.db._get_supabase", return_value=FailingClient()):
            with self.assertRaises(db.DatabaseError):
                db.call_function("execute_plan_tx", {})

    def test_reset_live_clears_durable_tables(self):
        deleted = []

        class Rec(StubClient):
            def table(self, name, *a, **k):
                deleted.append(name)
                return super().table(name)

        with mock.patch("app.db._get_supabase", return_value=Rec(data=[])):
            db.reset_to_seed()
        for t in ("analysis_runs", "sourcing_sessions", "execution_receipts", "webhook_events"):
            self.assertIn(t, deleted)


class _CodedError(Exception):
    def __init__(self, code, msg="x"):
        super().__init__(msg)
        self.code = code


class ExecutePlanTxTests(unittest.TestCase):
    ARGS = dict(po={"po_number": "PO-1"}, order_id="EV-402", order_status="RECOVERY_IN_PROGRESS",
                supplier_updates=[], overtime_line_ids=[], agent_log={}, root_run_id="R1",
                receipt={"run_id": "R1", "playbook_id": "A"})

    def test_unique_violation_is_already_executed(self):
        stub = StubClient(error=_CodedError("23505", 'violates unique constraint "execution_receipts_pkey"'))
        with mock.patch("app.db._get_supabase", return_value=stub):
            with self.assertRaises(db.AlreadyExecutedError) as cm:
                db.execute_plan_tx(**self.ARGS)
        self.assertEqual(cm.exception.root_run_id, "R1")

    def test_missing_function_is_database_error(self):
        stub = StubClient(error=_CodedError("PGRST202", "Could not find the function public.execute_plan_tx"))
        with mock.patch("app.db._get_supabase", return_value=stub):
            with self.assertRaises(db.DatabaseError) as cm:
                db.execute_plan_tx(**self.ARGS)
        self.assertEqual((cm.exception.operation, cm.exception.table), ("rpc", "execute_plan_tx"))

    def test_other_error_is_database_error(self):
        with mock.patch("app.db._get_supabase", return_value=FailingClient()):
            with self.assertRaises(db.DatabaseError):
                db.execute_plan_tx(**self.ARGS)

    def test_offline_duplicate_root_run_id(self):
        db.reset_to_seed()
        db.execute_plan_tx(**self.ARGS)
        with self.assertRaises(db.AlreadyExecutedError):
            db.execute_plan_tx(**self.ARGS)
        self.assertEqual(db.get_receipt("R1"), self.ARGS["receipt"])
        self.assertEqual(len(db.fetch_all("purchase_orders")), 1)


class _RecordingClient:
    def __init__(self, data=None, error=None):
        self.calls, self._data, self._error = [], data, error

    def rpc(self, name, params):
        self.calls.append((name, params))
        outer = self

        class _Q:
            def execute(self):
                if outer._error is not None:
                    raise outer._error
                return type("R", (), {"data": outer._data})()
        return _Q()


class ExecutePlanTxClassificationTests(unittest.TestCase):
    ARGS = ExecutePlanTxTests.ARGS

    def _run(self, error):
        with mock.patch("app.db._get_supabase", return_value=StubClient(error=error)):
            return db.execute_plan_tx(**self.ARGS)

    def test_receipts_pkey_violation_is_already_executed(self):
        err = _CodedError("23505", 'duplicate key value violates unique constraint "execution_receipts_pkey"')
        with self.assertRaises(db.AlreadyExecutedError):
            self._run(err)

    def test_other_unique_violation_is_database_error(self):
        err = _CodedError("23505", 'duplicate key value violates unique constraint "purchase_orders_pkey"')
        with self.assertRaises(db.DatabaseError):
            self._run(err)

    def test_code_lookalike_in_message_is_database_error(self):
        err = Exception('error 123505 on execution_receipts_pkey')
        with self.assertRaises(db.DatabaseError):
            self._run(err)

    def test_rpc_name_and_params(self):
        client = _RecordingClient(data={"ok": 1})
        args = dict(self.ARGS, overtime_line_ids=["L1"], supplier_updates=[{"supplier_id": "S", "inbound_qty": 3}],
                    agent_log={"run_id": "R1"})
        with mock.patch("app.db._get_supabase", return_value=client):
            db.execute_plan_tx(**args)
        (name, params), = client.calls
        self.assertEqual(name, "execute_plan_tx")
        self.assertEqual(set(params), {"p_po", "p_order_id", "p_order_status", "p_supplier_updates",
                                       "p_overtime_line_ids", "p_agent_log", "p_root_run_id", "p_receipt"})
        self.assertIsInstance(params["p_po"], dict)
        self.assertIsInstance(params["p_supplier_updates"], list)
        self.assertIsInstance(params["p_overtime_line_ids"], list)
        self.assertIsInstance(params["p_agent_log"], dict)
        self.assertEqual(params["p_receipt"]["run_id"], "R1")
        self.assertEqual(params["p_receipt"]["playbook_id"], "A")
