from tests import _offline_env  # noqa: F401  (must precede any app import)

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import db, main, run_store
from app.agents import client as client_agent
from app.agents import sourcing
from app.agents.sourcing import RFQ, _regex_parse
from tests.test_client_agent import KEY, PIN, SLOW, _add_slow_vendor


def _rfq(units=300):
    return RFQ(id="R", run_id="X", round=1, supplier_id="SUP-PNY-02", supplier_name="Peenya",
               units_requested=units, expected_unit_price_inr=600, needed_within_hours=34, channel="simulated")


class I1PlainEnglishDeclines(unittest.TestCase):
    """Final review I-1: the reviewer's probe texts must all read as declines."""

    def test_review_probes_are_declines(self):
        for text in ("won't be able to do 300 units", "will not manage 300 units",
                     "We won't make it, 300 units", "Yes but unable for 300 units",
                     "can do 300 units but not in 34 hrs", "not able to supply 300 units",
                     "can't manage 300 units", "cannot supply 300 units", "No way, 300 units is too many",
                     "Ok but we cant do 300 units"):
            with self.subTest(text=text):
                o = _regex_parse(text, _rfq())
                self.assertTrue(o.declined, o)
                self.assertEqual(o.available_units, 0)

    def test_explicit_partial_offer_still_counts(self):
        for text, units in (("won't manage 300, only 120 units", 120),
                            ("unable to do 300 units, 80 units only", 80),
                            ("sorry, only 100 units available", 100),
                            ("Can't do 150 but can do 60 units at ₹650 in 6 hours", 60)):
            with self.subTest(text=text):
                o = _regex_parse(text, _rfq())
                self.assertFalse(o.declined, o)
                self.assertEqual(o.available_units, units)

    def test_plain_acceptances_unchanged(self):
        for text in ("Yes, can supply 300 units at ₹620 per unit, delivery in 6 hours", "ok", "confirmed"):
            with self.subTest(text=text):
                o = _regex_parse(text, _rfq())
                self.assertFalse(o.declined, o)
                self.assertEqual(o.available_units, 300)


class _Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = TestClient(main.app)

    def setUp(self):
        self.api.post("/api/v1/reset", headers=KEY)
        db.update_rows("orders", "order_id", "EV-402", {"due_at": (PIN + timedelta(hours=38)).isoformat()})
        p = mock.patch.object(client_agent, "_now", lambda: PIN)
        p.start()
        self.addCleanup(p.stop)

    def _post(self, path, body, code=200):
        r = self.api.post(path, json=body, headers=KEY)
        self.assertEqual(r.status_code, code, r.text)
        return r.json()

    def _reply(self, run_id, supplier_id, text):
        return self._post(f"/api/v1/sourcing/{run_id}/vendor-reply", {"supplier_id": supplier_id, "text": text})

    def _accepted_extension(self):
        """Scenario 1 → every vendor declines → draft → approve → client ACCEPTS (slow vendor asked)."""
        _add_slow_vendor()
        run_id = self._post("/api/v1/simulate-crisis", {"scenario_id": 1})["run_id"]
        self._post("/api/v1/sourcing/start", {"run_id": run_id})
        self._reply(run_id, "SUP-PNY-02", "NO, out of stock")
        self._reply(run_id, "SUP-HSR-03", "sorry nahi hoga")
        self._reply(run_id, "SUP-AIR-04", "NO")
        self._post("/api/v1/client/approve", {"run_id": run_id, "approved_by": "ops-lead@apex"})
        c = self._post("/api/v1/client/answer", {"run_id": run_id, "accepted": True, "text": "OK"})
        self.assertEqual(c["status"], "ACCEPTED")
        return run_id, c


class I2NoSecondFreeExtension(_Flow):
    def test_replan_after_acceptance_has_no_renegotiation_plan(self):
        run_id, c = self._accepted_extension()
        replan = run_store.get_run(c["replan_run_id"])
        self.assertNotIn("SLA_RENEGOTIATION", [p["strategy_type"] for p in replan["playbooks"]])

    def test_accept_then_vendor_declines_is_not_a_certain_plan_c(self):
        run_id, _ = self._accepted_extension()
        s = self._reply(run_id, SLOW, "Sorry, not available")
        self.assertEqual(s["status"], "COMPLETE")
        winner = next(p for p in s["playbooks"] if p["id"] == s["recommended_plan_id"])
        self.assertFalse(winner["strategy_type"] == "SLA_RENEGOTIATION" and winner["confidence_pct"] == 100.0,
                         winner)
        self.assertNotIn("SLA_RENEGOTIATION", [p["strategy_type"] for p in s["playbooks"]])
        # The Client Agent drafted a follow-up request, keeping the first one in its history.
        c = client_agent.view(run_id)
        self.assertEqual(c["status"], "DRAFTED")
        self.assertEqual(c["drafted_by"], "sourcing_failure")
        self.assertEqual(c["request_number"], 2)
        self.assertEqual([h["status"] for h in c["history"]], ["ACCEPTED"])
        self.assertIsNone(c["answer"])
        self.assertIsNone(c.get("replan_run_id"))
        # The follow-up starts from the already-extended deadline.
        self.assertEqual(c["original_due_at"], c["history"][0]["new_due_at"])
        # No duplicate while the follow-up is open.
        self.assertIsNone(client_agent.on_sourcing_failed(run_id))
        self.assertEqual(client_agent.view(run_id)["version"], c["version"])

    def test_follow_up_can_be_sent_and_answered(self):
        run_id, _ = self._accepted_extension()
        self._reply(run_id, SLOW, "Sorry, not available")
        self._post("/api/v1/client/approve", {"run_id": run_id, "approved_by": "ops-lead@apex"})
        c = self._post("/api/v1/client/answer", {"run_id": run_id, "accepted": False, "text": "No more"})
        self.assertEqual(c["status"], "REFUSED")
        self.assertEqual(c["replan_run_id"], f"{run_id}-C2")
        self.assertEqual(len(c["outbox"]), 2)


