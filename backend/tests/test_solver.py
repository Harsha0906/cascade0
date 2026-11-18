"""Solver tests. Run from backend/: python -m unittest discover -s tests -v  (or pytest)."""

import unittest
import xml.etree.ElementTree as ET

from tests import _offline_env  # noqa: F401  (must precede app imports)
from app.schemas import PlaybookOption, VendorAllocation
from app.solver import (
    HOSUR,
    OVERTIME_UNITS_PER_HOUR,
    PEENYA,
    SolverInputError,
    build_tally_xml,
    generate_playbooks,
    line2_throughput_gap,
    simulate_monte_carlo,
    solve_pulp_milp,
)


class MilpTests(unittest.TestCase):
    def test_small_shortfall_uses_cheapest_vendor(self):
        lp = solve_pulp_milp(150, 48, 50)
        self.assertTrue(lp["feasible"])
        self.assertEqual(lp["units_by_vendor"], {PEENYA.supplier_id: 150})
        self.assertFalse(lp["air_charter"])

    def test_overtime_covers_line2_gap_and_uses_speed(self):
        fast = solve_pulp_milp(100, 0, 100)
        slow = solve_pulp_milp(100, 0, 25)
        self.assertEqual(fast["overtime_hours"], 0, "no throughput gap at full speed")
        self.assertGreater(slow["overtime_hours"], 0)
        self.assertGreaterEqual(slow["overtime_hours"] * OVERTIME_UNITS_PER_HOUR, line2_throughput_gap(25))

    def test_capacity_split_when_peenya_is_exhausted(self):
        lp = solve_pulp_milp(350, 72, 25)
        self.assertEqual(lp["units_by_vendor"].get(PEENYA.supplier_id), 200)
        self.assertEqual(lp["units_by_vendor"].get(HOSUR.supplier_id), 150)

    def test_infeasible_input_is_reported_not_hidden(self):
        lp = solve_pulp_milp(1000, 72, 25)
        self.assertFalse(lp["feasible"])
        self.assertEqual(lp["uncovered_material_units"], 120)  # 200 + 180 + 500 = 880 capacity
        self.assertNotEqual(lp["status"], "Optimal")
        self.assertGreater(lp["total_cost_inr"], 0)

    def test_tight_deadline_excludes_slow_vendor(self):
        # Hosur (8h lead) + overtime + 2.5h QA cannot fit in 10h; the model must route elsewhere.
        lp = solve_pulp_milp(350, 72, 100, deadline_hours=10)
        self.assertNotIn(HOSUR.supplier_id, lp["units_by_vendor"])
        self.assertTrue(lp["air_charter"])

    def test_reliability_floor_excludes_hosur(self):
        lp = solve_pulp_milp(350, 72, 25, min_vendor_reliability_pct=85)
        self.assertNotIn(HOSUR.supplier_id, lp["units_by_vendor"])

    def test_rejects_negative_shortfall(self):
        with self.assertRaises(SolverInputError):
            solve_pulp_milp(-1)


class MonteCarloTests(unittest.TestCase):
    def test_uncovered_plan_never_succeeds(self):
        mc = simulate_monte_carlo("X", {PEENYA.supplier_id: 10}, 1, fully_covered=False)
        self.assertEqual(mc["confidence_pct"], 0.0)

    def test_deadline_changes_probability(self):
        units = {HOSUR.supplier_id: 100}
        loose = simulate_monte_carlo("X", units, 4, deadline_hours=38)["confidence_pct"]
        tight = simulate_monte_carlo("X", units, 4, deadline_hours=15)["confidence_pct"]
        self.assertGreater(loose, tight)
        self.assertLess(tight, 100.0)

    def test_renegotiation_depends_on_delay(self):
        short = simulate_monte_carlo("SLA_RENEGOTIATION", {}, 0, delay_hours=6)["confidence_pct"]
        long_ = simulate_monte_carlo("SLA_RENEGOTIATION", {}, 0, delay_hours=96)["confidence_pct"]
        self.assertGreater(short, long_)

    def test_confidence_interval_brackets_estimate(self):
        mc = simulate_monte_carlo("X", {HOSUR.supplier_id: 50}, 2, deadline_hours=14)
        self.assertLessEqual(mc["ci_low_pct"], mc["confidence_pct"])
        self.assertGreaterEqual(mc["ci_high_pct"], mc["confidence_pct"])


