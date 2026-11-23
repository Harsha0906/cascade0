"""API tests (offline: in-memory DB mirror, no LLM, no outbound messages)."""

import copy
import json
import unittest
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_HEADERS, dev_client  # noqa: F401
from fastapi.testclient import TestClient

from concurrent.futures import ThreadPoolExecutor

from app import db, main, run_store
from app.factory_model import FactoryDataError

KEY = DEV_HEADERS  # dev-owner@example.test (AUTH_MODE=dev)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = dev_client(main.app)

    def setUp(self):
        self.client.post("/api/v1/reset", headers=KEY)

    def _simulate(self, scenario=1):
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": scenario}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── factory data ──
    def test_factory_endpoint_lists_data(self):
        d = self.client.get("/api/v1/factory").json()
        self.assertEqual(d["factory_id"], "apex-volt-blr2")
        self.assertIn("SUP-PNY-02", [v["supplier_id"] for v in d["vendors"]])

    def test_invalid_factory_data_is_503_with_reason(self):
        with mock.patch("app.agents.graph.load_factory_model",
                        side_effect=FactoryDataError("suppliers.lead_time_sigma_hours missing — apply supabase/migrations/003_factory_model.sql")):
            r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY)
        self.assertEqual(r.status_code, 503)
        self.assertIn("003_factory_model", r.json()["detail"])

    def test_execution_marks_only_scheduled_overtime_lines(self):
        sim = self._simulate(2)
        # Store a run whose chosen plan schedules overtime on LINE-1 only.
        run = copy.deepcopy(run_store.get_run(sim["run_id"]))
        run["run_id"] = "RUN-OT-LINE1"
        playbook = next(p for p in run["playbooks"] if p["id"] == sim["recommended_plan_id"])
        playbook.update(overtime_line_hours={"LINE-1": 2}, overtime_hours=2, feasible=True)
        run_store.save_run(run)
        r = self.client.post("/api/v1/execute-plan",
                             json={"run_id": "RUN-OT-LINE1", "playbook_id": playbook["id"]}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        lines = {l["line_id"]: l["status"] for l in self.client.get("/api/v1/state").json()["production_lines"]}
        self.assertEqual(lines["LINE-1"], "OVERTIME_SCHEDULED")
        self.assertNotEqual(lines["LINE-3"], "OVERTIME_SCHEDULED")
        self.assertNotEqual(lines["LINE-2"], "OVERTIME_SCHEDULED")

    # ── factory-data error handling ──
    def test_factory_endpoint_503_on_invalid_data(self):
        with mock.patch.object(main, "load_factory_model", side_effect=FactoryDataError("bad lines")):
            r = self.client.get("/api/v1/factory")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["detail"], "Factory data invalid: bad lines")

    def test_sourcing_start_503_on_invalid_factory_data(self):
        sim = self._simulate(1)
        # Runs carry their factory snapshot; only a run without one reloads (and can fail) here.
        run = run_store.get_run(sim["run_id"])
        run.pop("factory_model")
        run_store.save_run(run)
        with mock.patch("app.agents.sourcing.load_factory_model", side_effect=FactoryDataError("bad vendors")):
            r = self.client.post("/api/v1/sourcing/start",
                                 json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}, headers=KEY)
        self.assertEqual(r.status_code, 503, r.text)
        self.assertIn("Factory data invalid: bad vendors", r.json()["detail"])

    # ── auth ──
    def test_mutating_endpoints_require_credentials(self):
        anon = TestClient(main.app)  # no X-Dev-User / bearer
        for path, body in [
            ("/api/v1/simulate-crisis", {"scenario_id": 1}),
            ("/api/v1/execute-plan", {"run_id": "x", "playbook_id": "PLAN_B"}),
            ("/api/v1/reset", None),
            ("/api/v1/ingest/erp-csv", {"filename": "a.csv", "csv_content": "order_id\nX"}),
            ("/api/v1/ingest/plc-telemetry", {}),
        ]:
            with self.subTest(path=path):
                self.assertEqual(anon.post(path, json=body).status_code, 401)
                self.assertEqual(anon.post(path, json=body, headers={"X-API-Key": "wrong"}).status_code, 401)

    def test_state_needs_credentials(self):
        self.assertEqual(self.client.get("/api/v1/state").status_code, 200)
        self.assertEqual(TestClient(main.app).get("/api/v1/state").status_code, 401)

    # ── simulation discloses AI mode ──
    def test_simulation_reports_fallback_mode(self):
        data = self._simulate(1)
        self.assertEqual(data["ai_mode"]["overall"], "fallback")
        self.assertEqual(data["extracted_parameters"]["source"], "regex-fallback")
        self.assertEqual(data["recommended_plan_id"], "PLAN_B")

    def test_custom_text_is_parsed(self):
        r = self.client.post(
            "/api/v1/simulate-crisis",
            json={"raw_message": "Truck breakdown, 120 casings short on EV-402, Line 2 at 60%, 24h delay"},
            headers=KEY,
        )
        p = r.json()["extracted_parameters"]
        self.assertEqual((p["shortfall_units"], p["line_impacts"][0]["speed_pct"], p["delay_hours"]), (150, 60, 24))
        self.assertEqual((p["shortfall_source"], p["alert_stated_shortfall"]), ("inventory", 120))

    # ── execution uses server-side numbers, once ──
    def test_execute_uses_server_plan_and_is_idempotent(self):
        sim = self._simulate(1)
        plan = next(p for p in sim["playbooks"] if p["id"] == sim["recommended_plan_id"])
        body = {"run_id": sim["run_id"], "playbook_id": plan["id"], "approved_by": "tester",
                "total_cost_inr": 1}  # extra client fields (cost, approver) must be ignored
        r1 = self.client.post("/api/v1/execute-plan", json=body, headers=KEY)
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r1.json()["total_cost_inr"], plan["total_mitigation_cost_inr"])
        self.assertEqual(r1.json()["approved_by"], "dev-owner@example.test")  # the verified actor
        r2 = self.client.post("/api/v1/execute-plan", json=body, headers=KEY)
        self.assertTrue(r2.json()["already_executed"])
        self.assertEqual(r2.json()["po_number"], r1.json()["po_number"])

    def test_execute_unknown_run_is_404(self):
        r = self.client.post("/api/v1/execute-plan", json={"run_id": "RUN-NOPE", "playbook_id": "PLAN_B"}, headers=KEY)
        self.assertEqual(r.status_code, 404)

    def test_execute_infeasible_plan_is_rejected(self):
        r = self.client.post("/api/v1/simulate-crisis",
                             json={"scenario_id": 3, "override_shortfall_units": 1000}, headers=KEY)
        sim = r.json()
        r = self.client.post("/api/v1/execute-plan",
                             json={"run_id": sim["run_id"], "playbook_id": "PLAN_B"}, headers=KEY)
        self.assertEqual(r.status_code, 409)

    # ── atomic / idempotent execution ──
    def test_execution_is_atomic(self):
        sim = self._simulate(1)
        real_update = db.update_rows_where

        def fail_on_suppliers(table, *a, **k):
            if table == "suppliers":
                raise RuntimeError("mid-transaction failure")
            return real_update(table, *a, **k)

        with mock.patch("app.db.update_rows_where", side_effect=fail_on_suppliers):
            with self.assertRaises(Exception):
                self.client.post("/api/v1/execute-plan", json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}, headers=KEY)
        self.assertEqual(db.fetch_all("purchase_orders"), [])
        self.assertIsNone(db.get_receipt(sim["run_id"]))
        self.assertNotEqual(db.get_order("EV-402")["status"], "RECOVERY_IN_PROGRESS")

    def test_concurrent_approvals_create_one_po(self):
        sim = self._simulate(1)
        body = {"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}
        with ThreadPoolExecutor(4) as ex:
            results = list(ex.map(lambda _: self.client.post("/api/v1/execute-plan", json=body, headers=KEY), range(4)))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertEqual(len(db.fetch_all("purchase_orders")), 1)
        self.assertEqual(sum(not r.json()["already_executed"] for r in results), 1)

    def test_missing_rpc_function_is_503(self):
        with mock.patch("app.db.execute_plan_tx", side_effect=db.DatabaseError("rpc", "execute_plan_tx")):
            sim = self._simulate(1)
            r = self.client.post("/api/v1/execute-plan", json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}, headers=KEY)
        self.assertEqual(r.status_code, 503)

    def test_receipt_carries_run_and_playbook(self):
        sim = self._simulate(1)
        self.client.post("/api/v1/execute-plan", json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}, headers=KEY)
        stored = db.get_receipt(sim["run_id"])
        self.assertEqual(stored["run_id"], sim["run_id"])
        self.assertEqual(stored["playbook_id"], sim["recommended_plan_id"])

    # ── ERP import ──
    def test_csv_inserts_new_orders_and_reports_bad_rows(self):
        csv_text = ("order_id,client,required_qty,sla_penalty_inr,partial_delay_penalty_inr,hours_remaining\n"
                    "NEW-1,Acme,100,50000,100,48\n,Missing,1,1,1,1\nBAD-1,X,abc,1,1,1\n")
        r = self.client.post("/api/v1/ingest/erp-csv", json={"filename": "o.csv", "csv_content": csv_text}, headers=KEY)
        data = r.json()
        self.assertEqual(data["orders"], ["NEW-1"])
        self.assertEqual(len(data["errors"]), 2)
        ids = [o["order_id"] for o in self.client.get("/api/v1/state").json()["orders"]]
        self.assertIn("NEW-1", ids)

    # ── round-2 regressions ──
    def test_second_execution_with_different_plan_is_rejected(self):
        sim = self._simulate(1)
        first = self.client.post("/api/v1/execute-plan",
                                 json={"run_id": sim["run_id"], "playbook_id": "PLAN_B"}, headers=KEY)
        self.assertEqual(first.status_code, 200)
        other = self.client.post("/api/v1/execute-plan",
                                 json={"run_id": sim["run_id"], "playbook_id": "PLAN_A"}, headers=KEY)
        self.assertEqual(other.status_code, 409)
        bogus = self.client.post("/api/v1/execute-plan",
                                 json={"run_id": sim["run_id"], "playbook_id": "PLAN_ZZ"}, headers=KEY)
        self.assertEqual(bogus.status_code, 404)

    def test_out_of_range_inputs_are_422(self):
        for body in [{"override_shortfall_units": -5}, {"override_line_speeds": {"LINE-1": 500}},
                     {"scenario_id": 0}, {"raw_message": "x" * 5000}]:
            with self.subTest(body=body):
                r = self.client.post("/api/v1/simulate-crisis", json=body, headers=KEY)
                self.assertEqual(r.status_code, 422)

    def test_zero_override_is_respected(self):
        r = self.client.post("/api/v1/simulate-crisis",
                             json={"scenario_id": 1, "override_delay_hours": 0}, headers=KEY)
        self.assertEqual(r.json()["extracted_parameters"]["delay_hours"], 0)

    def test_rebuttal_counts_one_round(self):
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 3}, headers=KEY)
        self.assertTrue(r.json()["rebuttal_occurred"])
        run = run_store.get_run(r.json()["run_id"])
        self.assertEqual(run["rebuttal_count"], 1)

    def test_passed_deadline_is_422_not_500(self):
        csv_text = "order_id,client,required_qty,sla_penalty_inr,hours_remaining\nEV-402,Ather,500,2500000,1\n"
        self.client.post("/api/v1/ingest/erp-csv", json={"filename": "o.csv", "csv_content": csv_text}, headers=KEY)
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY)
        self.assertEqual(r.status_code, 422)

    def test_csv_infinite_value_is_rejected_cleanly(self):
        csv_text = "order_id,client,required_qty\nINF-1,X,inf\n"
        r = self.client.post("/api/v1/ingest/erp-csv", json={"filename": "o.csv", "csv_content": csv_text}, headers=KEY)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["errors"]), 1)

    def test_cors_is_not_wildcard(self):
        r = self.client.options("/api/v1/state", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
        self.assertNotEqual(r.headers.get("access-control-allow-origin"), "*")
        self.assertNotEqual(r.headers.get("access-control-allow-origin"), "https://evil.example")

    # ── Phase 3: generic disruption API ──
    def test_scenarios_endpoint_lists_presets_from_data(self):
        r = self.client.get("/api/v1/scenarios")
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual([x["scenario_id"] for x in rows], [1, 2, 3])
        self.assertEqual(rows[0]["line_speeds"], {"LINE-2": 50})
        self.assertEqual(rows[0]["order_id"], "EV-402")
        self.assertEqual(rows[0]["title"], "NH48 flood + Line 2 overheat")

    def test_scenario_1_reports_line_impacts(self):
        data = self._simulate(1)
        self.assertEqual(data["recommended_plan_id"], "PLAN_B")
        li = data["extracted_parameters"]["line_impacts"][0]
        self.assertEqual((li["line_id"], li["name"], li["speed_pct"]), ("LINE-2", "Robotic Welding Line 2", 50))
        self.assertNotIn("line2_speed_pct", data["extracted_parameters"])
        event = db.fetch_all("disruption_events")[-1]
        self.assertEqual((event["order_id"], event["factory_id"]), ("EV-402", "apex-volt-blr2"))
        self.assertEqual(event["line_impacts"][0]["line_id"], "LINE-2")

    def test_unknown_scenario_is_404(self):
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 9}, headers=KEY)
        self.assertEqual(r.status_code, 404)

    def test_no_scenario_and_no_message_is_422(self):
        r = self.client.post("/api/v1/simulate-crisis", json={}, headers=KEY)
        self.assertEqual(r.status_code, 422)
        self.assertIn("scenario_id or raw_message", r.json()["detail"])

    def test_line_speed_override_validation(self):
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1,
                             "override_line_speeds": {"LINE-1": 120}}, headers=KEY)
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1,
                             "override_line_speeds": {"LINE-9": 50}}, headers=KEY)
        self.assertEqual(r.status_code, 422)
        self.assertIn("LINE-1", r.json()["detail"])

    def test_custom_text_line_speed(self):
        r = self.client.post("/api/v1/simulate-crisis", headers=KEY, json={
            "raw_message": "Truck breakdown, 120 casings short on EV-402, Line 2 at 60%, 24h delay"})
        p = r.json()["extracted_parameters"]
        self.assertEqual(p["line_impacts"][0]["speed_pct"], 60)
        # EV-402 has inventory data: the computed shortfall wins; the alert's 120 is reported, not used.
        self.assertEqual((p["shortfall_source"], p["alert_stated_shortfall"]), ("inventory", 120))

    def test_plc_requires_known_line(self):
        r = self.client.post("/api/v1/ingest/plc-telemetry", json={"speed_pct": 50}, headers=KEY)
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/v1/ingest/plc-telemetry", json={"line_id": "LINE-9", "speed_pct": 50,
                             "temp_celsius": 60.0, "status": "NORMAL"}, headers=KEY)
        self.assertEqual(r.status_code, 404)
        r = self.client.post("/api/v1/ingest/plc-telemetry", json={"line_id": "LINE-1", "speed_pct": 70,
                             "temp_celsius": 60.0, "status": "NORMAL"}, headers=KEY)
        self.assertEqual(r.status_code, 200)

    def test_status_text_reads_lines_and_orders_from_data(self):
        self.assertIn("All lines normal; all orders on track.", main._status_text())
        self._simulate(1)
        text = main._status_text()
        self.assertIn("Robotic Welding Line 2", text)
        self.assertIn("EV-402", text)

    def test_execute_on_second_factory_run(self):
        from tests.factories import seed_second_factory
        from app.agents.graph import run_cascade_pipeline
        seed_second_factory()
        try:
            result = run_cascade_pipeline(
                "L-B at 40%, 80 units short on WO-77, 5h delay from Vendor V1", factory_id="test-plant")
            run_store.save_run(result)
            pid = result["recommended_plan_id"]
            # Executed by test-plant's owner: the run's own factory (Round B Task 2 tenancy).
            r = self.client.post("/api/v1/execute-plan", json={"run_id": result["run_id"], "playbook_id": pid},
                                 headers={"X-Dev-User": "other@example.test"})
            self.assertEqual(r.status_code, 200, r.text)
            # dev-owner is not a member of test-plant: 404, as for an unknown run.
            r = self.client.post("/api/v1/execute-plan",
                                 json={"run_id": result["run_id"], "playbook_id": pid}, headers=KEY)
            self.assertEqual(r.status_code, 404, r.text)
            expected = {"SLA_RENEGOTIATION": "EXTENSION_REQUESTED", "NO_ACTION": "RISK_ACCEPTED"}.get(
                next(p for p in result["playbooks"] if p["id"] == pid)["strategy_type"], "RECOVERY_IN_PROGRESS")
            self.assertEqual(db.get_order("WO-77")["status"], expected)
        finally:
            db.reset_to_seed()


if __name__ == "__main__":
    unittest.main()
