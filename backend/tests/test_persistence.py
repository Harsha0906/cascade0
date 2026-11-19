"""Fail-loud database layer: live-DB failures raise, never fall back to the mirror."""

import unittest
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from fastapi.testclient import TestClient

from app import db, main
from tests.fake_supabase import FailingClient

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


if __name__ == "__main__":
    unittest.main()
