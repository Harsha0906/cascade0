import unittest

from tests import _offline_env  # noqa: F401

from app.factory_model import FactoryDataError
from tests.factories import small_factory


class FactoryModelTests(unittest.TestCase):
    def test_throughput_gap_sums_listed_lines(self):
        self.assertEqual(small_factory().throughput_gap({"L-A": 50}), 50)  # 10*0.5*10
        self.assertEqual(small_factory().throughput_gap({"L-A": 50, "L-B": 80}), 70)
        self.assertEqual(small_factory().throughput_gap({"L-A": 100}), 0)

    def test_unknown_line_rejected(self):
        with self.assertRaises(FactoryDataError):
            small_factory().throughput_gap({"L-Z": 50})

    def test_overtime_lines_and_expedite(self):
        m = small_factory()
        self.assertEqual([l.line_id for l in m.overtime_lines], ["L-B"])
        self.assertEqual(m.expedite_vendor_id, "V3")

    def test_overrides_replace_and_drop(self):
        m = small_factory().with_vendor_overrides(
            {"V1": {"max_units": 40, "unit_cost": 520}, "V3": {"max_units": 0}})
        self.assertEqual((m.vendor("V1").max_units, m.vendor("V1").unit_cost), (40, 520))
        self.assertIsNone(m.expedite_vendor_id)

    def test_override_for_unknown_vendor_rejected(self):
        with self.assertRaises(FactoryDataError):
            small_factory().with_vendor_overrides({"NOPE": {"max_units": 5}})


if __name__ == "__main__":
    unittest.main()
