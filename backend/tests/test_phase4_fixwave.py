"""Phase 4 fix wave: snapshot imports (I1), finished statuses (I2), capped shortfall (I3),
missing priority (I4), order selection from inventory (I5), absolute due_at deadlines (I6),
quantity-column priority (I7) and the stock-summary unit column (M3)."""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from tests import _offline_env  # noqa: F401  (must precede app imports)
from fastapi.testclient import TestClient

from app import db, main
from app.agents.graph import run_cascade_pipeline
from app.deadlines import deadline_hours
from app.disruption import DisruptionOverrides, DisruptionResolutionError, resolve_disruption
from app.factory_model import load_factory_model
from app.importers import parse_open_purchase_orders, parse_stock_summary
from app.inventory import FINISHED_STATUSES, InventoryDataError, compute_shortfall
from app.schemas import DisruptionExtraction
from tests.factories import small_factory

KEY = {"X-API-Key": "test-operator-key"}
FACTORY = "apex-volt-blr2"
ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples" / "tally"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _orders():
    return [
        {"order_id": "EV-402", "hours_remaining": 38, "priority": 10, "status": "AT_RISK"},
        {"order_id": "EV-405", "hours_remaining": 110, "priority": 20, "status": "AT_RISK"},
    ]


def _lines():
    return [{"order_id": "EV-402", "item_code": "CELL", "qty": 500},
            {"order_id": "EV-405", "item_code": "CELL", "qty": 300}]


def _sf(order="EV-402", orders=None, stock=None, ships=(), **kw):
    return compute_shortfall(order, "CELL", orders if orders is not None else _orders(), _lines(),
                             stock if stock is not None else {"CELL": 350}, list(ships), NOW, **kw)


