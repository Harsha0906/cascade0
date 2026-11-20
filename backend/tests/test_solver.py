"""Solver tests. Run from backend/: python -m unittest discover -s tests -v  (or pytest)."""

import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace

from tests import _offline_env  # noqa: F401  (must precede app imports)
from app.factory_model import ProductionLine, load_factory_model
from app.schemas import PlaybookOption, VendorAllocation
from app.solver import (
    SolverInputError,
    build_shift_broadcast_msg,
    build_tally_xml,
    generate_playbooks,
    simulate_monte_carlo,
    solve_pulp_milp,
)
from tests.factories import small_factory

DEMO = load_factory_model()
S = lambda speed: {"LINE-2": speed}  # noqa: E731

PEENYA = "SUP-PNY-02"
HOSUR = "SUP-HSR-03"
AIR = "SUP-AIR-04"

ORDER = dict(order_id="EV-402", sla_penalty_inr=2_500_000, partial_penalty_inr=500_000,
             deadline_hours=38, client="Ather-Grid Mobility Corp")
SMALL_ORDER = dict(order_id="X", sla_penalty_inr=500_000, partial_penalty_inr=100_000,
                   deadline_hours=24, client="C")


def _order(**changes):
    return {**ORDER, **changes}


def _ot_units(model, overtime_line_hours):
    by_id = {l.line_id: l for l in model.lines}
    return sum(by_id[lid].ot_units_per_hour * h for lid, h in overtime_line_hours.items())


