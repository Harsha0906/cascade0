import json
import unittest

from tests import _offline_env  # noqa: F401
from tests.factories import small_factory

from app.disruption import (
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
    return {**dict(model.primary_suppliers), **{v.supplier_id: v.name for v in model.vendors}}


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

    def test_fuzzy_name_typo(self):
        self.assertEqual(
            resolve_reference("Chenai Precision", _vendors(self.model), "supplier"), "SUP-CHN-01")

    def test_single_digit_does_not_match(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_reference("2", _lines(self.model), "line")

    def test_order_override_not_in_orders(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_disruption(_ext(), self.model, self.orders, DisruptionOverrides(order_id="EV-999"))

    def test_empty_order_override_is_unset(self):
        r = resolve_disruption(_ext(), self.model, self.orders, DisruptionOverrides(order_id=""))
        self.assertEqual(r.order_id, "EV-402")

    def test_override_line_ids_are_exact_case_sensitive(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_disruption(_ext(), self.model, self.orders,
                               DisruptionOverrides(line_speeds={"line-2": 50}))

    def test_negative_speed_override(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_disruption(_ext(), self.model, self.orders,
                               DisruptionOverrides(line_speeds={"LINE-2": -1}))

    def test_extracted_speed_validated(self):
        e = _ext()
        e.affected_lines[0].speed_pct = 150  # bypasses pydantic bounds (no validate_assignment)
        with self.assertRaises(DisruptionResolutionError):
            resolve_disruption(e, self.model, self.orders)

    def test_negative_delay(self):
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(_ext(delay_hours=-1), self.model, self.orders)
        self.assertIn("delay_hours", str(cm.exception))

    def test_negative_shortfall_but_zero_ok(self):
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(_ext(shortfall_units=-5), self.model, self.orders)
        self.assertIn("shortfall_units", str(cm.exception))
        self.assertEqual(resolve_disruption(_ext(shortfall_units=0), self.model, self.orders).shortfall_units, 0)

    def test_generated_headline_and_json(self):
        r = resolve_disruption(_ext(), self.model, self.orders)
        self.assertEqual(
            r.headline,
            "Chennai Precision Casings Ltd +48h; Robotic Welding Line 2 at 50%; 150 short on #EV-402")
        json.dumps(r.to_dict())

    def test_extraction_headline_wins(self):
        r = resolve_disruption(_ext(crisis_headline="Flood"), self.model, self.orders)
        self.assertEqual(r.headline, "Flood")


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        from app.agents.tools import extract_disruption_entities
        from app.main import SCENARIO_PROMPTS
        self.extract = extract_disruption_entities
        self.prompt1 = SCENARIO_PROMPTS[1]
        self.model = load_factory_model()
        self.orders = ["EV-402", "EV-405"]

    def _resolved(self, text, model=None, orders=None):
        model = model or self.model
        orders = orders or self.orders
        ext, source = self.extract(text, model, orders)
        self.assertEqual(source, "regex-fallback")
        return ext, resolve_disruption(ext, model, orders)

    def test_scenario_1(self):
        ext, r = self._resolved(self.prompt1)
        self.assertEqual(len(ext.affected_lines), 1)
        li = r.line_impacts[0]
        self.assertEqual((li.line_id, li.speed_pct, li.temp_celsius), ("LINE-2", 50, 89.0))
        self.assertEqual(r.supplier_id, "SUP-CHN-01")
        self.assertEqual(r.order_id, "EV-402")
        self.assertEqual(r.delay_hours, 48)
        self.assertEqual(r.shortfall_units, 150)

    def test_short_text(self):
        _, r = self._resolved("Truck breakdown, 120 casings short on EV-402, Line 2 at 60%, 24h delay")
        self.assertEqual([(l.line_id, l.speed_pct) for l in r.line_impacts], [("LINE-2", 60)])
        self.assertEqual((r.shortfall_units, r.delay_hours, r.order_id), (120, 24, "EV-402"))

    def test_two_lines(self):
        _, r = self._resolved("Line 1 at 70% and Line 3 at 40%, 90 units short on EV-405")
        self.assertEqual([(l.line_id, l.speed_pct) for l in r.line_impacts], [("LINE-1", 70), ("LINE-3", 40)])
        self.assertEqual((r.shortfall_units, r.order_id), (90, "EV-405"))

    def test_second_factory(self):
        m = small_factory()
        _, r = self._resolved("L-B at 40%, 80 units short on WO-77, 5h delay from Vendor V1", m, ["WO-77"])
        self.assertEqual([(l.line_id, l.speed_pct) for l in r.line_impacts], [("L-B", 40)])
        self.assertEqual((r.supplier_id, r.order_id, r.delay_hours, r.shortfall_units), ("V1", "WO-77", 5, 80))

    def test_nothing_stated(self):
        ext, _ = self.extract("flood on the highway", self.model, self.orders)
        self.assertIsNone(ext.shortfall_units)
        self.assertIsNone(ext.delay_hours)
        self.assertEqual(ext.affected_lines, [])
        self.assertIsNone(ext.affected_supplier)
        self.assertIsNone(ext.affected_order)
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(ext, self.model, self.orders)
        self.assertIn("shortfall_units not stated", str(cm.exception))


class ExtractionHazardTests(unittest.TestCase):
    def setUp(self):
        from app.agents.tools import extract_disruption_entities
        self.extract = extract_disruption_entities
        self.model = load_factory_model()
        self.orders = ["EV-402", "EV-405"]

    def ext(self, text, model=None, orders=None):
        return self.extract(text, model or self.model, orders or self.orders)[0]

    def speeds(self, e):
        return [(l.line, l.speed_pct) for l in e.affected_lines]

    def test_shortfall_cue_beats_leftmost(self):
        self.assertEqual(self.ext("500 casings delayed, shortfall 150").shortfall_units, 150)
        self.assertEqual(self.ext("3 units of scrap, 150 casings short on EV-402").shortfall_units, 150)

    def test_shortfall_ambiguous_units_is_none(self):
        self.assertIsNone(self.ext("500 casings delayed and 20 units scrapped").shortfall_units)

    def test_shortfall_single_units_number_ok(self):
        self.assertEqual(self.ext("lost 90 units on EV-402").shortfall_units, 90)

    def test_delay_cue_beats_first(self):
        e = self.ext("shipment in 3 hours ... 12 hour delay")
        self.assertEqual(e.delay_hours, 12)

    def test_delay_ambiguous_is_none(self):
        self.assertIsNone(self.ext("truck left 3 hours ago, ETA 12 hours").delay_hours)

    def test_speed_needs_cue(self):
        e = self.ext("Line 2 is down, 50% of the shipment lost, Line 2 at 30%, 10 units short")
        self.assertEqual(self.speeds(e), [("LINE-2", 30)])
        e = self.ext("Line 2 down. Quality up 50%, 10 units short")
        self.assertEqual(self.speeds(e), [("LINE-2", None)])

    def test_speed_conflict_is_none(self):
        e = self.ext("Line 2 at 50%. Line 2 at 30%. 10 units short")
        self.assertEqual(self.speeds(e), [("LINE-2", None)])

    def test_phantom_line_ids(self):
        m = small_factory()
        e = self.ext("la la 80 units short on WO-77", m, ["WO-77"])
        self.assertEqual(e.affected_lines, [])
        e = self.ext("line a bit slow, 80 units short on WO-77", m, ["WO-77"])
        self.assertEqual(e.affected_lines, [])
        e = self.ext("Line A at 40%, 80 units short on WO-77", m, ["WO-77"])
        self.assertEqual(self.speeds(e), [("L-A", 40)])

    def test_supplier_near_delay_cue(self):
        e = self.ext("Hosur Precision Castings on standby; Chennai Precision Casings delayed 20 hours")
        self.assertEqual(e.affected_supplier, "SUP-CHN-01")

    def test_supplier_ambiguous_is_none(self):
        e = self.ext("Chennai Precision Casings and Hosur Precision Castings both mentioned")
        self.assertIsNone(e.affected_supplier)

    def test_presets(self):
        from app.main import SCENARIO_PROMPTS
        exp = {1: (50, 48, 150), 2: (85, 6, 25), 3: (25, 72, 350)}
        for k, (sp, d, sf) in exp.items():
            e = self.ext(SCENARIO_PROMPTS[k])
            self.assertEqual(self.speeds(e), [("LINE-2", sp)], k)
            self.assertEqual((e.delay_hours, e.shortfall_units, e.affected_order), (d, sf, "EV-402"), k)
            if k != 2:
                self.assertEqual(e.affected_supplier, "SUP-CHN-01", k)


if __name__ == "__main__":
    unittest.main()