class I3ConfirmedEtaBeatsTheRiskShift(unittest.TestCase):
    def test_blocked_route_vendor_confirming_a_short_eta_is_not_floored(self):
        from app.disruption import ResolvedDisruption, risk_adjusted_model
        from app.factory_model import load_factory_model
        from app.solver import simulate_monte_carlo
        base = load_factory_model()
        hsr = base.vendor("SUP-HSR-03")
        adj = risk_adjusted_model(base, ResolvedDisruption(
            delay_hours=30, line_impacts=(), supplier_id="SUP-CHN-01", order_id="EV-402",
            shortfall_units=150, headline="x", blocked_route=hsr.route, weather_alert=False))
        self.assertEqual(adj.vendor("SUP-HSR-03").min_lead_hours, hsr.min_lead_hours + 30)
        session = sourcing.SourcingSession(run_id="X", playbook_id="PLAN_B", params={}, model=adj)
        session.rfqs.append(RFQ(id="R1", run_id="X", round=1, supplier_id="SUP-HSR-03", supplier_name="Hosur",
                                units_requested=150, expected_unit_price_inr=600, needed_within_hours=30,
                                channel="simulated"))
        with mock.patch.object(sourcing, "_persist", lambda r: None), \
                mock.patch.object(sourcing, "_advance", lambda s: None), \
                mock.patch.object(sourcing, "log_agent_step", lambda **k: None):
            sourcing._apply_reply(session, "SUP-HSR-03", "Yes 150 units in 12 hours", "operator")
        o = session.overrides["SUP-HSR-03"]
        self.assertEqual(o["lead_hours"], 12.0)
        self.assertEqual(o["min_lead_hours"], 12.0)
        sourced = adj.with_vendor_overrides(session.overrides)
        for deadline in (20, 30):
            mc = simulate_monte_carlo(sourced, "REGIONAL_BALANCED_OT", {"SUP-HSR-03": 150}, 0, deadline)
            self.assertGreater(mc["confidence_pct"], 50.0, (deadline, mc))

    def test_confirmed_eta_longer_than_min_lead_keeps_the_min_lead(self):
        from app.factory_model import load_factory_model
        m = load_factory_model()
        pny = m.vendor("SUP-PNY-02")
        session = sourcing.SourcingSession(run_id="X", playbook_id="PLAN_B", params={}, model=m)
        session.rfqs.append(RFQ(id="R1", run_id="X", round=1, supplier_id="SUP-PNY-02", supplier_name="Peenya",
                                units_requested=150, expected_unit_price_inr=600, needed_within_hours=30,
                                channel="simulated"))
        with mock.patch.object(sourcing, "_persist", lambda r: None), \
                mock.patch.object(sourcing, "_advance", lambda s: None), \
                mock.patch.object(sourcing, "log_agent_step", lambda **k: None):
            sourcing._apply_reply(session, "SUP-PNY-02", "Yes 150 units in 20 hours", "operator")
        self.assertEqual(session.overrides["SUP-PNY-02"]["min_lead_hours"], min(pny.min_lead_hours, 20.0))


