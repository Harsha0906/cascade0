"""Tenant scoping (Round B Task 2, Review Focus 1): every endpoint authorises against the factory
of the RESOURCE it touches. A user who is not a member of that factory gets 404 (no existence
leak) and nothing is written; a member without the needed role gets 403."""

import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_OWNER, DEV_VIEWER, OTHER_OWNER, dev_client
from tests.factories import seed_second_factory

from app import db, main

TP = "test-plant"
APEX = "apex-volt-blr2"
KEY = {"X-API-Key": "test-operator-key"}
TP_MESSAGE = "L-B at 40%, 80 units short on WO-77, 5h delay from Vendor V1"


def _mirror_snapshot():
    return copy.deepcopy({k: v for k, v in vars(db._mirror).items()})


class TenancyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
        db.reset_to_seed()
        seed_second_factory()
        due = (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat()
        db.update_rows("orders", "order_id", "WO-77", {"due_at": due})   # the Client Agent needs a due_at
        self.owner = dev_client(main.app)                      # owner of apex-volt-blr2
        self.viewer = dev_client(main.app, user=DEV_VIEWER)    # viewer of apex-volt-blr2
        self.other = dev_client(main.app, user=OTHER_OWNER)    # owner of test-plant

    def tearDown(self):
        db.reset_to_seed()

    # ── fixtures built through the API by each factory's own owner ──
    def _tp_run(self):
        r = self.other.post("/api/v1/simulate-crisis", json={"raw_message": TP_MESSAGE, "factory_id": TP})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _apex_run(self):
        r = self.owner.post("/api/v1/simulate-crisis", json={"scenario_id": 1})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _tp_world(self):
        """A test-plant run with a sourcing session, a client draft and an execution (with PENDING
        delivery outcomes), all created by test-plant's owner."""
        sim = self._tp_run()
        rid = sim["run_id"]
        r = self.other.post("/api/v1/sourcing/start", json={"run_id": rid})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.other.post("/api/v1/client/draft", json={"run_id": rid, "extension_hours": 12})
        self.assertEqual(r.status_code, 200, r.text)
        with_vendors = next(p for p in sim["playbooks"] if p["vendor_allocations"] and p["feasible"])
        r = self.other.post("/api/v1/execute-plan", json={"run_id": rid, "playbook_id": with_vendors["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        outcome = db.get_delivery_outcomes(status="PENDING")[0]
        self.assertEqual(outcome["factory_id"], TP)
        return sim, outcome

    # ── Review Focus 1: foreign factory → 404, nothing written ──
    def test_foreign_owner_gets_404_and_nothing_is_written(self):
        sim, outcome = self._tp_world()
        rid = sim["run_id"]
        pid = sim["recommended_plan_id"]
        csv = {"filename": "x.csv", "factory_id": TP}
        cases = [
            ("post", "/api/v1/simulate-crisis", {"raw_message": TP_MESSAGE, "factory_id": TP}),
            ("get", f"/api/v1/state?factory_id={TP}", None),
            ("get", f"/api/v1/factory?factory_id={TP}", None),
            ("get", f"/api/v1/scenarios?factory_id={TP}", None),
            ("get", f"/api/v1/runs/latest?factory_id={TP}", None),
            ("get", f"/api/v1/runs/{rid}", None),
            ("post", "/api/v1/sourcing/start", {"run_id": rid}),
            ("get", f"/api/v1/sourcing/{rid}", None),
            ("post", f"/api/v1/sourcing/{rid}/vendor-reply", {"supplier_id": "V1", "text": "YES 50 pcs"}),
            ("post", "/api/v1/client/draft", {"run_id": rid, "extension_hours": 24}),
            ("post", "/api/v1/client/approve", {"run_id": rid}),
            ("post", "/api/v1/client/answer", {"run_id": rid, "accepted": True}),
            ("get", f"/api/v1/client/{rid}", None),
            ("post", "/api/v1/execute-plan", {"run_id": rid, "playbook_id": pid}),
            ("post", "/api/v1/deliveries", {"po_number": outcome["po_number"], "supplier_id": outcome["supplier_id"],
                                            "delivered_at": outcome["promised_at"]}),
            ("get", f"/api/v1/deliveries?factory_id={TP}", None),
            ("post", "/api/v1/ingest/erp-csv",
             {**csv, "csv_content": "order_id,required_qty,sla_penalty_inr\nWO-77,1,1\n"}),
            ("post", "/api/v1/ingest/stock-summary", {**csv, "csv_content": "Item Code,Closing Qty\nITEM-W,999\n"}),
            ("post", "/api/v1/ingest/open-purchase-orders",
             {**csv, "csv_content": "PO Number,Item Code,Supplier ID,Qty,ETA\nPO-1,ITEM-W,V1,5,2030-01-01 10:00\n"}),
            ("post", "/api/v1/ingest/sales-order-lines", {**csv, "csv_content": "Order ID,Item Code,Qty\nWO-77,ITEM-W,1\n"}),
            ("post", "/api/v1/ingest/plc-telemetry",
             {"line_id": "L-A", "speed_pct": 1, "temp_celsius": 99.0, "status": "DOWN"}),
            ("post", "/api/v1/reset", {"factory_id": TP}),
        ]
        for method, path, body in cases:
            with self.subTest(path=path):
                before = _mirror_snapshot()
                r = getattr(self.owner, method)(path, **({"json": body} if body is not None else {}))
                self.assertEqual(r.status_code, 404, f"{path}: {r.status_code} {r.text}")
                self.assertEqual(_mirror_snapshot(), before, f"{path} wrote to the database")

    def test_test_plant_owner_cannot_touch_apex_resources(self):
        """The Task 1 probe: an owner of test-plant executed an apex run and reset apex (both 200)."""
        sim = self._apex_run()
        rid = sim["run_id"]
        cases = [
            ("post", "/api/v1/execute-plan", {"run_id": rid, "playbook_id": sim["recommended_plan_id"]}),
            ("post", "/api/v1/reset", {"factory_id": APEX}),
            ("post", "/api/v1/sourcing/start", {"run_id": rid}),
            ("post", "/api/v1/client/draft", {"run_id": rid, "extension_hours": 24}),
            ("get", f"/api/v1/runs/{rid}", None),
            ("post", "/api/v1/simulate-crisis", {"scenario_id": 1, "factory_id": APEX}),
            ("post", "/api/v1/ingest/plc-telemetry",
             {"line_id": "LINE-2", "speed_pct": 1, "temp_celsius": 99.0, "status": "DOWN"}),
        ]
        for method, path, body in cases:
            with self.subTest(path=path):
                before = _mirror_snapshot()
                r = getattr(self.other, method)(path, **({"json": body} if body is not None else {}))
                self.assertEqual(r.status_code, 404, f"{path}: {r.status_code} {r.text}")
                self.assertEqual(_mirror_snapshot(), before, f"{path} wrote to the database")

    def test_role_is_checked_in_the_resource_factory(self):
        """Owner of test-plant but only a viewer of apex: apex writes are 403, not allowed."""
        db.insert_row("factory_members", {"user_id": "00000000-0000-4000-8000-000000000003",
                                          "factory_id": APEX, "role": "viewer", "email": OTHER_OWNER})
        sim = self._apex_run()
        rid = sim["run_id"]
        for method, path, body in [
            ("post", "/api/v1/execute-plan", {"run_id": rid, "playbook_id": sim["recommended_plan_id"]}),
            ("post", "/api/v1/reset", {"factory_id": APEX}),
            ("post", "/api/v1/sourcing/start", {"run_id": rid}),
            ("post", "/api/v1/simulate-crisis", {"scenario_id": 1, "factory_id": APEX}),
        ]:
            with self.subTest(path=path):
                before = _mirror_snapshot()
                r = getattr(self.other, method)(path, **({"json": body} if body is not None else {}))
                self.assertEqual(r.status_code, 403, f"{path}: {r.status_code} {r.text}")
                self.assertEqual(_mirror_snapshot(), before)
        # A viewer may read the resource.
        self.assertEqual(self.other.get(f"/api/v1/runs/{rid}").status_code, 200)

    def test_viewer_cannot_write_own_factory(self):
        sim = self._apex_run()
        r = self.viewer.post("/api/v1/execute-plan",
                             json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.viewer.post("/api/v1/reset").status_code, 403)

    def test_foreign_run_is_indistinguishable_from_unknown(self):
        sim = self._tp_run()
        foreign = {}
        for path in (f"/api/v1/runs/{sim['run_id']}", f"/api/v1/sourcing/{sim['run_id']}",
                     f"/api/v1/client/{sim['run_id']}"):
            r = self.owner.get(path)
            self.assertEqual(r.status_code, 404)
            foreign[path] = r.json()
        rid = sim["run_id"]
        db.reset_to_seed()   # the same id, now unknown everywhere
        seed_second_factory()
        for path in (f"/api/v1/runs/{rid}", f"/api/v1/sourcing/{rid}", f"/api/v1/client/{rid}"):
            with self.subTest(path=path):
                unknown = self.owner.get(path)
                self.assertEqual(unknown.status_code, 404)
                self.assertEqual(foreign[path], unknown.json())

    def test_machine_key_is_scoped_to_its_factory(self):
        before = _mirror_snapshot()
        from fastapi.testclient import TestClient
        machine = TestClient(main.app, headers=KEY)
        r = machine.post("/api/v1/simulate-crisis", json={"raw_message": TP_MESSAGE, "factory_id": TP})
        self.assertEqual(r.status_code, 404, r.text)
        r = machine.post("/api/v1/ingest/plc-telemetry",
                         json={"line_id": "L-A", "speed_pct": 1, "temp_celsius": 99.0, "status": "DOWN"})
        self.assertEqual(r.status_code, 404, r.text)
        self.assertEqual(_mirror_snapshot(), before)

    # ── own factory works, and only its rows are visible ──
    def test_other_owner_works_end_to_end_and_sees_only_its_rows(self):
        self._apex_run()
        sim, _ = self._tp_world()
        r = self.other.get("/api/v1/state")
        self.assertEqual(r.status_code, 200, r.text)
        state = r.json()
        self.assertEqual(state["factory_name"], "Test Plant")
        self.assertEqual({s["factory_id"] for s in state["suppliers"]}, {TP})
        self.assertEqual({s["supplier_id"] for s in state["vendor_history"]}, {"V1", "V2", "V3"})
        self.assertEqual({l["factory_id"] for l in state["production_lines"]}, {TP})
        self.assertEqual([o["order_id"] for o in state["orders"]], ["WO-77"])
        for key in ("disruption_events", "agent_logs", "purchase_orders"):
            with self.subTest(key=key):
                self.assertTrue(state[key], key)
                self.assertEqual({row.get("factory_id") for row in state[key]}, {TP}, key)
        self.assertEqual(self.other.get("/api/v1/factory").json()["factory_id"], TP)
        self.assertEqual(self.other.get("/api/v1/runs/latest").json()["run_id"], sim["run_id"])
        self.assertEqual(self.other.get("/api/v1/scenarios").json(), [])
        outcomes = self.other.get("/api/v1/deliveries").json()["outcomes"]
        self.assertTrue(outcomes)
        self.assertEqual({o["factory_id"] for o in outcomes}, {TP})
        self.assertEqual(self.other.get(f"/api/v1/sourcing/{sim['run_id']}").status_code, 200)
        self.assertEqual(self.other.get(f"/api/v1/client/{sim['run_id']}").status_code, 200)

    def test_apex_state_has_no_test_plant_rows(self):
        self._tp_world()
        self._apex_run()
        state = self.owner.get("/api/v1/state").json()
        for key in ("suppliers", "production_lines", "orders", "disruption_events", "agent_logs", "purchase_orders"):
            with self.subTest(key=key):
                self.assertNotIn(TP, {row.get("factory_id") for row in state[key]})
        self.assertNotIn("V1", {v["supplier_id"] for v in state["vendor_history"]})
        self.assertNotIn(TP, {o["factory_id"] for o in self.owner.get("/api/v1/deliveries").json()["outcomes"]})
        self.assertNotEqual(self.owner.get("/api/v1/runs/latest").json()["run_id"], None)

    def test_reset_of_a_factory_without_demo_seed_is_409(self):
        r = self.other.post("/api/v1/reset")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("no demo seed for this factory", r.json()["detail"])

    def test_reset_keeps_other_factories_rows(self):
        self._tp_world()
        self._apex_run()
        r = self.owner.post("/api/v1/reset")
        self.assertEqual(r.status_code, 200, r.text)
        tp_state = self.other.get("/api/v1/state").json()
        self.assertEqual([o["order_id"] for o in tp_state["orders"]], ["WO-77"])
        self.assertTrue(tp_state["purchase_orders"])
        self.assertTrue(tp_state["agent_logs"])
        apex = self.owner.get("/api/v1/state").json()
        self.assertEqual(apex["purchase_orders"], [])
        self.assertEqual(apex["agent_logs"], [])
        self.assertIsNone(self.owner.get("/api/v1/runs/latest").json()["run_id"])

    def test_erp_import_cannot_take_over_another_factorys_order(self):
        before = db.get_order("WO-77")
        r = self.owner.post("/api/v1/ingest/erp-csv", json={
            "filename": "o.csv",
            "csv_content": "order_id,required_qty,sla_penalty_inr,partial_delay_penalty_inr,hours_remaining\n"
                           "WO-77,5,5,5,5\n"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["success"])
        self.assertEqual(db.get_order("WO-77")["factory_id"], TP)
        self.assertEqual(db.get_order("WO-77")["required_qty"], before["required_qty"])


if __name__ == "__main__":
    unittest.main()


class _RecordingQuery:
    def __init__(self, log, table):
        self.log, self.table, self.ops = log, table, []
        log.append(self)

    def __getattr__(self, name):
        def call(*args, **kwargs):
            if name == "execute":
                return type("R", (), {"data": []})()
            self.ops.append((name, args))
            return self
        return call


class _RecordingClient:
    def __init__(self):
        self.queries = []

    def table(self, name):
        return _RecordingQuery(self.queries, name)


class LiveTenancyTests(unittest.TestCase):
    """The live (Supabase) paths filter by factory too."""

    def test_live_state_filters_every_table_by_factory(self):
        fake = _RecordingClient()
        with mock.patch("app.db._get_supabase", return_value=fake):
            db.get_full_state(TP)
        for q in fake.queries:
            if q.table in ("suppliers", "production_lines", "orders", "disruption_events",
                           "agent_logs", "purchase_orders"):
                with self.subTest(table=q.table):
                    self.assertIn(("eq", ("factory_id", TP)), q.ops)
            elif q.table != "factories":
                self.fail(f"unexpected unfiltered read of {q.table}")

    def test_live_factory_reset_never_touches_other_factories(self):
        fake = _RecordingClient()
        with mock.patch("app.db._get_supabase", return_value=fake):
            db.reset_to_seed(APEX)
        deletes = [q for q in fake.queries if any(op == "delete" for op, _ in q.ops)]
        self.assertTrue(deletes)
        for q in deletes:
            with self.subTest(table=q.table):
                filters = [op for op in q.ops if op[0] in ("eq", "in_")]
                self.assertTrue(filters, f"unscoped delete on {q.table}")
                if q.table not in ("sourcing_rfqs", "sourcing_sessions"):
                    self.assertIn(("eq", ("factory_id", APEX)), q.ops)
        self.assertNotIn("webhook_events", {q.table for q in deletes})
        for table in ("purchase_orders", "agent_logs", "analysis_runs", "execution_receipts",
                      "delivery_outcomes", "order_coordination", "disruption_events"):
            self.assertIn(table, {q.table for q in deletes})

    def test_reset_refuses_a_factory_without_seed(self):
        with self.assertRaises(ValueError):
            db.reset_to_seed(TP)
