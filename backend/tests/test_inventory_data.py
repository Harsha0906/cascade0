"""Phase 4 Task 1: inventory tables, seeds, db helpers and the factory model's stock item code."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede any app import)
from tests._offline_env import DEV_HEADERS, dev_client  # noqa: F401


from app import db
from app.factory_model import FactoryDataError, FactoryModel, load_factory_model
from tests.factories import seed_second_factory, small_factory


def _parse(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


class InventoryHelperTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()

    def tearDown(self):
        db.reset_to_seed()

    def test_items(self):
        items = db.get_items("apex-volt-blr2")
        self.assertEqual([(i["item_code"], i["name"], i["unit"]) for i in items],
                         [("CASING", "Aluminium Battery Casing", "pcs")])

    def test_stock_levels(self):
        self.assertEqual(db.get_stock_levels("apex-volt-blr2"), {"CASING": 350})

    def test_open_shipment_seed(self):
        ships = db.get_inbound_shipments("apex-volt-blr2")
        self.assertEqual(len(ships), 1)
        s = ships[0]
        self.assertEqual((s["shipment_id"], s["supplier_id"], s["item_code"], s["qty"], s["status"]),
                         ("SHP-CHN-0001", "SUP-CHN-01", "CASING", 500, "OPEN"))
        expected = datetime.now(timezone.utc) + timedelta(hours=20)
        self.assertLess(abs(_parse(s["eta"]) - expected), timedelta(minutes=1))

    def test_shipment_status_filter(self):
        self.assertEqual(db.get_inbound_shipments("apex-volt-blr2", status="RECEIVED"), [])

    def test_reset_resets_shipment_eta(self):
        db._mirror.inbound_shipments[0]["eta"] = "2000-01-01T00:00:00+00:00"
        db.reset_to_seed()
        eta = _parse(db.get_inbound_shipments("apex-volt-blr2")[0]["eta"])
        self.assertLess(abs(eta - (datetime.now(timezone.utc) + timedelta(hours=20))), timedelta(minutes=1))

    def test_order_lines_and_priorities(self):
        lines = db.get_order_lines(["EV-402", "EV-405"])
        self.assertEqual(sorted((l["order_id"], l["item_code"], l["qty"]) for l in lines),
                         [("EV-402", "CASING", 500), ("EV-405", "CASING", 300)])
        self.assertEqual(db.get_order_lines(["EV-405"])[0]["qty"], 300)
        self.assertEqual(db.get_order_lines([]), [])
        prio = {o["order_id"]: o["priority"] for o in db.get_all_orders()}
        self.assertEqual(prio, {"EV-402": 10, "EV-405": 20})

    def test_scenario_one_shortfall_is_null(self):
        by_id = {s["scenario_id"]: s for s in db.get_scenarios("apex-volt-blr2")}
        self.assertIsNone(by_id[1]["shortfall_units"])
        self.assertEqual((by_id[2]["shortfall_units"], by_id[3]["shortfall_units"]), (25, 350))

    def test_second_factory_inventory(self):
        seed_second_factory()
        self.assertEqual(db.get_stock_levels("test-plant"), {"ITEM-W": 40})
        self.assertEqual(db.get_inbound_shipments("test-plant"), [])
        self.assertEqual([i["name"] for i in db.get_items("test-plant")], ["Widget"])
        self.assertEqual(db.get_order_lines(["WO-77"])[0]["qty"], 80)
        self.assertEqual(db.get_stock_levels("apex-volt-blr2"), {"CASING": 350})

    def test_helpers_fail_loud_when_live_query_errors(self):
        from tests.fake_supabase import FailingClient
        with mock.patch("app.db._get_supabase", return_value=FailingClient()):
            for call in (lambda: db.get_items("f"), lambda: db.get_stock_levels("f"),
                         lambda: db.get_inbound_shipments("f"), lambda: db.get_order_lines(["A"])):
                with self.assertRaises(db.DatabaseError):
                    call()


class StockItemCodeTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()

    def tearDown(self):
        db.reset_to_seed()

    def test_loader_reads_code(self):
        self.assertEqual(load_factory_model().stock_item_code, "CASING")

    def test_missing_code_names_the_column(self):
        db.update_rows("factories", "id", "apex-volt-blr2", {"stock_item_code": None})
        with self.assertRaises(FactoryDataError) as cm:
            load_factory_model()
        self.assertIn("factories.stock_item_code", str(cm.exception))

    def test_absent_column_names_the_column(self):
        for row in db._mirror.factories:
            row.pop("stock_item_code", None)
        with self.assertRaises(FactoryDataError) as cm:
            load_factory_model()
        self.assertIn("factories.stock_item_code", str(cm.exception))

    def test_roundtrip_and_old_payload(self):
        m = load_factory_model()
        self.assertEqual(FactoryModel.from_dict(m.to_dict()), m)
        old = m.to_dict()
        del old["stock_item_code"]
        self.assertEqual(FactoryModel.from_dict(old).stock_item_code, "")

    def test_small_factory_has_code(self):
        self.assertEqual(small_factory().stock_item_code, "ITEM-W")


class HealthzLevelTests(unittest.TestCase):
    def test_required_level_is_eight(self):
        from app.main import app
        r = dev_client(app).get("/healthz")
        self.assertEqual(r.json()["required_migration_level"], 8)
        self.assertEqual(db.REQUIRED_MIGRATION_LEVEL, 8)


if __name__ == "__main__":
    unittest.main()
