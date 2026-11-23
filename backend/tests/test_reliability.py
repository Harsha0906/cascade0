"""Round A / Task 1: vendor reliability learned from recorded deliveries (Beta posterior)."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_HEADERS, dev_client  # noqa: F401
from fastapi.testclient import TestClient

from app import db, main
from app.factory_model import load_factory_model
from app.reliability import beta_reliability, on_time

KEY = DEV_HEADERS  # dev-owner@example.test (AUTH_MODE=dev)
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)   # fixed, in the past (future deliveries are 422)


class BetaMathTests(unittest.TestCase):
    def test_demo_prior(self):
        self.assertEqual(beta_reliability(48, 50, 0, 0), 94.2)
        self.assertEqual(beta_reliability(14, 15, 0, 0), 88.2)
        self.assertEqual(beta_reliability(9, 11, 0, 0), 76.9)
        self.assertEqual(beta_reliability(5, 5, 0, 0), 85.7)

    def test_no_history_is_one_half(self):
        self.assertEqual(beta_reliability(0, 0, 0, 0), 50.0)

    def test_always_inside_zero_to_hundred(self):
        for args in ((0, 1000, 0, 1000), (1000, 1000, 1000, 1000), (0, 0, 0, 0)):
            self.assertTrue(0.0 <= beta_reliability(*args) <= 100.0)

    def test_inconsistent_counts_raise(self):
        with self.assertRaises(ValueError):
            beta_reliability(5, 3, 0, 0)
        with self.assertRaises(ValueError):
            beta_reliability(1, 3, 2, 1)
        with self.assertRaises(ValueError):
            beta_reliability(-1, 3, 0, 0)

    def test_on_time_grace(self):
        promised = NOW
        self.assertTrue(on_time(promised, promised + timedelta(hours=2)))
        self.assertFalse(on_time(promised, promised + timedelta(hours=2, minutes=1)))
        self.assertTrue(on_time(promised.isoformat(), (promised - timedelta(hours=9)).isoformat()))
        self.assertFalse(on_time(promised, promised + timedelta(hours=5), grace_hours=4))


class _Api(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        self.client = dev_client(main.app)

    def _record_outcome(self, supplier_id, po, delivered_hours_after_promise, units=100):
        promised = NOW
        db.insert_row("delivery_outcomes", {
            "id": len(db._mirror.delivery_outcomes) + 1, "factory_id": "apex-volt-blr2",
            "supplier_id": supplier_id, "po_number": po, "units": units,
            "promised_at": promised.isoformat(), "delivered_at": None, "status": "PENDING",
            "recorded_at": NOW.isoformat(),
        })
        return self.client.post("/api/v1/deliveries", headers=KEY, json={
            "po_number": po, "supplier_id": supplier_id,
            "delivered_at": (promised + timedelta(hours=delivered_hours_after_promise)).isoformat()})

    def _reliability(self, sid):
        return next(v for v in load_factory_model().vendors if v.supplier_id == sid).reliability_pct


class LearnedReliabilityTests(_Api):
    def test_loader_uses_beta_not_the_stored_score(self):
        v = {x.supplier_id: x for x in load_factory_model().vendors}
        self.assertEqual({k: x.reliability_pct for k, x in v.items()},
                         {"SUP-PNY-02": 88.2, "SUP-HSR-03": 76.9, "SUP-AIR-04": 85.7})
        self.assertEqual((v["SUP-HSR-03"].prior_total, v["SUP-HSR-03"].outcomes_total), (11, 0))

    def test_late_deliveries_lower_reliability(self):
        before = self._reliability("SUP-HSR-03")
        for i in range(3):
            r = self._record_outcome("SUP-HSR-03", f"PO-LATE-{i}", 10)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertFalse(r.json()["on_time"])
        after = self._reliability("SUP-HSR-03")
        self.assertLess(after, before)
        self.assertEqual(after, beta_reliability(9, 11, 0, 3))

    def test_on_time_deliveries_raise_reliability(self):
        before = self._reliability("SUP-HSR-03")
        for i in range(3):
            r = self._record_outcome("SUP-HSR-03", f"PO-OK-{i}", -1)
            self.assertTrue(r.json()["on_time"])
        self.assertGreater(self._reliability("SUP-HSR-03"), before)

    def test_pending_outcomes_do_not_count(self):
        db.insert_row("delivery_outcomes", {
            "id": 1, "factory_id": "apex-volt-blr2", "supplier_id": "SUP-HSR-03", "po_number": "PO-P",
            "units": 10, "promised_at": NOW.isoformat(), "delivered_at": None, "status": "PENDING",
            "recorded_at": NOW.isoformat()})
        self.assertEqual(self._reliability("SUP-HSR-03"), 76.9)

    def test_response_reports_new_reliability(self):
        r = self._record_outcome("SUP-HSR-03", "PO-X", 10)
        self.assertEqual(r.json()["reliability_pct"], beta_reliability(9, 11, 0, 1))

    def test_factory_endpoint_exposes_evidence_counts(self):
        self._record_outcome("SUP-PNY-02", "PO-Y", 0)
        vendors = {v["supplier_id"]: v for v in self.client.get("/api/v1/factory").json()["vendors"]}
        self.assertEqual((vendors["SUP-PNY-02"]["prior_total"], vendors["SUP-PNY-02"]["outcomes_total"]), (15, 1))

    def test_seed_history_cannot_exceed_total(self):
        for row in db._mirror.vendor_history:
            if row["supplier_id"] == "SUP-PNY-02":
                row["on_time_deliveries"] = 99
        from app.factory_model import FactoryDataError
        with self.assertRaisesRegex(FactoryDataError, "on_time_deliveries"):
            load_factory_model()


class DeliveryEndpointTests(_Api):
    def test_unknown_outcome_is_404(self):
        r = self.client.post("/api/v1/deliveries", headers=KEY, json={
            "po_number": "PO-NOPE", "supplier_id": "SUP-NOPE", "delivered_at": NOW.isoformat()})
        self.assertEqual(r.status_code, 404)

    def test_double_record_is_409(self):
        self.assertEqual(self._record_outcome("SUP-HSR-03", "PO-D", 0).status_code, 200)
        r = self.client.post("/api/v1/deliveries", headers=KEY, json={
            "po_number": "PO-D", "supplier_id": "SUP-HSR-03", "delivered_at": NOW.isoformat()})
        self.assertEqual(r.status_code, 409)

    def test_missing_or_invalid_date_is_422(self):
        for body in ({"po_number": "P", "supplier_id": "S"},
                     {"po_number": "P", "supplier_id": "S", "delivered_at": "not-a-date"}):
            self.assertEqual(self.client.post("/api/v1/deliveries", headers=KEY, json=body).status_code, 422)

    def test_implausibly_early_is_422_and_changes_nothing(self):
        r = self._record_outcome("SUP-HSR-03", "PO-E", -24 * 31)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.client.get("/api/v1/deliveries?status=PENDING").json()["outcomes"][0]["status"], "PENDING")
        self.assertEqual(self._reliability("SUP-HSR-03"), 76.9)

    def test_requires_api_key(self):
        r = TestClient(main.app).post("/api/v1/deliveries", json={  # no credentials
            "po_number": "P", "supplier_id": "S", "delivered_at": NOW.isoformat()})
        self.assertEqual(r.status_code, 401)

    def test_list_filters_by_status(self):
        self._record_outcome("SUP-HSR-03", "PO-1", 0)
        db.insert_row("delivery_outcomes", {
            "id": 99, "factory_id": "apex-volt-blr2", "supplier_id": "SUP-PNY-02", "po_number": "PO-2",
            "units": 5, "promised_at": NOW.isoformat(), "delivered_at": None, "status": "PENDING",
            "recorded_at": NOW.isoformat()})
        pending = self.client.get("/api/v1/deliveries?status=PENDING").json()["outcomes"]
        done = self.client.get("/api/v1/deliveries?status=DELIVERED").json()["outcomes"]
        self.assertEqual([o["po_number"] for o in pending], ["PO-2"])
        self.assertEqual([o["po_number"] for o in done], ["PO-1"])
        self.assertEqual(self.client.get("/api/v1/deliveries?status=BOGUS").status_code, 422)


class ExecuteCreatesPendingOutcomesTests(_Api):
    def _simulate_and_execute(self, scenario=1):
        sim = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": scenario}, headers=KEY).json()
        run = main.run_store.get_run(sim["run_id"])
        play = next(p for p in run["playbooks"] if p["id"] == sim["recommended_plan_id"])
        r = self.client.post("/api/v1/execute-plan", headers=KEY, json={
            "run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), play

    def test_one_pending_outcome_per_allocated_vendor(self):
        receipt, play = self._simulate_and_execute(1)
        outcomes = db.get_delivery_outcomes(status="PENDING")
        allocs = [a for a in play["vendor_allocations"] if a["units_allocated"] > 0]
        self.assertGreaterEqual(len(allocs), 1)
        self.assertEqual(sorted(o["supplier_id"] for o in outcomes), sorted(a["supplier_id"] for a in allocs))
        self.assertTrue(all(o["po_number"] == receipt["po_number"] for o in outcomes))
        by = {a["supplier_id"]: a for a in allocs}
        self.assertTrue(all(o["units"] == by[o["supplier_id"]]["units_allocated"] for o in outcomes))
        # promised_at = execution time + the vendor's lead time
        executed = datetime.fromisoformat(receipt["executed_at"])
        for o in outcomes:
            lead = next(v.lead_hours for v in load_factory_model().vendors if v.supplier_id == o["supplier_id"])
            delta = datetime.fromisoformat(o["promised_at"]) - executed
            self.assertAlmostEqual(delta.total_seconds() / 3600, lead, places=2)

    def test_recorded_delivery_moves_reliability_after_execute(self):
        receipt, _ = self._simulate_and_execute(1)
        o = db.get_delivery_outcomes(status="PENDING")[0]
        before = self._reliability(o["supplier_id"])
        # The promise is hours ahead; move it into the past so a 30h-late delivery is not in the future.
        promised = datetime.now(timezone.utc) - timedelta(hours=40)
        db.update_rows_where("delivery_outcomes", {"po_number": o["po_number"], "supplier_id": o["supplier_id"]},
                             {"promised_at": promised.isoformat()})
        late = promised + timedelta(hours=30)
        r = self.client.post("/api/v1/deliveries", headers=KEY, json={
            "po_number": receipt["po_number"], "supplier_id": o["supplier_id"], "delivered_at": late.isoformat()})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertLess(self._reliability(o["supplier_id"]), before)

    def test_execute_rollback_leaves_no_outcomes(self):
        sim = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY).json()
        with mock.patch.object(db, "update_rows", return_value=[]):  # order not found -> rolls back
            with self.assertRaises(db.DatabaseError):
                main._execute(main.ExecutePlanRequest(run_id=sim["run_id"], playbook_id=sim["recommended_plan_id"]),
                              "dev-owner@example.test")
        self.assertEqual(db.get_delivery_outcomes(), [])

    def test_repeat_execute_does_not_duplicate_outcomes(self):
        sim = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY).json()
        body = {"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}
        self.client.post("/api/v1/execute-plan", headers=KEY, json=body)
        n = len(db.get_delivery_outcomes())
        self.client.post("/api/v1/execute-plan", headers=KEY, json=body)
        self.assertEqual(len(db.get_delivery_outcomes()), n)

    def test_live_path_sends_outcomes_param(self):
        captured = {}

        def fake_call(name, params):
            captured.update(params)
            return None
        with mock.patch.object(db, "_get_supabase", return_value=object()), \
                mock.patch.object(db, "call_function", fake_call):
            db.execute_plan_tx(po={}, order_id="X", order_status="S", supplier_updates=[], overtime_line_ids=[],
                               agent_log={}, root_run_id="R", receipt={"a": 1}, outcomes=[{"po_number": "P"}])
        self.assertEqual(captured["p_outcomes"], [{"po_number": "P"}])


class ScenarioWinnersTests(_Api):
    def test_scenarios_keep_their_winners(self):
        got = []
        for sid in (1, 2, 3):
            r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": sid}, headers=KEY)
            self.assertEqual(r.status_code, 200, r.text)
            got.append(r.json()["recommended_plan_id"])
        self.assertEqual(got, ["PLAN_B", "PLAN_C", "PLAN_B"])


class MigrationFileTests(unittest.TestCase):
    def test_007_drops_old_signature_and_guards_on_006(self):
        from pathlib import Path
        sql = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
               / "007_learning_and_coordination.sql").read_text(encoding="utf-8")
        self.assertIn("version = 6", sql)
        self.assertIn("DROP FUNCTION IF EXISTS execute_plan_tx(JSONB, TEXT, TEXT, JSONB, TEXT[], JSONB, TEXT, JSONB)", sql)
        self.assertIn("p_outcomes           JSONB DEFAULT", sql)
        self.assertIn("VALUES (7)", sql)


if __name__ == "__main__":
    unittest.main()