class _Api(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        self.client = TestClient(main.app)

    def tearDown(self):
        db.reset_to_seed()

    def post(self, path, text):
        return self.client.post(f"/api/v1/ingest/{path}", json={"filename": "f.csv", "csv_content": text},
                                headers=KEY).json()


# ─── I1: imports are snapshots ───────────────────────────────────────────────

class SnapshotImportTests(_Api):
    def test_stock_summary_deletes_items_absent_from_file(self):
        r = self.post("stock-summary", "Item Code,Item Name,Closing Quantity\nBOLT,M8 Bolt,40\n")
        self.assertEqual(r["errors"], [])
        self.assertEqual(db.get_stock_levels(FACTORY), {"BOLT": 40})
        self.assertTrue(any("CASING" in w["warning"] for w in r["warnings"]))

    def test_stock_row_with_error_is_kept_not_deleted(self):
        r = self.post("stock-summary", "Item Code,Item Name,Closing Quantity\nCASING,x,12a\nBOLT,M8 Bolt,40\n")
        self.assertEqual(len(r["errors"]), 1)
        self.assertEqual(db.get_stock_levels(FACTORY), {"CASING": 350, "BOLT": 40})

    def test_header_error_deletes_nothing(self):
        r = self.post("stock-summary", "Foo,Bar\n1,2\n")
        self.assertEqual(r["errors"][0]["line"], 1)
        self.assertEqual(db.get_stock_levels(FACTORY), {"CASING": 350})
        r = self.post("open-purchase-orders", "Foo,Bar\n1,2\n")
        self.assertEqual([s["shipment_id"] for s in db.get_inbound_shipments(FACTORY)], ["SHP-CHN-0001"])

    def test_po_absent_from_file_is_closed(self):
        db.insert_row("inbound_shipments", {"shipment_id": "SHP-OTHER", "factory_id": "other", "item_code": "CASING",
                                            "supplier_id": "SUP-CHN-01", "qty": 1,
                                            "eta": "2099-01-01T00:00:00+00:00", "status": "OPEN"})
        r = self.post("open-purchase-orders", "PO Number,Supplier Code,Item Code,Qty,Due Date\n"
                                              "SHP-NEW-1,SUP-CHN-01,CASING,250,2099-01-01\n")
        self.assertEqual(r["errors"], [])
        self.assertEqual([s["shipment_id"] for s in db.get_inbound_shipments(FACTORY)], ["SHP-NEW-1"])
        self.assertEqual([s["shipment_id"] for s in db.get_inbound_shipments(FACTORY, status="CLOSED")],
                         ["SHP-CHN-0001"])
        self.assertTrue(any("SHP-CHN-0001" in w["warning"] and "CLOSED" in w["warning"] for w in r["warnings"]))
        other = [s for s in db.fetch_all("inbound_shipments") if s["shipment_id"] == "SHP-OTHER"][0]
        self.assertEqual(other["status"], "OPEN")

    def test_received_po_not_double_counted(self):
        """Day 2: the PO arrived, stock shows +500, the PO left the pending export."""
        self.post("stock-summary", "Item Code,Closing Quantity\nCASING,850\n")
        self.post("open-purchase-orders", "PO Number,Supplier Code,Item Code,Qty,Due Date\n")
        r = run_cascade_pipeline("Chennai shipment delayed 2h, order EV-402")
        self.assertEqual(r["shortfall_breakdown"]["inbound_before_deadline"], 0)
        self.assertEqual(r["shortfall_breakdown"]["on_hand"], 850)

    def test_po_row_with_error_is_not_closed(self):
        r = self.post("open-purchase-orders", "PO Number,Supplier Code,Item Code,Qty,Due Date\n"
                                              "SHP-CHN-0001,SUP-CHN-01,CASING,abc,2099-01-01\n")
        self.assertEqual(len(r["errors"]), 1)
        self.assertEqual([s["shipment_id"] for s in db.get_inbound_shipments(FACTORY)], ["SHP-CHN-0001"])

    def test_sales_order_lines_replace_lines_of_orders_in_file(self):
        db.upsert_row("items", {"factory_id": FACTORY, "item_code": "BOLT", "name": "Bolt", "unit": "pcs"},
                      key_columns=("factory_id", "item_code"))
        r = self.post("sales-order-lines", "order_id,item_code,qty\nEV-402,BOLT,5\n")
        self.assertEqual(r["errors"], [])
        lines = {(x["order_id"], x["item_code"]): x["qty"] for x in db.get_order_lines(["EV-402", "EV-405"])}
        self.assertEqual(lines, {("EV-402", "BOLT"): 5, ("EV-405", "CASING"): 300})
        self.assertTrue(any("EV-402" in w["warning"] and "CASING" in w["warning"] for w in r["warnings"]))

    def test_samples_readme_explains_snapshots(self):
        self.assertIn("snapshot", (SAMPLES / "README.md").read_text(encoding="utf-8").lower())


# ─── I2, I3, I4: shortfall rules ─────────────────────────────────────────────

class ShortfallRuleTests(unittest.TestCase):
    def test_risk_accepted_still_reserves(self):
        self.assertEqual(FINISHED_STATUSES, frozenset({"DELIVERED", "CANCELLED"}))
        orders = _orders()
        orders[0]["status"] = "RISK_ACCEPTED"
        self.assertEqual(_sf("EV-405", orders=orders).reserved_for_higher_priority, 500)

    def test_shortfall_capped_at_demand(self):
        b = _sf("EV-405")
        self.assertEqual((b.demand, b.reserved_for_higher_priority, b.shortfall), (300, 500, 300))
        self.assertIn("higher-priority orders take all", b.explanation())

    def test_missing_priority_is_inventory_error(self):
        for value in (None, "absent"):
            with self.subTest(value=value):
                orders = _orders()
                if value == "absent":
                    del orders[1]["priority"]
                else:
                    orders[1]["priority"] = None
                with self.assertRaises(InventoryDataError) as cm:
                    _sf("EV-402", orders=orders)
                self.assertIn("EV-405", str(cm.exception))
                self.assertIn("priority", str(cm.exception))


class ErpCsvPriorityTests(_Api):
    HEAD = "order_id,client,required_qty,sla_penalty_inr,partial_delay_penalty_inr,hours_remaining"

    def test_priority_column_and_documented_default(self):
        r = self.post("erp-csv", self.HEAD + ",priority\nEV-500,Acme,10,100,5,30,5\nEV-501,Acme,10,100,5,30,\n")
        self.assertEqual(r["errors"], [])
        self.assertEqual(db.get_order("EV-500")["priority"], 5)
        self.assertEqual(db.get_order("EV-501")["priority"], 100)

    def test_update_keeps_priority_when_blank(self):
        self.post("erp-csv", "order_id,required_qty,sla_penalty_inr,priority\nEV-402,500,2500000,\n")
        self.assertEqual(db.get_order("EV-402")["priority"], 10)

    def test_inventory_run_after_erp_import_is_not_500(self):
        self.post("erp-csv", self.HEAD + "\nEV-500,Acme,10,100,5,30\n")
        resp = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY)
        self.assertEqual(resp.status_code, 200, resp.text)