class I4PromiseIsTheVendorsOwn(_Flow):
    def _execute(self, run_id):
        run = run_store.get_run(run_id)
        r = self.api.post("/api/v1/execute-plan", headers=KEY,
                          json={"run_id": run_id, "playbook_id": run["recommended_plan_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        return datetime.fromisoformat(r.json()["executed_at"])

    def _promised_hours(self, executed, supplier_id):
        o = next(o for o in db.get_delivery_outcomes(status="PENDING") if o["supplier_id"] == supplier_id)
        return (datetime.fromisoformat(o["promised_at"]) - executed).total_seconds() / 3600

    def test_confirmed_eta_is_the_promise(self):
        run_id = self._post("/api/v1/simulate-crisis", {"scenario_id": 1})["run_id"]
        self._post("/api/v1/sourcing/start", {"run_id": run_id})
        s = self._reply(run_id, "SUP-PNY-02", "YES 150 pcs @600 in 9h")
        self.assertEqual(s["status"], "COMPLETE")
        executed = self._execute(s["sourced_run_id"])
        self.assertAlmostEqual(self._promised_hours(executed, "SUP-PNY-02"), 9.0, places=2)

    def test_without_a_confirmed_eta_the_unshifted_live_lead_is_the_promise(self):
        from app.disruption import ResolvedDisruption, risk_adjusted_model
        from app.factory_model import load_factory_model
        sim = self._post("/api/v1/simulate-crisis", {"scenario_id": 1})
        run = run_store.get_run(sim["run_id"])
        live = load_factory_model()
        pny = live.vendor("SUP-PNY-02")
        run["factory_model"] = risk_adjusted_model(run["factory_model"], ResolvedDisruption(
            delay_hours=30, line_impacts=(), supplier_id="SUP-CHN-01", order_id="EV-402",
            shortfall_units=150, headline="x", blocked_route=pny.route, weather_alert=False))
        self.assertEqual(run["factory_model"].vendor("SUP-PNY-02").lead_hours, pny.lead_hours + 30)
        run_store.save_run(run)
        play = next(p for p in run["playbooks"] if p["id"] == run["recommended_plan_id"])
        self.assertIn("SUP-PNY-02", [a["supplier_id"] for a in play["vendor_allocations"]])
        executed = self._execute(sim["run_id"])
        self.assertAlmostEqual(self._promised_hours(executed, "SUP-PNY-02"), pny.lead_hours, places=2)


class FutureDeliveryIsRejected(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        self.api = TestClient(main.app)
        now = datetime.now(timezone.utc)
        db.insert_row("delivery_outcomes", {
            "id": len(db._mirror.delivery_outcomes) + 1, "factory_id": "apex-volt-blr2",
            "supplier_id": "SUP-HSR-03", "po_number": "PO-FUT", "units": 10,
            "promised_at": (now - timedelta(hours=5)).isoformat(), "delivered_at": None, "status": "PENDING",
            "recorded_at": now.isoformat()})

    def _record(self, delivered):
        return self.api.post("/api/v1/deliveries", headers=KEY, json={
            "po_number": "PO-FUT", "supplier_id": "SUP-HSR-03", "delivered_at": delivered.isoformat()})

    def test_more_than_an_hour_ahead_is_422_and_changes_nothing(self):
        r = self._record(datetime.now(timezone.utc) + timedelta(hours=2))
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("future", r.json()["detail"])
        self.assertEqual(db.get_delivery_outcomes(status="PENDING")[0]["po_number"], "PO-FUT")

    def test_within_the_hour_is_accepted(self):
        self.assertEqual(self._record(datetime.now(timezone.utc) + timedelta(minutes=30)).status_code, 200)


class GeminiVendorReplyIsGrounded(unittest.TestCase):
    def _gemini(self, text, payload, units=150):
        import json
        resp = mock.Mock(text=json.dumps(payload), usage_metadata=None)
        fake = mock.Mock(has_gemini=True, GEMINI_API_KEY="k", GEMINI_MODEL="m")
        with mock.patch.object(sourcing, "settings", fake), mock.patch("google.genai.Client") as client:
            client.return_value.models.generate_content.return_value = resp
            return sourcing.parse_vendor_reply(text, _rfq(units))

    def test_numbers_copied_from_the_prompt_are_dropped(self):
        o, by = self._gemini("Yes we can supply 150 units",
                             {"declined": False, "available_units": 150, "unit_price_inr": 600, "eta_hours": 34})
        self.assertTrue(by.startswith("gemini"))
        self.assertEqual((o.declined, o.available_units, o.unit_price_inr, o.eta_hours), (False, 150, None, None))

    def test_stated_numbers_are_kept(self):
        o, _ = self._gemini("Haan ji, 120 pcs @ 1,250, 2 din",
                            {"declined": False, "available_units": 120, "unit_price_inr": 1250, "eta_hours": 48})
        self.assertEqual((o.declined, o.available_units, o.unit_price_inr, o.eta_hours), (False, 120, 1250, 48))

    def test_acceptance_without_quantity_defaults_to_requested(self):
        o, _ = self._gemini("ok, confirmed", {"declined": False, "available_units": 150}, units=150)
        self.assertEqual((o.declined, o.available_units), (False, 150))

    def test_invented_quantity_goes_to_operator_review(self):
        o, _ = self._gemini("we will check and revert",
                            {"declined": False, "available_units": 90, "unit_price_inr": None, "eta_hours": None})
        self.assertTrue(o.declined)
        self.assertEqual(o.available_units, 0)
        self.assertIn("operator review", o.notes)

    def test_regex_decline_cue_vetoes_a_gemini_acceptance(self):
        o, _ = self._gemini("won't be able to do 300 units",
                            {"declined": False, "available_units": 300}, units=300)
        self.assertTrue(o.declined)


if __name__ == "__main__":
    unittest.main()
