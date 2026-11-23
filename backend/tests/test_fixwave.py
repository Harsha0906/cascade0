"""Final-review fix wave: webhook release-on-failure, offline execute rollback, reset filters, etc."""

import json
import pathlib
import unittest
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_HEADERS, dev_client  # noqa: F401

from app import db, main, run_store
from tests.fake_supabase import FailingClient
from tests.test_persistence import ExecutePlanTxTests, _meta_text

KEY = DEV_HEADERS  # dev-owner@example.test (AUTH_MODE=dev)


def _meta_button(sender, button_id, msg_id):
    return {"object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {"messages": [{
                "from": sender, "type": "interactive", "id": msg_id,
                "interactive": {"button_reply": {"id": button_id}}}]}}]}]}


class _DeleteRecorder:
    def __init__(self):
        self.calls = []

    def table(self, name):
        rec = self
        chain = []

        class _Q:
            def __getattr__(self, attr):
                if attr == "execute":
                    def execute():
                        rec.calls.append((name, list(chain)))
                        return type("R", (), {"data": []})()
                    return execute

                def step(*args, **kwargs):
                    chain.append((attr, args))
                    return self
                return step
        return _Q()


class WebhookReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = dev_client(main.app, raise_server_exceptions=False)
        cls._patches = [
            mock.patch.object(main, "send_whatsapp_text", lambda *a, **k: True),
            mock.patch.object(main, "send_whatsapp_interactive_buttons", lambda *a, **k: True),
        ]
        for p in cls._patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()

    def setUp(self):
        self.client.post("/api/v1/reset", headers=KEY)

    def _post(self, body):
        import hashlib
        import hmac
        raw = json.dumps(body).encode()
        sig = "sha256=" + hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()
        return self.client.post("/api/v1/webhooks/whatsapp", content=raw,
                                headers={"content-type": "application/json", "x-hub-signature-256": sig})

    def test_release_webhook_event_offline(self):
        self.assertTrue(db.record_webhook_event("wamid.R"))
        db.release_webhook_event("wamid.R")
        self.assertTrue(db.record_webhook_event("wamid.R"))
        db.release_webhook_event("wamid.unknown")  # no-op

    def test_release_webhook_event_live_deletes_by_message_id(self):
        rec = _DeleteRecorder()
        with mock.patch("app.db._get_supabase", return_value=rec):
            db.release_webhook_event("wamid.R")
        (table, chain), = rec.calls
        self.assertEqual(table, "webhook_events")
        self.assertIn(("delete", ()), chain)
        self.assertIn(("eq", ("message_id", "wamid.R")), chain)

    def test_release_webhook_event_live_failure_raises(self):
        with mock.patch("app.db._get_supabase", return_value=FailingClient()):
            with self.assertRaises(db.DatabaseError):
                db.release_webhook_event("wamid.R")

    def test_approval_database_error_releases_event_and_retry_is_processed(self):
        sim = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY).json()
        body = _meta_button("919800000000", f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}", "wamid.APR")
        with mock.patch.object(main, "_execute", side_effect=db.DatabaseError("rpc", "execute_plan_tx")):
            r = self._post(body)
        self.assertEqual(r.status_code, 503)
        self.assertIsNone(db.get_receipt(sim["run_id"]))
        r2 = self._post(body)  # Meta's retry
        self.assertEqual(r2.json().get("action"), "plan_executed")
        self.assertIsNotNone(db.get_receipt(sim["run_id"]))
        self.assertEqual(self._post(body).json()["status"], "duplicate")  # handled -> stays recorded

    def test_unexpected_exception_releases_event_and_reraises(self):
        body = _meta_text("919800000009", "ok 100 units at 500", msg_id="wamid.BOOM")
        with mock.patch.object(main.sourcing, "find_open_rfq_by_number", side_effect=RuntimeError("kaboom")):
            r = self._post(body)
        self.assertEqual(r.status_code, 500)
        retry = self._post(_meta_text("919800000009", "status", msg_id="wamid.BOOM"))
        self.assertNotEqual(retry.json()["status"], "duplicate")

    def test_release_failure_is_swallowed_original_error_surfaces(self):
        body = _meta_text("919800000009", "ok 1", msg_id="wamid.REL")
        with mock.patch.object(main.sourcing, "find_open_rfq_by_number",
                               side_effect=db.DatabaseError("fetch_all", "sourcing_sessions")), \
                mock.patch.object(db, "release_webhook_event",
                                  side_effect=db.DatabaseError("delete", "webhook_events")):
            r = self._post(body)
        self.assertEqual(r.status_code, 503)
        self.assertIn("fetch_all", r.json()["detail"])

    def test_successful_message_redelivery_is_duplicate(self):
        body = _meta_text("919800000001", "status", msg_id="wamid.OK")
        self.assertNotEqual(self._post(body).json()["status"], "duplicate")
        self.assertEqual(self._post(body).json()["status"], "duplicate")

    def test_find_open_rfq_runs_in_threadpool(self):
        seen = []
        real = main.run_in_threadpool

        async def spy(fn, *a, **k):
            seen.append(getattr(fn, "__name__", ""))
            return await real(fn, *a, **k)
        with mock.patch.object(main, "run_in_threadpool", spy):
            self._post(_meta_text("919800000001", "status", msg_id="wamid.TP"))
        self.assertIn("find_open_rfq_by_number", seen)


class FixWaveDbTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()

    def test_offline_execute_unknown_order_rolls_back(self):
        args = dict(ExecutePlanTxTests.ARGS, order_id="NO-SUCH-ORDER")
        with self.assertRaises(db.DatabaseError):
            db.execute_plan_tx(**args)
        self.assertIsNone(db.get_receipt("R1"))
        self.assertEqual(db.fetch_all("purchase_orders"), [])

    def test_offline_credentials_warning_logged_once(self):
        db._warned_offline = False
        with self.assertLogs("cascadezero.db", level="WARNING") as cm:
            for _ in range(3):
                db.fetch_all("orders")
        self.assertEqual(sum("credentials not configured" in m for m in cm.output), 1)

    def test_reset_uses_per_table_filters_without_retry(self):
        rec = _DeleteRecorder()
        with mock.patch("app.db._get_supabase", return_value=rec):
            db.reset_to_seed()
        per_table = {}
        for t, c in rec.calls:
            if any(s == "delete" for s, _ in c):
                per_table.setdefault(t, []).append(c)
        for t in ("purchase_orders", "agent_logs", "disruption_events"):
            self.assertEqual(len(per_table[t]), 1, t)
        cols = [a[0] for s, a in per_table["purchase_orders"][0] if s in ("neq", "gte")]
        self.assertEqual(cols, ["po_number"])

    def test_save_run_preserves_created_at(self):
        run_store.save_run({"run_id": "RUN-OLD", "factory_id": "f"})
        first = db.fetch_by_id("analysis_runs", "run_id", "RUN-OLD")["created_at"]
        run_store.save_run({"run_id": "RUN-NEW", "factory_id": "f"})
        run_store.save_run({"run_id": "RUN-OLD", "factory_id": "f", "x": 1})
        self.assertEqual(db.fetch_by_id("analysis_runs", "run_id", "RUN-OLD")["created_at"], first)
        self.assertEqual(run_store.latest_run_id(), "RUN-NEW")


class MigrationSqlTests(unittest.TestCase):
    SQL = (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"
           / "004_durable_state.sql").read_text(encoding="utf-8")

    def test_prerequisite_guard_precedes_seeding(self):
        seed = self.SQL.index("INSERT INTO schema_migrations")
        head = self.SQL[:seed]
        self.assertIn("RAISE EXCEPTION", head)
        for needle in ("approved_by", "whatsapp_number", "factories"):
            self.assertIn(needle, head)

    def test_execute_plan_tx_hardening(self):
        self.assertIn("SET search_path = public", self.SQL)
        self.assertIn("IF NOT FOUND THEN", self.SQL)
        self.assertNotIn("so table defaults are never overridden", self.SQL)


if __name__ == "__main__":
    unittest.main()