class MilpTests(unittest.TestCase):
    def test_small_shortfall_uses_cheapest_vendor(self):
        lp = solve_pulp_milp(DEMO, 150, S(50), 38)
        self.assertTrue(lp["feasible"])
        self.assertEqual(lp["units_by_vendor"], {PEENYA: 150})
        self.assertFalse(lp["air_charter"])

    def test_overtime_covers_throughput_gap_and_uses_speed(self):
        fast = solve_pulp_milp(DEMO, 100, S(100), 38)
        slow = solve_pulp_milp(DEMO, 100, S(25), 38)
        self.assertEqual(fast["overtime_hours"], 0, "no throughput gap at full speed")
        self.assertEqual(fast["throughput_gap_units"], 0)
        self.assertGreater(slow["overtime_hours"], 0)
        self.assertEqual(slow["throughput_gap_units"], DEMO.throughput_gap(S(25)))
        self.assertGreaterEqual(_ot_units(DEMO, slow["overtime_line_hours"]), DEMO.throughput_gap(S(25)))
        # The reported window is the longest line's overtime.
        self.assertEqual(slow["overtime_hours"], max(slow["overtime_line_hours"].values()))

    def test_capacity_split_when_peenya_is_exhausted(self):
        lp = solve_pulp_milp(DEMO, 350, S(25), 38)
        self.assertEqual(lp["units_by_vendor"].get(PEENYA), 200)
        self.assertEqual(lp["units_by_vendor"].get(HOSUR), 150)

    def test_infeasible_input_is_reported_not_hidden(self):
        lp = solve_pulp_milp(DEMO, 1000, S(25), 38)
        self.assertFalse(lp["feasible"])
        self.assertEqual(lp["uncovered_material_units"], 120)  # 200 + 180 + 500 = 880 capacity
        self.assertNotEqual(lp["status"], "Optimal")
        self.assertGreater(lp["total_cost_inr"], 0)

    def test_tight_deadline_excludes_slow_vendor(self):
        # Hosur (8h lead) + overtime + 2.5h QA cannot fit in 10h; the model must route elsewhere.
        lp = solve_pulp_milp(DEMO, 350, S(100), deadline_hours=10)
        self.assertNotIn(HOSUR, lp["units_by_vendor"])
        self.assertTrue(lp["air_charter"])

    def test_reliability_floor_excludes_hosur(self):
        lp = solve_pulp_milp(DEMO, 350, S(25), 38, min_vendor_reliability_pct=85)
        self.assertNotIn(HOSUR, lp["units_by_vendor"])

    def test_rejects_negative_shortfall(self):
        with self.assertRaises(SolverInputError):
            solve_pulp_milp(DEMO, -1, S(100), 38)

    def test_forced_vendor_missing_from_model_is_reported(self):
        lp = solve_pulp_milp(DEMO, 150, S(50), 38, force_vendor_id=AIR, allowed_vendor_ids=[PEENYA])
        self.assertFalse(lp["feasible"])
        self.assertEqual(lp["status"], "Infeasible: forced vendor unavailable")
        self.assertEqual(lp["overtime_line_hours"], {})

    def test_reported_cost_excludes_tie_break_terms(self):
        lp = solve_pulp_milp(DEMO, 150, S(50), 38)
        self.assertEqual(lp["total_cost_inr"], 150 * 600 + 8 * 11_250)
        self.assertEqual(lp["overtime_line_hours"], {"LINE-1": 4, "LINE-3": 4})
        self.assertEqual(lp["overtime_hours"], 4)

    def test_tie_breaks_never_outweigh_one_rupee_of_real_cost(self):
        # LINE-X loses 80 units. OT-1: ₹1000/h, 10 u/h -> 8h = ₹8000 (8h window).
        # OT-2: ₹4001/h, 40 u/h -> 2h = ₹8002 (2h window). A ₹1/h window tie-break would pick
        # OT-2 (8002 + 2 < 8000 + 8); the real cost minimum is OT-1.
        m = replace(small_factory(), production_hours_in_window=16.0, lines=(
            ProductionLine("LINE-X", "X", 10, 0, 0, 0),
            ProductionLine("OT-1", "OT 1", 10, 10, 1000, 8),
            ProductionLine("OT-2", "OT 2", 10, 40, 4001, 8),
        ))
        lp = solve_pulp_milp(m, 0, {"LINE-X": 50}, 24)
        self.assertTrue(lp["feasible"])
        self.assertEqual(lp["overtime_line_hours"], {"OT-1": 8})
        self.assertEqual(lp["total_cost_inr"], 8000)

    def test_tie_break_worst_case_is_below_one_rupee(self):
        from app.solver import _tie_break_weights
        for m in (DEMO, small_factory()):
            w_window, w_unit = _tie_break_weights(m)
            max_window = max((l.max_ot_hours for l in m.overtime_lines), default=0)
            max_units = sum(v.max_units for v in m.vendors)
            self.assertLess(w_window * max_window + w_unit * max_units, 1.0)
            self.assertGreater(w_window, 0)
            self.assertGreater(w_unit, 0)

    def test_factory_without_overtime_lines_reports_gap_uncovered(self):   # Review Focus 3
        m = replace(small_factory(), lines=(ProductionLine("L-A", "A", 10, 0, 0, 0),))
        lp = solve_pulp_milp(m, 0, {"L-A": 50}, 24)
        self.assertFalse(lp["feasible"])
        self.assertEqual(lp["uncovered_capacity_units"], 50)


class MonteCarloTests(unittest.TestCase):
    def test_uncovered_plan_never_succeeds(self):
        mc = simulate_monte_carlo(DEMO, "X", {PEENYA: 10}, 1, 38, fully_covered=False)
        self.assertEqual(mc["confidence_pct"], 0.0)

    def test_deadline_changes_probability(self):
        units = {HOSUR: 100}
        loose = simulate_monte_carlo(DEMO, "X", units, 4, 38)["confidence_pct"]
        tight = simulate_monte_carlo(DEMO, "X", units, 4, 15)["confidence_pct"]
        self.assertGreater(loose, tight)
        self.assertLess(tight, 100.0)

    def test_renegotiation_depends_on_delay(self):
        short = simulate_monte_carlo(DEMO, "SLA_RENEGOTIATION", {}, 0, 38, delay_hours=6)["confidence_pct"]
        long_ = simulate_monte_carlo(DEMO, "SLA_RENEGOTIATION", {}, 0, 38, delay_hours=96)["confidence_pct"]
        self.assertGreater(short, long_)

    def test_confidence_interval_brackets_estimate(self):
        mc = simulate_monte_carlo(DEMO, "X", {HOSUR: 50}, 2, 14)
        self.assertLessEqual(mc["ci_low_pct"], mc["confidence_pct"])
        self.assertGreaterEqual(mc["ci_high_pct"], mc["confidence_pct"])

    def test_qa_time_comes_from_the_model(self):
        slow_qa = replace(DEMO, qa_dispatch_hours=10.0)
        fast = simulate_monte_carlo(DEMO, "X", {PEENYA: 50}, 0, 9)["confidence_pct"]
        slow = simulate_monte_carlo(slow_qa, "X", {PEENYA: 50}, 0, 9)["confidence_pct"]
        self.assertGreater(fast, slow)
        self.assertEqual(slow, 0.0)


