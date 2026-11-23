"""Round A / Task 2: risk reacts to the reported disruption (blocked routes, weather alerts).

Demo seeds, fixed clock: stock 350, shipment 500 eta +20h, EV-402 needs 500, deadline 38h.
"""

import json
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

from tests import _offline_env  # noqa: F401  (must precede app imports)

from app import db
from app.agents.graph import run_cascade_pipeline
from app.agents.tools import extract_disruption_entities
from app.disruption import ResolvedDisruption, resolve_route, risk_adjusted_model
from app.factory_model import FactoryModel, load_factory_model
from app.solver import simulate_monte_carlo

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
BASE = "Chennai Precision shipment delayed 30 hours"
BLOCKED = BASE + "; Hosur corridor blocked 30h"
HOSUR_ROUTE = "Hosur Industrial Corridor (42 km)"
NH48_ROUTE = "NH48 Chennai-Bengaluru Highway"
KW = dict(override_shortfall_units=350, override_line_speeds={"LINE-2": 50}, order_id="EV-402")


def _fix_clock(deadline_hours=38):
    db.update_rows("orders", "order_id", "EV-402", {"due_at": (NOW + timedelta(hours=deadline_hours)).isoformat()})
    db.update_rows("inbound_shipments", "shipment_id", "SHP-CHN-0001", {"eta": (NOW + timedelta(hours=20)).isoformat()})


def _alloc(result, plan_id):
    plan = next(p for p in result["playbooks"] if p["id"] == plan_id)
    return {a["supplier_id"]: a["units_allocated"] for a in plan["vendor_allocations"]}


def _run(message, deadline_hours=38, **kw):
    _fix_clock(deadline_hours)
    return run_cascade_pipeline(message, now=NOW, **{**KW, **kw})