class RankingTests(unittest.TestCase):
    def _assert_winner_is_min_expected_cost(self, res):
        best = min(p.expected_cost_inr for p in res.playbooks)
        winner = next(p for p in res.playbooks if p.id == res.recommended_plan_id)
        self.assertEqual(winner.expected_cost_inr, best)
        self.assertEqual(sum(p.recommended for p in res.playbooks), 1)

    def test_winner_is_argmin_expected_cost_across_scenarios(self):
        for args in [(150, 48, 50), (25, 6, 85), (350, 72, 25), (450, 48, 50), (1000, 72, 25)]:
            with self.subTest(args=args):
                self._assert_winner_is_min_expected_cost(generate_playbooks(*args))

    def test_cheaper_plan_wins_when_equally_safe(self):
        # The old code recommended Plan B unconditionally; check the cheaper safe plan wins.
        res = generate_playbooks(25, 6, 85)
        self.assertEqual(res.recommended_plan_id, "PLAN_C")

    def test_over_capacity_flags_infeasible_plans(self):
        res = generate_playbooks(1000, 72, 25)
        self.assertTrue(res.capacity_exhausted)
        self.assertIn("Infeasible", res.lp_status)
        plan_b = next(p for p in res.playbooks if p.id == "PLAN_B")
        self.assertFalse(plan_b.feasible)
        self.assertEqual(plan_b.confidence_pct, 0.0)
        self.assertNotEqual(res.recommended_plan_id, "PLAN_B")


class Round2RegressionTests(unittest.TestCase):
    def test_short_deadline_does_not_crash(self):
        res = generate_playbooks(150, 48, 50, deadline_hours=6)
        plan_a = next(p for p in res.playbooks if p.id == "PLAN_A")
        self.assertFalse(plan_a.feasible)  # forced air (6h lead + QA) cannot meet 6h
        self.assertNotEqual(res.recommended_plan_id, "PLAN_A")

    def test_deadline_before_qa_is_input_error(self):
        with self.assertRaises(SolverInputError):
            generate_playbooks(150, 48, 50, deadline_hours=2)

    def test_zero_shortfall_recommends_doing_nothing(self):
        res = generate_playbooks(0, 0, 100)
        self.assertEqual(res.recommended_plan_id, "PLAN_D")
        winner = next(p for p in res.playbooks if p.recommended)
        self.assertEqual(winner.total_mitigation_cost_inr, 0)

    def test_zero_penalty_means_no_spend(self):
        res = generate_playbooks(150, 48, 50, sla_penalty_inr=0)
        self.assertEqual(res.recommended_plan_id, "PLAN_D")

    def test_forced_air_plan_actually_uses_air(self):
        res = generate_playbooks(150, 48, 50)
        plan_a = next(p for p in res.playbooks if p.id == "PLAN_A")
        self.assertIn("SUP-AIR-04", [a.supplier_id for a in plan_a.vendor_allocations])

    def test_overtime_only_plan_respects_deadline(self):
        res = generate_playbooks(50, 6, 0, deadline_hours=6)
        plan_c = next(p for p in res.playbooks if p.id == "PLAN_C")
        self.assertFalse(plan_c.feasible)  # 8h of overtime cannot fit in a 6h window


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
        xml = build_tally_xml("PO-1", self._plan())
        root = ET.fromstring(xml)  # raises if special characters were not escaped
        self.assertEqual(root.findtext(".//PARTYLEDGERNAME"), "Peenya & Sons <Metals>")
        self.assertEqual(root.findtext(".//SVCURRENTCOMPANY") is not None, True)

    def test_voucher_balances(self):
        root = ET.fromstring(build_tally_xml("PO-1", self._plan("Peenya")))
        party = int(root.findtext(".//LEDGERENTRIES.LIST/AMOUNT"))
        inventory = int(root.findtext(".//ALLINVENTORYENTRIES.LIST/AMOUNT"))
        self.assertEqual(party + inventory, 0)
        self.assertEqual(root.findtext(".//STOCKITEMNAME"), "Aluminium Battery Casing")


if __name__ == "__main__":
    unittest.main()