class RankingTests(unittest.TestCase):
    def _assert_winner_is_min_expected_cost(self, res):
        best = min(p.expected_cost_inr for p in res.playbooks)
        winner = next(p for p in res.playbooks if p.id == res.recommended_plan_id)
        self.assertEqual(winner.expected_cost_inr, best)
        self.assertEqual(sum(p.recommended for p in res.playbooks), 1)

    def test_winner_is_argmin_expected_cost_across_scenarios(self):
        for shortfall, delay, speed in [(150, 48, 50), (25, 6, 85), (350, 72, 25), (450, 48, 50),
                                        (1000, 72, 25)]:
            with self.subTest(args=(shortfall, delay, speed)):
                self._assert_winner_is_min_expected_cost(
                    generate_playbooks(DEMO, shortfall, delay, S(speed), **ORDER))

    def test_cheaper_plan_wins_when_equally_safe(self):
        # The old code recommended Plan B unconditionally; check the cheaper safe plan wins.
        res = generate_playbooks(DEMO, 25, 6, S(85), **ORDER)
        self.assertEqual(res.recommended_plan_id, "PLAN_C")

    def test_over_capacity_flags_infeasible_plans(self):
        res = generate_playbooks(DEMO, 1000, 72, S(25), **ORDER)
        self.assertTrue(res.capacity_exhausted)
        self.assertIn("Infeasible", res.lp_status)
        plan_b = next(p for p in res.playbooks if p.id == "PLAN_B")
        self.assertFalse(plan_b.feasible)
        self.assertEqual(plan_b.confidence_pct, 0.0)
        self.assertEqual(res.recommended_plan_id, "PLAN_C")  # golden: renegotiate when capacity is exhausted

    def test_demo_scenarios_regression(self):
        r1 = generate_playbooks(DEMO, 150, 48, S(50), **ORDER)
        r2 = generate_playbooks(DEMO, 25, 6, S(85), **ORDER)
        r3 = generate_playbooks(DEMO, 350, 72, S(25), **ORDER)
        win = lambda r: next(p for p in r.playbooks if p.recommended)  # noqa: E731
        self.assertEqual((r1.recommended_plan_id, win(r1).total_mitigation_cost_inr), ("PLAN_B", 180_000))
        self.assertEqual((r2.recommended_plan_id, win(r2).total_mitigation_cost_inr), ("PLAN_C", 33_750))
        self.assertEqual((r3.recommended_plan_id, win(r3).total_mitigation_cost_inr), ("PLAN_B", 382_500))
        self.assertEqual(win(r1).overtime_line_hours, {"LINE-1": 4, "LINE-3": 4})
        self.assertEqual(win(r1).overtime_hours, 4)
        self.assertEqual(win(r1).overtime_cost_inr, 90_000)
        self.assertEqual(r1.throughput_gap_units, 152)

    def test_second_factory_defined_only_by_data(self):
        r = generate_playbooks(small_factory(), 120, 10, {"L-A": 40}, order_id="X", sla_penalty_inr=500_000,
                               partial_penalty_inr=100_000, deadline_hours=24, client="C")
        b = next(p for p in r.playbooks if p.id == "PLAN_B")
        self.assertEqual({a.supplier_id: a.units_allocated for a in b.vendor_allocations}, {"V1": 100, "V2": 20})
        self.assertEqual(b.total_mitigation_cost_inr, 50_000 + 18_000 + 15_000)   # V1 + V2 + 3h overtime
        self.assertEqual(b.overtime_line_hours, {"L-B": 3})          # gap 10×0.6×10 = 60 → 3h × 20 u/h

    def test_flat_fee_vendor_is_not_over_allocated(self):
        r = generate_playbooks(small_factory(), 120, 10, {"L-A": 100}, **SMALL_ORDER)
        a = next(p for p in r.playbooks if p.id == "PLAN_A")
        self.assertEqual(sum(x.units_allocated for x in a.vendor_allocations), 120)

    def test_factory_without_expedite_vendor_has_no_plan_a(self):    # Review Focus 2
        m = small_factory().with_vendor_overrides({"V3": {"max_units": 0}})
        r = generate_playbooks(m, 50, 10, {"L-A": 100}, **SMALL_ORDER)
        self.assertNotIn("PLAN_A", [p.id for p in r.playbooks])
        self.assertEqual(sum(p.recommended for p in r.playbooks), 1)


