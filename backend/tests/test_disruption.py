import unittest

from tests import _offline_env  # noqa: F401
from tests.factories import small_factory

from app.disruption import (
    _primary_suppliers,
    DisruptionOverrides,
    DisruptionResolutionError,
    resolve_disruption,
    resolve_reference,
)
from app.factory_model import load_factory_model
from app.schemas import DisruptionExtraction, LineImpactExtraction
from app.solver import SolverInputError


def _lines(model):
    return {l.line_id: l.name for l in model.lines}


def _vendors(model):
    return {**_primary_suppliers(model), **{v.supplier_id: v.name for v in model.vendors}}


def _ext(**kw):
    base = dict(
        delay_hours=48,
        affected_lines=[LineImpactExtraction(line="Line 2", speed_pct=50)],
        affected_order="ev-402",
        shortfall_units=150,
    )
    base.update(kw)
    return DisruptionExtraction(**base)


class ResolveReferenceTests(unittest.TestCase):
    def setUp(self):
        self.model = load_factory_model()

    def test_line_short_name(self):
        self.assertEqual(resolve_reference("Line 2", _lines(self.model), "line"), "LINE-2")

    def test_line_partial_name(self):
        self.assertEqual(resolve_reference("Welding Line 2", _lines(self.model), "line"), "LINE-2")

    def test_ambiguous(self):
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_reference("Welding Line", _lines(self.model), "line")
        msg = str(cm.exception)
        self.assertIn("Ambiguous", msg)
        for lid in ("LINE-1", "LINE-2", "LINE-3"):
            self.assertIn(lid, msg)

    def test_unknown(self):
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_reference("Line 9", _lines(self.model), "line")
        self.assertIn("Unknown", str(cm.exception))
        self.assertIn("LINE-1", str(cm.exception))

    def test_vendor_stem(self):
        self.assertEqual(
            resolve_reference("Chennai Precision", _vendors(self.model), "supplier"), "SUP-CHN-01")

    def test_order_case_insensitive(self):
        self.assertEqual(
            resolve_reference("ev-402", {"EV-402": "EV-402", "EV-405": "EV-405"}, "order"), "EV-402")

    def test_is_solver_input_error(self):
        self.assertTrue(issubclass(DisruptionResolutionError, SolverInputError))


class ResolveDisruptionTests(unittest.TestCase):
    def setUp(self):
        self.model = load_factory_model()
        self.orders = ["EV-402", "EV-405"]

    def test_full_resolution(self):
        r = resolve_disruption(_ext(affected_supplier="Chennai Precision"), self.model, self.orders)
        self.assertEqual(r.delay_hours, 48)
        self.assertEqual(r.supplier_id, "SUP-CHN-01")
        self.assertEqual(r.order_id, "EV-402")
        self.assertEqual(r.line_speeds, {"LINE-2": 50})
        self.assertEqual(r.shortfall_units, 150)
        self.assertTrue(r.headline)
        self.assertEqual(r.to_dict()["line_impacts"][0]["line_id"], "LINE-2")

    def test_overrides_beat_extraction(self):
        ov = DisruptionOverrides(delay_hours=12, shortfall_units=99,
                                 line_speeds={"LINE-3": 20}, order_id="EV-405")
        r = resolve_disruption(_ext(), self.model, self.orders, ov)
        self.assertEqual(r.delay_hours, 12)
        self.assertEqual(r.shortfall_units, 99)
        self.assertEqual(r.line_speeds, {"LINE-3": 20})
        self.assertEqual(r.order_id, "EV-405")

    def test_missing_shortfall(self):
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(_ext(shortfall_units=None), self.model, self.orders)
        self.assertIn("shortfall_units not stated", str(cm.exception))

    def test_line_without_speed(self):
        e = _ext(affected_lines=[LineImpactExtraction(line="Line 2")])
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(e, self.model, self.orders)
        self.assertIn("speed for line LINE-2 not stated", str(cm.exception))

    def test_line_named_twice(self):
        e = _ext(affected_lines=[LineImpactExtraction(line="Line 2", speed_pct=50),
                                 LineImpactExtraction(line="LINE-2", speed_pct=40)])
        with self.assertRaises(DisruptionResolutionError):
            resolve_disruption(e, self.model, self.orders)

    def test_delay_defaults_primary_supplier(self):
        r = resolve_disruption(_ext(), self.model, self.orders)
        self.assertEqual(r.supplier_id, "SUP-CHN-01")

    def test_no_delay_no_supplier(self):
        r = resolve_disruption(_ext(delay_hours=None), self.model, self.orders)
        self.assertEqual(r.delay_hours, 0)
        self.assertIsNone(r.supplier_id)

    def test_no_primary_raises(self):
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(_ext(affected_lines=[LineImpactExtraction(line="Line A", speed_pct=50)],
                                    affected_order=None),
                               small_factory(), ["O-1"])
        self.assertIn("name the delayed supplier", str(cm.exception))

    def test_single_order_default(self):
        r = resolve_disruption(_ext(affected_order=None, delay_hours=None),
                               small_factory(), ["O-1"],
                               DisruptionOverrides(line_speeds={"L-A": 50}))
        self.assertEqual(r.order_id, "O-1")

    def test_override_unknown_line(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_disruption(_ext(), self.model, self.orders,
                               DisruptionOverrides(line_speeds={"LINE-9": 50}))

    def test_speed_101(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_disruption(_ext(), self.model, self.orders,
                               DisruptionOverrides(line_speeds={"LINE-2": 101}))

    def test_two_orders_none_named(self):
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(_ext(affected_order=None), self.model, self.orders)
        self.assertIn("EV-402", str(cm.exception))
        self.assertIn("EV-405", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
