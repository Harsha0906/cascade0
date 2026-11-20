import json
import unittest
from datetime import datetime, timedelta, timezone

from tests import _offline_env  # noqa: F401
from app.disruption import DisruptionResolutionError
from app.inventory import InventoryDataError, compute_shortfall

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _orders():
    return [
        {"order_id": "EV-402", "hours_remaining": 38, "priority": 10, "status": "AT_RISK"},
        {"order_id": "EV-405", "hours_remaining": 110, "priority": 20, "status": "AT_RISK"},
    ]


def _lines():
    return [
        {"order_id": "EV-402", "item_code": "CELL", "qty": 500},
        {"order_id": "EV-405", "item_code": "CELL", "qty": 300},
    ]


def _ship(eta_h=20, **kw):
    row = {"shipment_id": "S1", "supplier_id": "chennai", "item_code": "CELL", "qty": 500,
           "eta": (NOW + timedelta(hours=eta_h)).isoformat(), "status": "OPEN"}
    row.update(kw)
    return row


def run(order="EV-402", orders=None, lines=None, stock=None, ships=None, **kw):
    return compute_shortfall(
        order, "CELL", orders if orders is not None else _orders(),
        lines if lines is not None else _lines(),
        stock if stock is not None else {"CELL": 350},
        ships if ships is not None else [_ship()], NOW, **kw)


class ShortfallTests(unittest.TestCase):
    def test_demo_delay(self):
        b = run(delayed_supplier_id="chennai", delay_hours=48)
        self.assertEqual(b.shortfall, 150)
        self.assertEqual(
            b.explanation(),
            "500 needed − (350 on hand + 0 inbound before the 38h deadline "
            "− 0 reserved for higher-priority orders) = 150 short")
        self.assertFalse(b.shipments[0].counted)
        self.assertEqual(b.shipments[0].delayed_by_hours, 48)

    def test_no_delay(self):
        b = run()
        self.assertEqual((b.shortfall, b.available), (0, 850))

    def test_small_delay(self):
        self.assertEqual(run(delayed_supplier_id="chennai", delay_hours=6).shortfall, 0)

    def test_other_supplier_not_delayed(self):
        self.assertEqual(run(delayed_supplier_id="other", delay_hours=48).shortfall, 0)

    def test_eta_at_deadline_counts(self):
        self.assertEqual(run(ships=[_ship(eta_h=38)]).shortfall, 0)
        late = _ship(eta="x")
        late["eta"] = (NOW + timedelta(hours=38, minutes=1)).isoformat()
        self.assertEqual(run(ships=[late]).shortfall, 150)

    def test_lower_priority_order_reserved(self):
        b = run(order="EV-405", delayed_supplier_id="chennai", delay_hours=48)
        self.assertEqual(b.reserved_for_higher_priority, 500)
        self.assertEqual(b.available, 350)
        self.assertEqual(b.shortfall, 0)
        self.assertTrue(b.shipments[0].counted)
        self.assertEqual(b.shipments[0].eta_hours, 68)

    def test_equal_priority_earlier_deadline_first(self):
        orders = [dict(o, priority=10) for o in _orders()]
        self.assertEqual(run(order="EV-405", orders=orders).reserved_for_higher_priority, 500)
        self.assertEqual(run(order="EV-402", orders=orders).reserved_for_higher_priority, 0)

    def test_finished_does_not_reserve(self):
        for st in ("DELIVERED", "CANCELLED", "RISK_ACCEPTED"):
            orders = _orders()
            orders[0]["status"] = st
            self.assertEqual(run(order="EV-405", orders=orders).reserved_for_higher_priority, 0)

    def test_missing_line_and_stock(self):
        with self.assertRaises(InventoryDataError) as c:
            run(order="EV-999")
        self.assertIn("EV-999", str(c.exception))
        with self.assertRaises(InventoryDataError) as c:
            run(stock={})
        self.assertIn("CELL", str(c.exception))
        self.assertTrue(issubclass(InventoryDataError, DisruptionResolutionError))

    def test_non_open_ignored(self):
        self.assertEqual(run(ships=[_ship(status="RECEIVED")]).shortfall, 150)

    def test_naive_eta_treated_as_utc(self):
        eta = (NOW + timedelta(hours=20)).replace(tzinfo=None).isoformat()
        self.assertEqual(run(ships=[_ship(eta=eta)]).shipments[0].eta_hours, 20)

    def test_to_dict_json_and_explanation(self):
        b = run(delayed_supplier_id="chennai", delay_hours=48)
        d = b.to_dict()
        json.dumps(d)
        self.assertEqual(d["explanation"], b.explanation())
        self.assertEqual(d["shipments"][0]["shipment_id"], "S1")

    def test_fractional_hours_display(self):
        b = run(orders=[dict(_orders()[0], hours_remaining=38.5), _orders()[1]])
        self.assertIn("38.5h deadline", b.explanation())


if __name__ == "__main__":
    unittest.main()