class Round2RegressionTests(unittest.TestCase):
    def test_short_deadline_does_not_crash(self):
        res = generate_playbooks(DEMO, 150, 48, S(50), **_order(deadline_hours=6))
        plan_a = next(p for p in res.playbooks if p.id == "PLAN_A")
        self.assertFalse(plan_a.feasible)  # forced air (6h lead + QA) cannot meet 6h
        self.assertNotEqual(res.recommended_plan_id, "PLAN_A")

    def test_deadline_before_qa_is_input_error(self):
        with self.assertRaises(SolverInputError):
            generate_playbooks(DEMO, 150, 48, S(50), **_order(deadline_hours=2))

    def test_zero_shortfall_recommends_doing_nothing(self):
        res = generate_playbooks(DEMO, 0, 0, S(100), **ORDER)
        self.assertEqual(res.recommended_plan_id, "PLAN_D")
        winner = next(p for p in res.playbooks if p.recommended)
        self.assertEqual(winner.total_mitigation_cost_inr, 0)

    def test_zero_penalty_means_no_spend(self):
        res = generate_playbooks(DEMO, 150, 48, S(50), **_order(sla_penalty_inr=0))
        self.assertEqual(res.recommended_plan_id, "PLAN_D")

    def test_forced_air_plan_actually_uses_air(self):
        res = generate_playbooks(DEMO, 150, 48, S(50), **ORDER)
        plan_a = next(p for p in res.playbooks if p.id == "PLAN_A")
        self.assertIn(AIR, [a.supplier_id for a in plan_a.vendor_allocations])

    def test_overtime_only_plan_respects_deadline(self):
        res = generate_playbooks(DEMO, 50, 6, S(0), **_order(deadline_hours=6))
        plan_c = next(p for p in res.playbooks if p.id == "PLAN_C")
        self.assertFalse(plan_c.feasible)  # 16h of line overtime cannot fit in a 6h window

    def test_vendor_overrides_and_confirmed_flags(self):
        res = generate_playbooks(DEMO, 150, 48, S(50), **ORDER,
                                 vendor_overrides={PEENYA: {"max_units": 0}},
                                 confirmed_vendor_ids={HOSUR})
        plan_b = next(p for p in res.playbooks if p.id == "PLAN_B")
        ids = [a.supplier_id for a in plan_b.vendor_allocations]
        self.assertNotIn(PEENYA, ids)
        hosur = next(a for a in plan_b.vendor_allocations if a.supplier_id == HOSUR)
        self.assertTrue(hosur.confirmed)


