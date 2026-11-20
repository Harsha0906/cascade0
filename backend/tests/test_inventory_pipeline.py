"""Pipeline tests: the shortfall is computed from inventory (offline mirror, no LLM)."""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests import _offline_env  # noqa: F401  (must precede app imports)
from fastapi.testclient import TestClient

from app import db, main
from app.agents.graph import run_cascade_pipeline
from app.config import settings
from app.disruption import DisruptionResolutionError

KEY = {"X-API-Key": "test-operator-key"}
SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "tally"
TEXT = "Chennai shipment delayed 48h, order EV-402"


def _now():
    return datetime.now(timezone.utc)


class InventoryPipelineTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        self.client = TestClient(main.app)

    def tearDown(self):
        db.reset_to_seed()

    def test_inventory_shortfall_from_alert_without_number(self):
        r = run_cascade_pipeline(TEXT, now=_now())
        self.assertEqual((r["shortfall_units"], r["shortfall_source"]), (150, "inventory"))
        self.assertEqual((r["delay_hours"], r["order_id"]), (48, "EV-402"))
        self.assertIsNone(r["alert_stated_shortfall"])
        self.assertEqual(r["shortfall_breakdown"]["shortfall"], 150)
        self.assertIn("150 short", r["shortfall_breakdown"]["explanation"])

    def test_inventory_wins_over_alert_number_and_both_reported(self):
        r = run_cascade_pipeline(TEXT + ", 999 units short", now=_now())
        self.assertEqual((r["shortfall_units"], r["shortfall_source"]), (150, "inventory"))
        self.assertEqual(r["alert_stated_shortfall"], 999)
        logs = [x for x in db.fetch_all("agent_logs") if x.get("run_id") == r["run_id"]]
        self.assertTrue(any("alert said 999; using inventory" in str(x) for x in logs))

    def test_override_wins(self):
        r = run_cascade_pipeline(TEXT, override_shortfall_units=120, now=_now())
        self.assertEqual((r["shortfall_units"], r["shortfall_source"]), (120, "override"))
        self.assertIsNone(r["shortfall_breakdown"])

    def test_zero_shortfall_pipeline_completes(self):
        r = run_cascade_pipeline("Chennai shipment delayed 48h, order EV-405", now=_now())
        self.assertEqual((r["shortfall_units"], r["shortfall_source"]), (0, "inventory"))
        rec = next(p for p in r["playbooks"] if p["id"] == r["recommended_plan_id"])
        self.assertEqual(rec["total_mitigation_cost_inr"], 0)
        self.assertEqual(rec["confidence_pct"], 100)

    def test_no_order_line_and_no_number_is_422_naming_order(self):
        db.delete_all("order_lines")
        before = len(db.fetch_all("disruption_events"))
        resp = self.client.post("/api/v1/simulate-crisis", json={"raw_message": TEXT}, headers=KEY)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("EV-402", resp.json()["detail"])
        self.assertEqual(len(db.fetch_all("disruption_events")), before)

    def test_no_order_line_falls_back_to_alert_number(self):
        db.delete_all("order_lines")
        r = run_cascade_pipeline(TEXT + ", 90 units short", now=_now())
        self.assertEqual((r["shortfall_units"], r["shortfall_source"]), (90, "alert_text"))
        self.assertIsNone(r["shortfall_breakdown"])

    def test_missing_stock_row_propagates_as_422(self):
        db.delete_all("stock_levels")
        resp = self.client.post("/api/v1/simulate-crisis", json={"raw_message": TEXT}, headers=KEY)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("stock", resp.json()["detail"])

    def test_empty_stock_item_code_rejected(self):
        from dataclasses import replace
        from app.agents.graph import _make_shortfall_resolver
        from app.factory_model import FactoryDataError, load_factory_model
        model = replace(load_factory_model(None), stock_item_code="")
        with self.assertRaises(FactoryDataError):
            _make_shortfall_resolver(model, _now())("EV-402", None, 0)

    def test_scenario_1_is_data_driven(self):
        d = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY).json()
        p = d["extracted_parameters"]
        self.assertEqual((p["shortfall_source"], p["shortfall_units"]), ("inventory", 150))
        self.assertEqual(p["shortfall_breakdown"]["shortfall"], 150)
        self.assertEqual(d["recommended_plan_id"], "PLAN_B")

    def test_scenarios_2_and_3_are_overrides(self):
        for sid, plan in ((2, "PLAN_C"), (3, "PLAN_B")):
            with self.subTest(scenario=sid):
                d = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": sid}, headers=KEY).json()
                p = d["extracted_parameters"]
                self.assertEqual(p["shortfall_source"], "override")
                self.assertIsNone(p["shortfall_breakdown"])
                self.assertEqual(d["recommended_plan_id"], plan)

    def test_csv_import_then_alert(self):
        """Done-when: import the three sample CSVs into a fresh mirror, then the literal alert
        "Chennai shipment delayed 48h" (no order named) resolves to EV-402, 150 short."""
        for t in ("order_lines", "stock_levels", "inbound_shipments"):
            db.delete_all(t)
        for path, fname in (("stock-summary", "stock_summary.csv"),
                            ("open-purchase-orders", "open_purchase_orders.csv"),
                            ("sales-order-lines", "sales_order_lines.csv")):
            body = {"filename": fname, "csv_content": (SAMPLES / fname).read_text(encoding="utf-8")}
            data = self.client.post(f"/api/v1/ingest/{path}", json=body, headers=KEY).json()
            self.assertEqual(data["errors"], [], path)
        # the sample PO is due 21-Nov-2026 (IST): evaluate the alert at 2026-11-20 00:00 UTC,
        # with the orders due 38h and 110h after that
        now = datetime(2026, 11, 20, tzinfo=timezone.utc)
        for oid, hours in (("EV-402", 38), ("EV-405", 110)):
            db.update_rows("orders", "order_id", oid, {"due_at": (now + timedelta(hours=hours)).isoformat()})
        r = run_cascade_pipeline("Chennai shipment delayed 48h", now=now)
        self.assertEqual((r["order_id"], r["shortfall_units"], r["shortfall_source"]),
                         ("EV-402", 150, "inventory"))
        self.assertEqual(r["order_selection"], "inventory")
        self.assertEqual(r["other_order_shortfalls"], [{"order_id": "EV-405", "shortfall": 0}])


if __name__ == "__main__":
    unittest.main()
