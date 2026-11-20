"""Phase 4 Task 3: Tally/Excel CSV parsers, composite-key upsert and the import endpoints."""

import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede any app import)

from fastapi.testclient import TestClient

from app import db
from app.importers import (
    parse_open_purchase_orders,
    parse_sales_order_lines,
    parse_stock_summary,
)
from app.main import app

SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "tally"
KEY = {"X-API-Key": "test-operator-key"}
FACTORY = "apex-volt-blr2"
TODAY = date(2026, 11, 20)


def _sample(name):
    return (SAMPLES / name).read_text(encoding="utf-8")


class SampleFileTests(unittest.TestCase):
    def test_stock_sample(self):
        r = parse_stock_summary(_sample("stock_summary.csv"), FACTORY, {"CASING"})
        self.assertEqual(r.errors, [])
        self.assertEqual(r.rows, [{"factory_id": FACTORY, "item_code": "CASING", "on_hand_qty": 350}])
        self.assertEqual(r.items, [])

    def test_stock_creates_new_item_with_name(self):
        r = parse_stock_summary('Item Code,Item Name,Closing Quantity\nBOLT,M8 Bolt,"1,200 Nos"\n',
                                FACTORY, {"CASING"})
        self.assertEqual(r.errors, [])
        self.assertEqual(r.items, [{"factory_id": FACTORY, "item_code": "BOLT", "name": "M8 Bolt", "unit": "pcs"}])
        self.assertEqual(r.rows[0]["on_hand_qty"], 1200)

    def test_po_sample(self):
        r = parse_open_purchase_orders(_sample("open_purchase_orders.csv"), FACTORY,
                                       {"CASING"}, {"SUP-CHN-01"}, TODAY)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.rows, [{
            "shipment_id": "SHP-CHN-0001", "factory_id": FACTORY, "item_code": "CASING",
            "supplier_id": "SUP-CHN-01", "qty": 500, "eta": "2026-11-21T11:30:00+00:00", "status": "OPEN",
        }])

    def test_lines_sample(self):
        r = parse_sales_order_lines(_sample("sales_order_lines.csv"), {"EV-402", "EV-405"}, {"CASING"})
        self.assertEqual(r.errors, [])
        self.assertEqual(r.rows, [{"order_id": "EV-402", "item_code": "CASING", "qty": 500},
                                  {"order_id": "EV-405", "item_code": "CASING", "qty": 300}])


