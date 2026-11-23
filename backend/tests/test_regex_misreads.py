from tests import _offline_env  # noqa: F401  (must precede any app import)

import unittest

from app.agents.sourcing import RFQ, _regex_parse
from app.agents.tools import _regex_extract
from app.factory_model import load_factory_model

ORDERS = ["EV-402", "EV-405"]


def _rfq(units=150):
    return RFQ(id="R", run_id="X", round=1, supplier_id="SUP-PNY-02", supplier_name="Peenya",
               units_requested=units, expected_unit_price_inr=600, needed_within_hours=34, channel="simulated")


class DeclinesNeverReadAsAcceptance(unittest.TestCase):
    def test_declines(self):
        for text in ("Sorry, not available", "Not possible this week, mushkil hai", "possible nahi hai",
                     "Sorry, can not do", "Cannot supply", "can't do this week", "Unavailable",
                     "Out of stock, regret", "nahi", "No stock. Sorry", "will let you know later",
                     "sorry sir, no"):
            with self.subTest(text=text):
                o = _regex_parse(text, _rfq())
                self.assertTrue(o.declined, o)
                self.assertEqual(o.available_units, 0)

    def test_decline_with_explicit_smaller_offer_is_partial(self):
        for text, units in (("sorry, only 100 units available", 100),
                            ("Can't do 150 but can do 60 units at ₹650 in 6 hours", 60)):
            with self.subTest(text=text):
                o = _regex_parse(text, _rfq())
                self.assertFalse(o.declined)
                self.assertEqual(o.available_units, units)

    def test_default_to_requested_units_only_with_an_acceptance_cue(self):
        for text in ("ok", "Yes", "haan ho jayega", "confirmed, ₹600", "done, 6 hrs"):
            with self.subTest(text=text):
                o = _regex_parse(text, _rfq())
                self.assertFalse(o.declined)
                self.assertEqual(o.available_units, 150)
        for text in ("rate 600", "6 hrs", "₹620 per piece"):
            with self.subTest(text=text):
                self.assertTrue(_regex_parse(text, _rfq()).declined)   # unclear: needs an operator


class IdsAreNotQuantities(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_factory_model()

    def _ex(self, text):
        return _regex_extract(text, self.model, ORDERS)

    def test_order_id_is_not_a_shortfall(self):
        self.assertIsNone(self._ex("Line 2 at 40%, EV-402 is short").shortfall_units)
        self.assertIsNone(self._ex("EV-405 missing, line 1 at 50%").shortfall_units)
        self.assertEqual(self._ex("EV-405 is short, 300 units short").shortfall_units, 300)

    def test_line_and_reference_ids_are_not_delay_or_speed(self):
        self.assertIsNone(self._ex("LINE-2 delay").delay_hours)
        ex = self._ex("Chennai Precision delayed 12 hours, #A123 hrs, EV-402 hours")
        self.assertEqual(ex.delay_hours, 12)
        self.assertIsNone(self._ex("EV-402 hrs late").delay_hours)

    def test_real_numbers_still_read(self):
        ex = self._ex("Chennai Precision Casings delayed by 12 hours. Line 2 at 40%. 1,200 casings short on EV-402.")
        self.assertEqual((ex.delay_hours, ex.shortfall_units), (12, 1200))


class NegatedDelayNamesNoSupplier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_factory_model()

    def test_no_delays_from_supplier(self):
        for text in ("No delays from Chennai Precision. Line 2 at 40%. EV-405 300 units short.",
                     "Chennai Precision Casings is not delayed. Line 2 at 40%. EV-405 300 units short."):
            with self.subTest(text=text):
                ex = _regex_extract(text, self.model, ORDERS)
                self.assertIsNone(ex.affected_supplier)
                self.assertIsNone(ex.delay_hours)

    def test_delayed_supplier_still_named(self):
        ex = _regex_extract("Hosur Precision Castings delayed 10 hours. Chennai Precision Casings no delay. "
                            "EV-402 250 units short", self.model, ORDERS)
        self.assertEqual(ex.delay_hours, 10)
        self.assertIsNotNone(ex.affected_supplier)


if __name__ == "__main__":
    unittest.main()
