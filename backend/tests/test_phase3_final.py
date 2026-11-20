"""Phase 3 final fix wave: id-shaped references, slider-only runs, number parsing, delays,
override temperatures, PLC schema, Gemini grounding and lowercase single-letter lines."""

import copy
import json
import unittest
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests.factories import small_factory

from fastapi.testclient import TestClient

from app import db, main
from app.disruption import (
    DisruptionOverrides,
    DisruptionResolutionError,
    resolve_disruption,
    resolve_reference,
)
from app.factory_model import load_factory_model
from app.schemas import DisruptionExtraction, LineImpactExtraction

KEY = {"X-API-Key": "test-operator-key"}
ORDERS = ["EV-402", "EV-405"]


def _extract(text, model=None, orders=None):
    from app.agents.tools import extract_disruption_entities
    return extract_disruption_entities(text, model or load_factory_model(), orders or ORDERS)


# ── C1 ─────────────────────────────────────────────────────────────────────

class IdShapedReferenceTests(unittest.TestCase):
    def test_line_10_is_not_line_1(self):
        cands = {"L-1": "Line 1", "L-2": "Line 2", "L-3": "Line 3"}
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_reference("Line 10", cands, "line")
        self.assertIn("Unknown", str(cm.exception))

    def test_line_10_against_model_lines(self):
        lines = {l.line_id: l.name for l in load_factory_model().lines}
        with self.assertRaises(DisruptionResolutionError):
            resolve_reference("Line 10", lines, "line")

    def test_order_with_extra_digit(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_reference("EV-4021", {o: o for o in ORDERS}, "order")

    def test_order_with_missing_digit(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_reference("WO-7", {"WO-77": "WO-77"}, "order")

    def test_order_with_suffix_letter(self):
        with self.assertRaises(DisruptionResolutionError):
            resolve_reference("EV-402A", {o: o for o in ORDERS}, "order")
        self.assertEqual(resolve_reference("ev 402", {o: o for o in ORDERS}, "order"), "EV-402")

    def test_partial_name_with_same_digits_ok(self):
        lines = {l.line_id: l.name for l in load_factory_model().lines}
        self.assertEqual(resolve_reference("Welding Line 2", lines, "line"), "LINE-2")

    def test_regex_path_unknown_order_writes_nothing(self):
        from app.agents.graph import run_cascade_pipeline
        db.reset_to_seed()
        try:
            before = copy.deepcopy([db.get_all_suppliers(), db.get_all_production_lines(), db.get_all_orders()])
            text = "Chennai Precision delayed 24h, Line 2 at 50%, 150 short on order EV-4021"
            with self.assertRaises(DisruptionResolutionError) as cm:
                run_cascade_pipeline(text)
            self.assertIn("EV-4021", str(cm.exception))
            after = [db.get_all_suppliers(), db.get_all_production_lines(), db.get_all_orders()]
            self.assertEqual(after, before)
        finally:
            db.reset_to_seed()


# ── I2 / I3 / M4: regex extraction ─────────────────────────────────────────

class NumberParsingTests(unittest.TestCase):
    def test_thousands_shortfall_of(self):
        e, _ = _extract("shortfall of 1,200 units on EV-402, Line 2 at 50%")
        self.assertEqual(e.shortfall_units, 1200)

    def test_thousands_units_short(self):
        e, _ = _extract("1,200 units short")
        self.assertEqual(e.shortfall_units, 1200)

    def test_indian_grouping(self):
        e, _ = _extract("Line 2 at 50%, 1,20,000 units short on EV-402, 24h delay")
        self.assertEqual(e.shortfall_units, 120000)

    def test_thousands_delay(self):
        e, _ = _extract("1,000 hours delay, 10 units short")
        self.assertEqual(e.delay_hours, 1000)


class DelayDaysTests(unittest.TestCase):
    def test_delay_two_days(self):
        e, _ = _extract("Line 2 at 50%, 100 short for EV-402, delay 2 days")
        self.assertEqual(e.delay_hours, 48)

    def test_late_by_one_day(self):
        e, _ = _extract("Line 2 at 50%, 100 short for EV-402, chennai shipment late by 1 day")
        self.assertEqual(e.delay_hours, 24)

    def test_delay_mentioned_without_hours_raises(self):
        text = "Chennai shipment delayed, Line 2 at 50%, 100 units short on EV-402"
        e, _ = _extract(text)
        self.assertIsNone(e.delay_hours)
        self.assertTrue(e.delay_mentioned)
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(e, load_factory_model(), ORDERS)
        self.assertIn("delay_hours not stated", str(cm.exception))

    def test_delay_mentioned_override_supplies_delay(self):
        e = DisruptionExtraction(shortfall_units=10, affected_order="EV-402", delay_mentioned=True)
        r = resolve_disruption(e, load_factory_model(), ORDERS, DisruptionOverrides(delay_hours=12))
        self.assertEqual(r.delay_hours, 12)

    def test_no_delay_cue_still_zero(self):
        e, _ = _extract("Line 2 at 50%, 100 units short on EV-402")
        self.assertFalse(e.delay_mentioned)
        r = resolve_disruption(e, load_factory_model(), ORDERS)
        self.assertEqual(r.delay_hours, 0)

    def test_speed_phrase_is_not_a_delay(self):
        for text in ("Line 2 stuck at 50%, 100 units short on EV-402",
                     "Line 2 held at 50%, 100 units short on EV-402"):
            e, _ = _extract(text)
            self.assertFalse(e.delay_mentioned, text)
            self.assertEqual(resolve_disruption(e, load_factory_model(), ORDERS).delay_hours, 0)

    def test_negated_delay_is_not_a_delay(self):
        for text in ("no delays reported, Line 2 at 60%, 80 units short on EV-402",
                     "shipment not delayed, Line 2 at 60%, 80 units short on EV-402",
                     "arrived without delay, Line 2 at 60%, 80 units short on EV-402"):
            e, _ = _extract(text)
            self.assertFalse(e.delay_mentioned, text)
            self.assertEqual(resolve_disruption(e, load_factory_model(), ORDERS).delay_hours, 0)

    def test_presets_resolve(self):
        prompts = [r["raw_message"] for r in db.get_scenarios("apex-volt-blr2")]
        for p in prompts:
            e, _ = _extract(p)
            resolve_disruption(e, load_factory_model(), ORDERS)


class LowercaseLineTests(unittest.TestCase):
    def test_lowercase_letter_with_speed_cue(self):
        e, _ = _extract("line a at 40%, 80 units short on WO-77", small_factory(), ["WO-77"])
        self.assertEqual([(l.line, l.speed_pct) for l in e.affected_lines], [("L-A", 40)])

    def test_lowercase_letter_prose_ignored(self):
        e, _ = _extract("line a bit slow, 80 units short on WO-77", small_factory(), ["WO-77"])
        self.assertEqual(e.affected_lines, [])


# ── M3: Gemini grounding ──────────────────────────────────────────────────

class GeminiGroundingTests(unittest.TestCase):
    def _gemini(self, text, payload):
        from app.agents import tools
        fake = mock.MagicMock()
        fake.models.generate_content.return_value = mock.MagicMock(text=json.dumps(payload))
        with mock.patch.object(type(tools.settings), "has_gemini", new_callable=mock.PropertyMock,
                               return_value=True), \
                mock.patch("google.genai.Client", return_value=fake) as client:
            ext, source = tools.extract_disruption_entities(text, load_factory_model(), ORDERS)
        self.assertTrue(client.called)
        self.assertTrue(source.startswith("gemini"))
        return ext

    def test_invented_shortfall_is_nulled(self):
        text = "Line 2 at 50%, 89C, Chennai delayed 2 days on EV-402, some casings short"
        ext = self._gemini(text, {
            "delay_hours": 48, "shortfall_units": 150, "affected_order": "EV-402",
            "affected_lines": [{"line": "LINE-2", "speed_pct": 50, "temp_celsius": 89.0}]})
        self.assertIsNone(ext.shortfall_units)
        self.assertEqual(ext.delay_hours, 48)  # 2 days x 24 is grounded
        self.assertEqual((ext.affected_lines[0].speed_pct, ext.affected_lines[0].temp_celsius), (50, 89.0))
        with self.assertRaises(DisruptionResolutionError) as cm:
            resolve_disruption(ext, load_factory_model(), ORDERS)
        self.assertIn("shortfall_units not stated", str(cm.exception))

    def test_invented_line_numbers_nulled(self):
        ext = self._gemini("Line 2 overheating, 1,200 short on EV-402, 6h delay", {
            "delay_hours": 7, "shortfall_units": 1200, "affected_order": "EV-402",
            "affected_lines": [{"line": "LINE-2", "speed_pct": 40, "temp_celsius": 95.0}]})
        self.assertEqual(ext.shortfall_units, 1200)
        self.assertIsNone(ext.delay_hours)
        self.assertEqual((ext.affected_lines[0].speed_pct, ext.affected_lines[0].temp_celsius), (None, None))


# ── I1 / M1 / M2: API ─────────────────────────────────────────────────────

class ApiFinalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.client.post("/api/v1/reset", headers=KEY)

    def tearDown(self):
        self.client.post("/api/v1/reset", headers=KEY)

    def test_sliders_body_runs(self):
        body = {"override_line_speeds": {"LINE-2": 40}, "override_shortfall_units": 120,
                "override_delay_hours": 10, "order_id": "EV-402", "source_channel": "WEB_DASHBOARD"}
        with mock.patch("google.genai.Client") as client:
            r = self.client.post("/api/v1/simulate-crisis", json=body, headers=KEY)
        self.assertFalse(client.called)
        self.assertEqual(r.status_code, 200, r.text)
        p = r.json()["extracted_parameters"]
        self.assertEqual([(li["line_id"], li["speed_pct"]) for li in p["line_impacts"]], [("LINE-2", 40)])
        self.assertEqual((p["shortfall_units"], p["delay_hours"], p["affected_order_id"]), (120, 10, "EV-402"))

    def test_overrides_only_still_need_shortfall(self):
        db.delete_all("order_lines")   # no inventory data: nothing can supply the shortfall
        r = self.client.post("/api/v1/simulate-crisis", headers=KEY,
                             json={"override_line_speeds": {"LINE-2": 40}, "order_id": "EV-402"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("shortfall_units", r.json()["detail"])

    def test_empty_body_is_422(self):
        r = self.client.post("/api/v1/simulate-crisis", json={"source_channel": "WEB_DASHBOARD"}, headers=KEY)
        self.assertEqual(r.status_code, 422)

    def test_scenario_1_keeps_stated_temperature(self):
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        li = r.json()["extracted_parameters"]["line_impacts"][0]
        self.assertEqual((li["line_id"], li["temp_celsius"]), ("LINE-2", 89.0))
        self.assertEqual(db.get_production_line("LINE-2")["temp_celsius"], 89.0)

    def test_plc_fields_required(self):
        for body in ({"line_id": "LINE-1"}, {"line_id": "LINE-1", "speed_pct": 70},
                     {"line_id": "LINE-1", "speed_pct": 70, "temp_celsius": 60.0}):
            r = self.client.post("/api/v1/ingest/plc-telemetry", json=body, headers=KEY)
            self.assertEqual(r.status_code, 422, body)


class OverrideTemperatureTests(unittest.TestCase):
    def test_override_copies_temp_best_effort(self):
        ext = DisruptionExtraction(
            shortfall_units=10, affected_order="EV-402",
            affected_lines=[LineImpactExtraction(line="Line 2", speed_pct=50, temp_celsius=89.0),
                            LineImpactExtraction(line="Line 9", speed_pct=20, temp_celsius=70.0)])
        r = resolve_disruption(ext, load_factory_model(), ORDERS,
                               DisruptionOverrides(line_speeds={"LINE-2": 40, "LINE-1": 80}))
        temps = {li.line_id: li.temp_celsius for li in r.line_impacts}
        self.assertEqual(temps, {"LINE-2": 89.0, "LINE-1": None})


if __name__ == "__main__":
    unittest.main()
