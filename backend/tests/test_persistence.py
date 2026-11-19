"""Fail-loud database layer: live-DB failures raise, never fall back to the mirror."""

import importlib
import json
import unittest
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from fastapi.testclient import TestClient

from app import db, main, run_store
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