class ValueTests(unittest.TestCase):
    def _qty(self, raw):
        text = f'item_code,on_hand_qty\nCASING,"{raw}"\n'
        return parse_stock_summary(text, FACTORY, {"CASING"})

    def test_quantity_formats(self):
        for raw, want in [("1,200 Nos", 1200), ("1,20,000", 120000), ("500 pcs", 500), ("0", 0), ("7", 7)]:
            with self.subTest(raw=raw):
                r = self._qty(raw)
                self.assertEqual(r.errors, [])
                self.assertEqual(r.rows[0]["on_hand_qty"], want)

    def test_bad_quantities(self):
        for raw in ["12a", "-5", "", "1.5", "5 pcs extra", "1,2"]:
            with self.subTest(raw=raw):
                r = self._qty(raw)
                self.assertEqual(r.rows, [])
                self.assertEqual(r.errors[0]["line"], 2)

    def test_zero_decimals_accepted_real_fractions_rejected(self):
        for raw, want in [("500.00", 500), ("1,200.000 Nos", 1200), ("7.0", 7)]:
            with self.subTest(raw=raw):
                r = self._qty(raw)
                self.assertEqual((r.errors, r.rows[0]["on_hand_qty"]), ([], want))
        for raw in ["12.5", "500.01", "1.", ".5"]:
            with self.subTest(raw=raw):
                self.assertEqual(self._qty(raw).errors[0]["line"], 2)

    def test_dates(self):
        cases = {
            "20-Nov-2026": "2026-11-20T11:30:00+00:00",
            "2026-11-20": "2026-11-20T11:30:00+00:00",
            "20-11-2026": "2026-11-20T11:30:00+00:00",
            "20/11/2026": "2026-11-20T11:30:00+00:00",
            "20-Nov-2026 09:00": "2026-11-20T03:30:00+00:00",
            "21/11/2026 02:00": "2026-11-20T20:30:00+00:00",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                text = f'PO Number,Supplier Code,Item Code,Qty,Due Date\nP1,S1,CASING,5,{raw}\n'
                r = parse_open_purchase_orders(text, FACTORY, {"CASING"}, {"S1"}, TODAY)
                self.assertEqual(r.errors, [])
                self.assertEqual(r.rows[0]["eta"], want)

    def test_headers_case_insensitive_and_aliases(self):
        text = "STOCK ITEM CODE,name of item,quantity\nCASING,x,5\n"
        r = parse_stock_summary(text, FACTORY, {"CASING"})
        self.assertEqual((r.errors, r.rows[0]["on_hand_qty"]), ([], 5))

    def test_missing_column_is_a_header_error(self):
        r = parse_stock_summary("item_code\nCASING\n", FACTORY, {"CASING"})
        self.assertEqual(r.rows, [])
        self.assertEqual(r.errors[0]["line"], 1)


class MixedFileTests(unittest.TestCase):
    def test_po_mixed(self):
        text = "\n".join([
            "PO Number,Supplier Code,Item Code,Pending Quantity,Due Date",
            "P1,S1,CASING,100,25-Nov-2026",       # 2 good
            "P2,S1,CASING,12a,25-Nov-2026",       # 3 bad qty
            "P3,S1,CASING,-5,25-Nov-2026",        # 4 negative
            "P4,S1,CASING,,25-Nov-2026",          # 5 empty qty
            "P5,S1,CASING,10,31-02-2026",         # 6 bad date
            "P6,S1,NOPE,10,25-Nov-2026",          # 7 unknown item
            "P7,NOSUP,CASING,10,25-Nov-2026",     # 8 unknown supplier
            "P1,S1,CASING,10,25-Nov-2026",        # 9 duplicate id
            "P8,S1,CASING,10,19-Nov-2026",        # 10 overdue (warning, imported)
            "P9,S1,CASING,20,26-Nov-2026",        # 11 good
        ]) + "\n"
        r = parse_open_purchase_orders(text, FACTORY, {"CASING"}, {"S1"}, TODAY)
        self.assertEqual([x["shipment_id"] for x in r.rows], ["P1", "P8", "P9"])
        by_line = {e["line"]: e["error"] for e in r.errors}
        self.assertEqual(sorted(by_line), [3, 4, 5, 6, 7, 8, 9])
        self.assertIn("quantity", by_line[3])
        self.assertIn("quantity", by_line[4])
        self.assertIn("empty", by_line[5])
        self.assertIn("date", by_line[6])
        self.assertIn("unknown item", by_line[7])
        self.assertIn("unknown supplier", by_line[8])
        self.assertIn("duplicate", by_line[9])
        self.assertEqual(r.warnings, [{"line": 10, "warning": "PO P8 overdue since 2026-11-19"}])

    def test_lines_mixed(self):
        text = "\n".join([
            "order_id,item_code,qty",
            "EV-402,CASING,5",
            "EV-999,CASING,5",
            "EV-402,NOPE,5",
            "EV-402,CASING,6",
            "EV-405,CASING,0",
        ]) + "\n"
        r = parse_sales_order_lines(text, {"EV-402", "EV-405"}, {"CASING"})
        self.assertEqual(len(r.rows), 1)
        self.assertEqual([e["line"] for e in r.errors], [3, 4, 5, 6])
        self.assertIn("unknown order", r.errors[0]["error"])
        self.assertIn("unknown item", r.errors[1]["error"])
        self.assertIn("duplicate", r.errors[2]["error"])

    def test_stock_total_rows_skipped_with_warning(self):
        text = ("Item Code,Item Name,Closing Quantity\n"
                "CASING,Aluminium Battery Casing,350\n"
                "Grand Total,Total,5000\n"
                ",Total,5000\n"
                "TOTAL,,5000\n")
        r = parse_stock_summary(text, FACTORY, {"CASING"})
        self.assertEqual(r.errors, [])
        self.assertEqual([x["item_code"] for x in r.rows], ["CASING"])
        self.assertEqual([w["line"] for w in r.warnings], [3, 4, 5])
        self.assertIn("total", r.warnings[0]["warning"])
        self.assertEqual(r.items, [])

    def test_po_reimport_keeps_non_open_status_and_rejects_foreign(self):
        existing = {"P1": {"factory_id": FACTORY, "status": "RECEIVED"},
                    "P2": {"factory_id": FACTORY, "status": "OPEN"},
                    "P3": {"factory_id": "other-factory", "status": "OPEN"}}
        text = ("PO Number,Supplier Code,Item Code,Qty,Due Date\n"
                "P1,S1,CASING,5,25-Nov-2026\nP2,S1,CASING,5,25-Nov-2026\n"
                "P3,S1,CASING,5,25-Nov-2026\nP4,S1,CASING,5,25-Nov-2026\n")
        r = parse_open_purchase_orders(text, FACTORY, {"CASING"}, {"S1"}, TODAY,
                                       existing_shipments=existing)
        self.assertEqual({x["shipment_id"]: x["status"] for x in r.rows},
                         {"P1": "RECEIVED", "P2": "OPEN", "P4": "OPEN"})
        self.assertEqual([(e["line"]) for e in r.errors], [4])
        self.assertIn("another factory", r.errors[0]["error"])
        self.assertEqual([w["line"] for w in r.warnings], [2])
        self.assertIn("RECEIVED", r.warnings[0]["warning"])

    def test_stock_mixed(self):
        text = "item_code,item_name,on_hand_qty\nCASING,x,5\nCASING,x,6\nNEW,,3\n"
        r = parse_stock_summary(text, FACTORY, {"CASING"})
        self.assertEqual(len(r.rows), 1)
        self.assertEqual([e["line"] for e in r.errors], [3, 4])
        self.assertIn("duplicate", r.errors[0]["error"])
        self.assertIn("unknown item", r.errors[1]["error"])


class CompositeUpsertTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()

    def tearDown(self):
        db.reset_to_seed()

    def test_offline_composite_key(self):
        db.upsert_row("stock_levels", {"factory_id": "other", "item_code": "CASING", "on_hand_qty": 9},
                      key_columns=("factory_id", "item_code"))
        db.upsert_row("stock_levels", {"factory_id": FACTORY, "item_code": "CASING", "on_hand_qty": 1},
                      key_columns=("factory_id", "item_code"))
        self.assertEqual(db.get_stock_levels(FACTORY), {"CASING": 1})
        self.assertEqual(db.get_stock_levels("other"), {"CASING": 9})

    def test_supabase_mode_passes_on_conflict(self):
        client = mock.MagicMock()
        client.table.return_value.upsert.return_value.execute.return_value.data = [{"a": 1}]
        with mock.patch.object(db, "_get_supabase", return_value=client):
            db.upsert_row("stock_levels", {"factory_id": "f", "item_code": "i"},
                          key_columns=("factory_id", "item_code"))
        client.table.return_value.upsert.assert_called_once_with(
            {"factory_id": "f", "item_code": "i"}, on_conflict="factory_id,item_code")


class EndpointTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        self.client = TestClient(app)

    def tearDown(self):
        db.reset_to_seed()

    def _post(self, path, text, headers=KEY):
        return self.client.post(f"/api/v1/ingest/{path}", json={"filename": "f.csv", "csv_content": text},
                                headers=headers)

    def test_api_key_required(self):
        for path in ("stock-summary", "open-purchase-orders", "sales-order-lines"):
            with self.subTest(path=path):
                self.assertEqual(self._post(path, "a\nb", headers={}).status_code, 401)

    def test_empty_body_is_400(self):
        self.assertEqual(self._post("stock-summary", "  ").status_code, 400)

    def test_stock_import_reflected(self):
        r = self._post("stock-summary", 'Item Code,Item Name,Closing Quantity\nCASING,x,"1,000 pcs"\nBOLT,M8 Bolt,40\n')
        self.assertEqual(r.json(), {"success": True, "filename": "f.csv", "imported_count": 2, "errors": [], "warnings": []})
        self.assertEqual(db.get_stock_levels(FACTORY), {"CASING": 1000, "BOLT": 40})
        self.assertIn("BOLT", [i["item_code"] for i in db.get_items(FACTORY)])
        self.assertEqual(len([i for i in db.get_items(FACTORY) if i["item_code"] == "CASING"]), 1)

    def test_stock_partial_success(self):
        r = self._post("stock-summary", "item_code,qty\nCASING,12a\nCASING,5\n").json()
        self.assertFalse(r["success"])
        self.assertEqual((r["imported_count"], r["errors"][0]["line"]), (1, 2))
        self.assertEqual(db.get_stock_levels(FACTORY), {"CASING": 5})

    def test_purchase_orders_import(self):
        csv_text = ("PO Number,Supplier Code,Item Code,Qty,Due Date\n"
                    "SHP-NEW-1,SUP-CHN-01,CASING,250,2099-01-01\n"
                    "SHP-NEW-2,NOBODY,CASING,250,2099-01-01\n")
        r = self._post("open-purchase-orders", csv_text).json()
        self.assertEqual((r["success"], r["imported_count"], len(r["errors"])), (False, 1, 1))
        ids = [s["shipment_id"] for s in db.get_inbound_shipments(FACTORY)]
        self.assertIn("SHP-NEW-1", ids)
        self.assertNotIn("SHP-NEW-2", ids)

    def test_overdue_po_imported_with_warning_and_all_endpoints_have_warnings(self):
        csv_text = ("PO Number,Supplier Code,Item Code,Qty,Due Date\n"
                    "SHP-OLD-1,SUP-CHN-01,CASING,250,2000-01-01\n")
        r = self._post("open-purchase-orders", csv_text).json()
        self.assertEqual((r["success"], r["imported_count"], r["errors"]), (True, 1, []))
        self.assertEqual(r["warnings"][0]["line"], 2)
        self.assertIn("SHP-OLD-1", r["warnings"][0]["warning"])
        self.assertIn("SHP-OLD-1", [s["shipment_id"] for s in db.get_inbound_shipments(FACTORY)])
        self.assertEqual(self._post("stock-summary", "item_code,qty\nCASING,5\n").json()["warnings"], [])
        self.assertEqual(self._post("sales-order-lines",
                                    "order_id,item_code,qty\nEV-402,CASING,5\n").json()["warnings"], [])

    def test_stock_endpoint_skips_total_row(self):
        r = self._post("stock-summary", "Item Code,Item Name,Qty\nCASING,x,5\nGrand Total,Total,5\n").json()
        self.assertEqual((r["success"], r["imported_count"], len(r["warnings"])), (True, 1, 1))

    def test_po_reimport_does_not_reopen_received(self):
        db.update_rows("inbound_shipments", "shipment_id", "SHP-CHN-0001", {"status": "RECEIVED"})
        csv_text = "PO Number,Supplier Code,Item Code,Qty,Due Date\nSHP-CHN-0001,SUP-CHN-01,CASING,500,2099-01-01\n"
        r = self._post("open-purchase-orders", csv_text).json()
        self.assertEqual((r["imported_count"], len(r["warnings"])), (1, 1))
        self.assertEqual(db.get_inbound_shipments(FACTORY, status="RECEIVED")[0]["shipment_id"], "SHP-CHN-0001")
        self.assertEqual(db.get_inbound_shipments(FACTORY), [])

    def test_po_id_of_other_factory_is_error(self):
        db.insert_row("inbound_shipments", {"shipment_id": "SHP-X", "factory_id": "other", "item_code": "CASING",
                                            "supplier_id": "SUP-CHN-01", "qty": 1, "eta": "2099-01-01T00:00:00+00:00",
                                            "status": "OPEN"})
        csv_text = "PO Number,Supplier Code,Item Code,Qty,Due Date\nSHP-X,SUP-CHN-01,CASING,5,2099-01-01\n"
        r = self._post("open-purchase-orders", csv_text).json()
        self.assertEqual((r["imported_count"], len(r["errors"])), (0, 1))
        self.assertEqual([s for s in db.fetch_all("inbound_shipments") if s["shipment_id"] == "SHP-X"][0]["qty"], 1)

    def test_sales_order_lines_import(self):
        r = self._post("sales-order-lines", "order_id,item_code,qty\nEV-402,CASING,450\n").json()
        self.assertTrue(r["success"])
        lines = {(x["order_id"], x["item_code"]): x["qty"] for x in db.get_order_lines(["EV-402"])}
        self.assertEqual(lines, {("EV-402", "CASING"): 450})

    def test_sales_lines_unknown_order_is_error(self):
        r = self._post("sales-order-lines", "order_id,item_code,qty\nNOPE,CASING,1\n").json()
        self.assertEqual((r["success"], r["imported_count"]), (False, 0))


class ErpCsvHardeningTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        self.client = TestClient(app)

    def tearDown(self):
        db.reset_to_seed()

    def _post(self, text):
        return self.client.post("/api/v1/ingest/erp-csv", json={"filename": "o.csv", "csv_content": text},
                                headers=KEY).json()

    def test_missing_numeric_column_is_row_error(self):
        data = self._post("order_id,client,required_qty,partial_delay_penalty_inr,hours_remaining\n"
                          "NEW-9,Acme,10,5,30\n")
        self.assertEqual(data["orders"], [])
        self.assertEqual(data["errors"][0]["line"], 2)
        self.assertIn("sla_penalty_inr", data["errors"][0]["error"])
        self.assertIsNone(db.get_order("NEW-9"))

    def test_new_order_gets_factory_id(self):
        data = self._post("order_id,client,required_qty,sla_penalty_inr,partial_delay_penalty_inr,hours_remaining\n"
                          "NEW-9,Acme,10,100,5,30\n")
        self.assertEqual(data["errors"], [])
        order = db.get_order("NEW-9")
        self.assertEqual((order["factory_id"], order["status"], order["shortfall_units"]),
                         (FACTORY, "ON_TRACK", 0))

    def test_update_preserves_status_and_shortfall(self):
        db.update_rows("orders", "order_id", "EV-402", {"status": "AT_RISK", "shortfall_units": 150})
        data = self._post("order_id,client,required_qty,sla_penalty_inr\nEV-402,Ather,600,2500000\n")
        self.assertEqual(data["errors"], [])
        order = db.get_order("EV-402")
        self.assertEqual((order["status"], order["shortfall_units"], order["required_qty"]),
                         ("AT_RISK", 150, 600))
        self.assertEqual(order["factory_id"], FACTORY)

    def test_update_preserves_client_and_label_when_blank(self):
        before = db.get_order("EV-402")
        data = self._post("order_id,client,required_qty,sla_penalty_inr,deadline_label\nEV-402,,600,2500000,\n")
        self.assertEqual(data["errors"], [])
        after = db.get_order("EV-402")
        self.assertEqual((after["client"], after["deadline_label"]), (before["client"], before["deadline_label"]))
        self.assertEqual(after["required_qty"], 600)

    def test_bom_and_header_normalisation(self):
        data = self._post("\ufeff Order_ID ,CLIENT, Required_Qty,SLA_Penalty_INR\nEV-402,Ather,601,2500000\n")
        self.assertEqual((data["errors"], data["orders"]), ([], ["EV-402"]))
        self.assertEqual(db.get_order("EV-402")["required_qty"], 601)


if __name__ == "__main__":
    unittest.main()