# ─── I5: order selection ─────────────────────────────────────────────────────

def _ext(**kw):
    base = dict(delay_hours=48, affected_lines=[], affected_order=None, shortfall_units=None)
    base.update(kw)
    return DisruptionExtraction(**base)


class OrderSelectionUnitTests(unittest.TestCase):
    def setUp(self):
        self.model = load_factory_model()

    def _ranker(self, *pairs):
        return lambda supplier, delay: [SimpleNamespace(order_id=o, shortfall=s) for o, s in pairs]

    def test_picks_highest_ranked_short_order(self):
        r = resolve_disruption(_ext(), self.model, ["EV-402", "EV-405"],
                               order_ranker=self._ranker(("EV-402", 0), ("EV-405", 300)))
        self.assertEqual((r.order_id, r.shortfall_units, r.order_selection), ("EV-405", 300, "inventory"))
        self.assertEqual(r.other_order_shortfalls, ({"order_id": "EV-402", "shortfall": 0},))

    def test_none_short_picks_highest_ranked(self):
        r = resolve_disruption(_ext(), self.model, ["EV-402", "EV-405"],
                               order_ranker=self._ranker(("EV-405", 0), ("EV-402", 0)))
        self.assertEqual((r.order_id, r.shortfall_units), ("EV-405", 0))

    def test_alert_without_any_disruption_is_not_mapped_to_an_order(self):
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(_ext(delay_hours=None), self.model, ["EV-402", "EV-405"],
                               order_ranker=self._ranker(("EV-402", 0)))
        self.assertIn("order not stated", str(cm.exception))

    def test_no_inventory_still_422(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_disruption(_ext(), self.model, ["EV-402", "EV-405"], order_ranker=self._ranker())

    def test_selection_labels(self):
        r = resolve_disruption(_ext(affected_order="EV-402", shortfall_units=5), self.model, ["EV-402", "EV-405"])
        self.assertEqual((r.order_selection, r.other_order_shortfalls), ("stated", ()))
        r = resolve_disruption(_ext(shortfall_units=5), self.model, ["EV-402", "EV-405"],
                               DisruptionOverrides(order_id="EV-405"))
        self.assertEqual(r.order_selection, "override")
        r = resolve_disruption(_ext(delay_hours=None, shortfall_units=5), small_factory(), ["O-1"])
        self.assertEqual(r.order_selection, "only_order")
        self.assertEqual(r.to_dict()["order_selection"], "only_order")


class OrderSelectionApiTests(_Api):
    def test_literal_alert_resolves_to_ev402(self):
        resp = self.client.post("/api/v1/simulate-crisis",
                                json={"raw_message": "Chennai shipment delayed 48h"}, headers=KEY)
        self.assertEqual(resp.status_code, 200, resp.text)
        p = resp.json()["extracted_parameters"]
        self.assertEqual((p["affected_order_id"], p["shortfall_units"], p["shortfall_source"]),
                         ("EV-402", 150, "inventory"))
        self.assertEqual(p["order_selection"], "inventory")
        self.assertEqual(p["other_order_shortfalls"], [{"order_id": "EV-405", "shortfall": 0}])

    def test_stated_order_label_in_api(self):
        resp = self.client.post("/api/v1/simulate-crisis",
                                json={"raw_message": "Chennai shipment delayed 48h, order EV-402"}, headers=KEY)
        p = resp.json()["extracted_parameters"]
        self.assertEqual((p["order_selection"], p["other_order_shortfalls"]), ("stated", []))

    def test_narration_says_order_was_chosen(self):
        r = run_cascade_pipeline("Chennai shipment delayed 48h")
        self.assertEqual(r["order_selection"], "inventory")
        logs = [x for x in db.fetch_all("agent_logs") if x.get("run_id") == r["run_id"]]
        self.assertTrue(any("EV-405 0 short" in str(x) for x in logs))


# ─── I6: absolute due dates ──────────────────────────────────────────────────

class DeadlineTests(_Api):
    def test_helper_uses_due_at_then_legacy_hours(self):
        due = (NOW + timedelta(hours=10)).isoformat()
        self.assertEqual(deadline_hours({"due_at": due, "hours_remaining": 99}, NOW), 10)
        self.assertEqual(deadline_hours({"due_at": None, "hours_remaining": 38}, NOW), 38)
        with self.assertRaises(ValueError):
            deadline_hours({"order_id": "X"}, NOW)

    def test_inventory_uses_due_at(self):
        orders = _orders()
        orders[0]["due_at"] = (NOW + timedelta(hours=10)).isoformat()  # hours_remaining (38) is stale
        b = _sf(ships=[{"shipment_id": "S", "supplier_id": "x", "item_code": "CELL", "qty": 500,
                        "eta": (NOW + timedelta(hours=20)).isoformat(), "status": "OPEN"}], orders=orders)
        self.assertEqual((b.deadline_hours, b.shortfall), (10, 150))

    def test_seed_and_reset_set_due_at(self):
        before = datetime.now(timezone.utc)
        for oid, h in (("EV-402", 38), ("EV-405", 110)):
            o = db.get_order(oid)
            self.assertIsNotNone(o.get("due_at"), oid)
            self.assertAlmostEqual(deadline_hours(o, before), h, delta=0.1)

    def test_hours_remaining_recomputed_on_read(self):
        db.update_rows("orders", "order_id", "EV-402",
                       {"due_at": (datetime.now(timezone.utc) + timedelta(hours=7)).isoformat()})
        self.assertAlmostEqual(db.get_order("EV-402")["hours_remaining"], 7, delta=0.1)
        ev = [o for o in db.get_all_orders() if o["order_id"] == "EV-402"][0]
        self.assertAlmostEqual(ev["hours_remaining"], 7, delta=0.1)

    def test_blast_radius_and_milp_deadline_follow_due_at(self):
        db.update_rows("orders", "order_id", "EV-402",
                       {"due_at": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()})
        r = run_cascade_pipeline("Chennai shipment delayed 48h, order EV-402", override_shortfall_units=100)
        self.assertAlmostEqual(r["blast_radius"]["hours_remaining"], 12, delta=0.1)

    def test_past_due_order_is_422(self):
        db.update_rows("orders", "order_id", "EV-402",
                       {"due_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()})
        resp = self.client.post("/api/v1/simulate-crisis",
                                json={"raw_message": "Chennai shipment delayed 48h, order EV-402"}, headers=KEY)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("EV-402", resp.json()["detail"])

    def test_erp_csv_sets_due_at(self):
        t0 = datetime.now(timezone.utc)
        r = self.post("erp-csv", "order_id,client,required_qty,sla_penalty_inr,partial_delay_penalty_inr,"
                                 "hours_remaining\nEV-500,Acme,10,100,5,30\n")
        self.assertEqual(r["errors"], [])
        self.assertAlmostEqual(deadline_hours(db.get_order("EV-500"), t0), 30, delta=0.1)
        r = self.post("erp-csv", "order_id,client,required_qty,sla_penalty_inr,partial_delay_penalty_inr,"
                                 "due_date\nEV-501,Acme,10,100,5,2099-01-01\n")
        self.assertEqual(r["errors"], [])
        self.assertEqual(db.get_order("EV-501")["due_at"], "2099-01-01T11:30:00+00:00")

    def test_migration_and_schema_have_due_at(self):
        mig = (ROOT / "supabase" / "migrations" / "006_inventory.sql").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ", mig)
        self.assertIn("WHERE due_at IS NULL", mig)
        self.assertIn("due_at", (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8"))


# ─── I7, M3: importer columns ────────────────────────────────────────────────

class ImporterColumnTests(unittest.TestCase):
    def test_po_prefers_pending_quantity(self):
        r = parse_open_purchase_orders(
            "PO Number,Supplier Code,Item Code,Quantity,Pending Quantity,Due Date\n"
            "PO1,S1,A,500,200,2099-01-01\n", FACTORY, {"A"}, {"S1"}, NOW)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.rows[0]["qty"], 200)

    def test_stock_prefers_closing_quantity(self):
        r = parse_stock_summary("Item Code,Quantity,Closing Quantity\nA,9,4\n", FACTORY, {"A"})
        self.assertEqual(r.rows[0]["on_hand_qty"], 4)

    def test_stock_unit_column(self):
        for col in ("Unit", "UOM"):
            with self.subTest(col=col):
                r = parse_stock_summary(f"Item Code,Item Name,{col},Closing Quantity\nB,Bolt,kg,4\n", FACTORY, set())
                self.assertEqual(r.items[0]["unit"], "kg")
        r = parse_stock_summary("Item Code,Item Name,Closing Quantity\nB,Bolt,4\n", FACTORY, set())
        self.assertEqual(r.items[0]["unit"], "pcs")


if __name__ == "__main__":
    unittest.main()