class _Base(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()

    def tearDown(self):
        db.reset_to_seed()


class ExtractionTests(_Base):
    def _extract(self, text):
        model = load_factory_model()
        return extract_disruption_entities(text, model, ["EV-402", "EV-405"])[0]

    def test_named_route_found(self):
        self.assertEqual(self._extract("Hosur corridor blocked 30h").affected_route, "Hosur")
        self.assertEqual(self._extract("NH48 is blocked by a landslide, 20h delay").affected_route, "NH48")

    def test_route_not_taken_from_a_supplier_name(self):
        self.assertIsNone(self._extract("Hosur Precision Castings delayed 12h").affected_route)
        self.assertIsNone(self._extract("Chennai shipment delayed 48h").affected_route)

    def test_unknown_route_is_emitted_as_written(self):
        self.assertEqual(self._extract("Mysore Road blocked 30h").affected_route, "Mysore Road")

    def test_weather_cues(self):
        for cue in ("flooding", "cyclone", "heavy rain", "storm", "landslide", "waterlogging"):
            self.assertTrue(self._extract(f"{cue} on the highway, 20h delay").weather_alert, cue)
        self.assertFalse(self._extract("Chennai shipment delayed 20h").weather_alert)


class ContextTests(_Base):
    def _extract(self, text):
        return extract_disruption_entities(text, load_factory_model(), ["EV-402", "EV-405"])[0]

    def test_negated_or_figurative_weather_is_not_an_alert(self):
        for t in ("no flooding reported, Chennai shipment delayed 20h", "not heavy rain, delayed 20h",
                  "without storms the shipment is delayed 20h", "a flood of orders, shipment delayed 20h",
                  "a storm of complaints, shipment delayed 20h", "storm in a teacup, delayed 20h"):
            self.assertFalse(self._extract(t).weather_alert, t)
        self.assertTrue(self._extract("heavy rain and flooding, delayed 20h").weather_alert)

    def test_clear_route_is_not_blocked(self):
        for t in ("Hosur corridor clear, shipment delayed 30 hours", "Hosur corridor reopened, delayed 30 hours",
                  "Hosur corridor not blocked, delayed 30 hours"):
            self.assertEqual(self._extract(t).affected_routes, [], t)

    def test_each_blocked_route_is_listed(self):
        x = self._extract("NH48 and Hosur corridor both blocked 24h")
        self.assertEqual(x.affected_routes, ["NH48", "Hosur"])
        x = self._extract("NH48 is clear but Hosur corridor blocked, delayed 24h")
        self.assertEqual(x.affected_routes, ["Hosur"])

    def _gemini(self, text, payload):
        resp = mock.Mock(text=json.dumps(payload))
        fake_settings = mock.Mock(has_gemini=True, GEMINI_API_KEY="k", GEMINI_MODEL="m")
        with mock.patch("app.agents.tools.settings", fake_settings), \
                mock.patch("google.genai.Client") as client:
            client.return_value.models.generate_content.return_value = resp
            return extract_disruption_entities(text, load_factory_model(), ["EV-402"])

    def test_gemini_route_inside_a_supplier_name_is_dropped(self):
        x, source = self._gemini("Supplier Hosur Precision Castings delayed 30 hours",
                                 {"affected_route": "Hosur", "delay_hours": 30, "delay_mentioned": True})
        self.assertTrue(source.startswith("gemini"))
        self.assertIsNone(x.affected_route)
        self.assertEqual(x.affected_routes, [])

    def test_gemini_real_blocked_route_is_kept(self):
        x, _ = self._gemini("Hosur corridor blocked 30h", {"affected_route": "Hosur", "delay_hours": 30})
        self.assertEqual(x.affected_route, "Hosur")


class RouteResolutionTests(_Base):
    def test_nh4_does_not_match_nh48(self):
        blocked, note = resolve_route("NH4", None, load_factory_model())
        self.assertEqual(blocked, ())
        self.assertIn("NH4", note)

    def test_unmatched_route_without_supplier_blocks_nothing(self):
        blocked, note = resolve_route(["Mysore Road"], None, load_factory_model())
        self.assertEqual((blocked, bool(note)), ((), True))

    def test_several_routes_all_block_with_a_note(self):
        blocked, note = resolve_route(["NH48", "Hosur"], None, load_factory_model())
        self.assertEqual(blocked, (NH48_ROUTE, HOSUR_ROUTE))
        self.assertIn(NH48_ROUTE, note)
        self.assertIn(HOSUR_ROUTE, note)


class RiskAdjustedModelTests(_Base):
    def _disruption(self, **kw):
        base = dict(delay_hours=30, line_impacts=(), supplier_id="SUP-CHN-01", order_id="EV-402",
                    shortfall_units=350, headline="x", blocked_route=None, weather_alert=False)
        return ResolvedDisruption(**{**base, **kw})

    def test_blocked_route_shifts_only_that_routes_vendors(self):
        m = load_factory_model()
        hsr = m.vendor("SUP-HSR-03")
        adj = risk_adjusted_model(m, self._disruption(blocked_route=hsr.route))
        self.assertEqual(adj.vendor("SUP-HSR-03").lead_hours, hsr.lead_hours + 30)
        self.assertEqual(adj.vendor("SUP-HSR-03").min_lead_hours, hsr.min_lead_hours + 30)
        for sid in ("SUP-PNY-02", "SUP-AIR-04"):
            self.assertEqual(adj.vendor(sid), m.vendor(sid))

    def test_no_route_no_weather_is_identity(self):
        m = load_factory_model()
        self.assertEqual(risk_adjusted_model(m, self._disruption()), m)

    def test_weather_doubles_shock_capped_at_90(self):
        m = load_factory_model()
        adj = risk_adjusted_model(m, self._disruption(weather_alert=True))
        for v in m.vendors:
            self.assertEqual(adj.vendor(v.supplier_id).delay_shock_pct, min(90, 2 * v.delay_shock_pct))
        self.assertEqual(adj.vendor("SUP-PNY-02").delay_shock_pct, 12.0)

    def test_shock_cap_is_ninety(self):
        m = load_factory_model().with_vendor_overrides({"SUP-PNY-02": {"delay_shock_pct": 60}})
        adj = risk_adjusted_model(m, self._disruption(weather_alert=True))
        self.assertEqual(adj.vendor("SUP-PNY-02").delay_shock_pct, 90.0)

    def test_every_blocked_route_shifts_its_vendors(self):
        m = load_factory_model()
        adj = risk_adjusted_model(m, self._disruption(blocked_route=HOSUR_ROUTE,
                                                      blocked_routes=(HOSUR_ROUTE, m.vendor("SUP-PNY-02").route)))
        self.assertEqual(adj.vendor("SUP-HSR-03").lead_hours, 38.0)
        self.assertEqual(adj.vendor("SUP-PNY-02").lead_hours, 34.0)
        self.assertEqual(adj.vendor("SUP-AIR-04"), m.vendor("SUP-AIR-04"))

    def test_primary_route_roundtrips_and_old_payload_loads(self):
        m = load_factory_model()
        self.assertEqual(dict(m.primary_routes)["SUP-CHN-01"], NH48_ROUTE)
        d = m.to_dict()
        self.assertEqual(FactoryModel.from_dict(d), m)
        d.pop("primary_routes")
        self.assertEqual(FactoryModel.from_dict(d).primary_routes, ())


class BlockedRouteTests(_Base):
    def test_blocked_hosur_changes_the_allocation(self):
        base = _run(BASE)
        blocked = _run(BLOCKED)
        self.assertEqual(base["recommended_plan_id"], "PLAN_B")
        self.assertEqual(_alloc(base, "PLAN_B"), {"SUP-HSR-03": 150, "SUP-PNY-02": 200})
        self.assertEqual(blocked["blocked_route"], HOSUR_ROUTE)
        self.assertNotIn("SUP-HSR-03", _alloc(blocked, "PLAN_B"))
        self.assertEqual(_alloc(blocked, "PLAN_B"), {"SUP-AIR-04": 350})
        # later nodes and the persisted model use the risk-adjusted lead time
        self.assertEqual(blocked["factory_model"].vendor("SUP-HSR-03").lead_hours, 38.0)

    def test_tight_deadline_flips_winner_to_plan_a(self):
        # Peenya blocked +30h: its lead becomes 34h, so a deadline just above lead + QA leaves the
        # Peenya plan unlikely to finish in time and the Monte Carlo makes the expedite plan win.
        # The flip window is seed/margin dependent, so the deadline is scanned, not hard-coded: some
        # deadline above the shifted lead + QA must flip B (unblocked) to A (blocked), and a blocked
        # PLAN_A win may only happen where the unblocked winner is PLAN_B.
        peenya = BASE + "; Peenya industrial area blocked 30h"
        m = load_factory_model()
        shifted = m.vendor("SUP-PNY-02").lead_hours + 30 + m.qa_dispatch_hours
        flips = []
        for d in range(int(shifted * 2), int(shifted * 2) + 16):      # half-hour steps
            hours = d / 2
            base = _run(BASE, deadline_hours=hours, override_shortfall_units=150)
            blocked = _run(peenya, deadline_hours=hours, override_shortfall_units=150)
            self.assertEqual(blocked["blocked_route"], "Peenya Industrial Area (14 km)")
            if blocked["recommended_plan_id"] == "PLAN_A":
                self.assertEqual(base["recommended_plan_id"], "PLAN_B", hours)
                self.assertEqual(_alloc(blocked, "PLAN_A"), {"SUP-AIR-04": 150})
                flips.append(hours)
        self.assertTrue(flips, "no deadline flips the winner to PLAN_A")
        self.assertGreater(min(flips), shifted)

    def test_delayed_vendor_supplier_route_shifts_its_own_lead(self):
        r = _run("Supplier Hosur Precision Castings delayed 30 hours")
        self.assertEqual(r["blocked_route"], HOSUR_ROUTE)
        self.assertEqual(r["factory_model"].vendor("SUP-HSR-03").lead_hours, 38.0)

    def test_primary_route_has_no_vendors_so_model_unchanged(self):
        r = _run(BASE)
        self.assertEqual(r["blocked_route"], NH48_ROUTE)
        self.assertEqual(r["factory_model"].vendors, load_factory_model().vendors)

    def test_unknown_route_is_noted_not_applied(self):
        r = _run(BASE + "; Mysore Road blocked 30h")
        self.assertIn("Mysore Road", r["route_note"])
        self.assertEqual(r["blocked_route"], NH48_ROUTE)   # falls back to the delayed supplier's route
        self.assertEqual(r["factory_model"].vendors, load_factory_model().vendors)

    def test_clear_route_does_not_shift_and_both_blocked_do(self):
        clear = _run(BASE + "; Hosur corridor clear")
        self.assertEqual(clear["factory_model"].vendor("SUP-HSR-03").lead_hours, 8.0)
        both = _run("Chennai Precision shipment delayed 24 hours; NH48 and Hosur corridor both blocked 24h")
        self.assertEqual(both["factory_model"].vendor("SUP-HSR-03").lead_hours, 32.0)
        self.assertEqual(set(both["blocked_routes"]), {NH48_ROUTE, HOSUR_ROUTE})
        self.assertIn(NH48_ROUTE, both["route_note"])
        self.assertIn(HOSUR_ROUTE, both["route_note"])

    def test_known_route_has_no_note(self):
        self.assertIsNone(_run(BLOCKED)["route_note"])


class WeatherTests(_Base):
    def test_weather_alert_lowers_road_vendor_confidence(self):
        m = load_factory_model()
        d = ResolvedDisruption(30, (), "SUP-CHN-01", "EV-402", 350, "x", weather_alert=True)
        wet = risk_adjusted_model(m, d)
        args = ("PROPOSAL", {"SUP-HSR-03": 150, "SUP-PNY-02": 200}, 0)
        dry_p = simulate_monte_carlo(m, *args, deadline_hours=12.0)["confidence_pct"]
        wet_p = simulate_monte_carlo(wet, *args, deadline_hours=12.0)["confidence_pct"]
        self.assertLess(wet_p, dry_p)

    def test_pipeline_flags_weather_and_doubles_shock(self):
        dry = _run(BASE)
        wet = _run("Flooding on NH48; Chennai Precision shipment delayed 30 hours")
        self.assertTrue(wet["weather_alert"])
        self.assertFalse(dry["weather_alert"])
        self.assertEqual(wet["factory_model"].vendor("SUP-PNY-02").delay_shock_pct, 12.0)


class ScenarioRegressionTests(_Base):
    def test_scenarios_keep_their_winners(self):
        want = {1: "PLAN_B", 2: "PLAN_C", 3: "PLAN_B"}
        for sid, plan in want.items():
            db.reset_to_seed()
            sc = {r["scenario_id"]: r for r in db.get_scenarios("apex-volt-blr2")}[sid]
            r = run_cascade_pipeline(
                sc["raw_message"], override_delay_hours=sc["delay_hours"],
                override_shortfall_units=sc["shortfall_units"], override_line_speeds=sc["line_speeds"],
                order_id=sc["order_id"])
            self.assertEqual(r["recommended_plan_id"], plan, sid)


if __name__ == "__main__":
    unittest.main()