class MessageTests(unittest.TestCase):
    def test_shift_broadcast_lists_model_line_names(self):
        msg = build_shift_broadcast_msg(DEMO, {"LINE-1": 4, "LINE-3": 4}, 150, "EV-402", "Client")
        by_id = {l.line_id: l.name for l in DEMO.lines}
        self.assertIn(by_id["LINE-1"], msg)
        self.assertIn(by_id["LINE-3"], msg)
        self.assertNotIn(by_id["LINE-2"], msg)

    def test_shift_broadcast_without_overtime(self):
        msg = build_shift_broadcast_msg(DEMO, {}, 150, "EV-402", "Client")
        self.assertIn("No overtime required", msg)


class TallyXmlTests(unittest.TestCase):
    def _plan(self, name="Peenya & Sons <Metals>"):
        alloc = VendorAllocation(
            supplier_id="S1", supplier_name=name, tier="T2", units_allocated=150,
            cost_per_unit_inr=600, total_cost_inr=90000, lead_time_hours=4, route="r",
        )
        return PlaybookOption(
            id="PLAN_B", name="Plan B", strategy_type="X", vendor_allocations=[alloc],
            overtime_hours=4, overtime_cost_inr=90000, supplier_cost_inr=90000,
            total_mitigation_cost_inr=180000, sla_penalty_prevented_inr=0, net_sla_saved_inr=0,
            roi_multiplier=0, confidence_pct=100,
        )

    def test_xml_is_well_formed_and_escaped(self):
        xml = build_tally_xml("PO-1", self._plan(), DEMO)
        root = ET.fromstring(xml)  # raises if special characters were not escaped
        self.assertEqual(root.findtext(".//PARTYLEDGERNAME"), "Peenya & Sons <Metals>")
        self.assertEqual(root.findtext(".//SVCURRENTCOMPANY"), DEMO.name)

    def test_voucher_balances(self):
        root = ET.fromstring(build_tally_xml("PO-1", self._plan("Peenya"), DEMO))
        party = int(root.findtext(".//LEDGERENTRIES.LIST/AMOUNT"))
        inventory = int(root.findtext(".//ALLINVENTORYENTRIES.LIST/AMOUNT"))
        self.assertEqual(party + inventory, 0)
        self.assertEqual(root.findtext(".//STOCKITEMNAME"), "Aluminium Battery Casing")

    def test_company_and_stock_item_come_from_the_model(self):
        root = ET.fromstring(build_tally_xml("PO-1", self._plan(), small_factory()))
        self.assertEqual(root.findtext(".//SVCURRENTCOMPANY"), "Test Plant")
        self.assertEqual(root.findtext(".//STOCKITEMNAME"), "Widget")


class IndexNamedVariableTests(unittest.TestCase):
    @staticmethod
    def _colliding_factory():
        from tests.factories import _vendor
        from app.factory_model import FactoryModel
        return FactoryModel(
            factory_id="collide", name="Collide", stock_item_name="Widget",
            qa_dispatch_hours=2.0, safety_stock_units=30, production_hours_in_window=10.0,
            vendors=(
                _vendor("V-1", "BACKUP", 30, 500, 0, 4, 90),
                _vendor("V_1", "BACKUP", 30, 600, 0, 4, 90),
            ),
            lines=(
                ProductionLine("L-B", "Line B", 10.0, 20, 5000, 6),
                ProductionLine("L_B", "Line B2", 10.0, 10, 3000, 2),
            ),
        )

    def test_colliding_ids_do_not_collide_in_milp(self):
        lp = solve_pulp_milp(self._colliding_factory(), 50, {"L-B": 50}, 40)
        self.assertTrue(set(lp["overtime_line_hours"]) <= {"L-B", "L_B"})
        self.assertTrue(lp["feasible"])  # both vendors usable -> 50 units covered

    def test_solver_result_reports_line_speeds(self):
        res = generate_playbooks(small_factory(), 40, 5, {"L-B": 60}, order_id="WO-1",
                                 sla_penalty_inr=100_000, partial_penalty_inr=20_000,
                                 deadline_hours=30, client="Client")
        self.assertEqual(res.line_speeds, {"L-B": 60})


if __name__ == "__main__":
    unittest.main()
