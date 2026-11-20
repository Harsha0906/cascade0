"""Sourcing Agent tests (offline: simulated channel, regex reply parsing, in-memory DB)."""

import dataclasses
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from fastapi.testclient import TestClient

from app import main, run_store
from app.agents import sourcing, sourcing_store
from app.agents.sourcing import RFQ, _regex_parse
from app.db import update_rows

KEY = {"X-API-Key": "test-operator-key"}


def _rfq(units=150):
    return RFQ(id="R", run_id="X", round=1, supplier_id="SUP-PNY-02", supplier_name="Peenya",
               units_requested=units, expected_unit_price_inr=600, needed_within_hours=34, channel="simulated")


class RfqWordingTests(unittest.TestCase):
    def test_flat_fee_vendor_rfq_is_not_an_air_charter(self):
        from tests.factories import small_factory
        model = small_factory()
        rfq = RFQ(id="R", run_id="X", round=1, supplier_id="V3", supplier_name="Vendor V3",
                  units_requested=120, expected_unit_price_inr=0, needed_within_hours=20, channel="simulated")
        text = sourcing._rfq_text(model, rfq)
        self.assertIn("flat fee", text)
        self.assertNotIn("air charter", text)
        self.assertIn("120 Widget", text)


class ReplyParsingTests(unittest.TestCase):
    def test_english_and_hinglish_replies(self):
        cases = {
            "YES 150 pcs @600 in 4h": (False, 150, 600, 4.0),
            "haan 120 pcs de denge, rate 650, kal tak": (False, 120, 650, 24.0),
            "can do 80 units by 6 hrs @ Rs 700": (False, 80, 700, 6.0),
            "ok": (False, 150, None, None),
            "No, out of stock": (True, 0, None, None),
            "sorry bhai nahi hoga": (True, 0, None, None),
        }
        for text, (declined, units, price, eta) in cases.items():
            with self.subTest(text=text):
                o = _regex_parse(text, _rfq())
                self.assertEqual((o.declined, o.available_units, o.unit_price_inr, o.eta_hours),
                                 (declined, units, price, eta))

    def test_unintelligible_reply_is_not_treated_as_yes(self):
        o = _regex_parse("call me later", _rfq())
        self.assertTrue(o.declined)


class SourcingFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls._patches = [
            mock.patch.object(main, "send_whatsapp_text", lambda *a, **k: True),
            mock.patch.object(main, "send_whatsapp_interactive_buttons", lambda *a, **k: True),
        ]
        for p in cls._patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()

    def setUp(self):
        self.client.post("/api/v1/reset", headers=KEY)

    def _simulate(self, scenario=1):
        r = self.client.post("/api/v1/simulate-crisis", json={"scenario_id": scenario}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _start(self, run_id):
        r = self.client.post("/api/v1/sourcing/start", json={"run_id": run_id}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _reply(self, run_id, supplier_id, text):
        r = self.client.post(f"/api/v1/sourcing/{run_id}/vendor-reply",
                             json={"supplier_id": supplier_id, "text": text}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_full_confirmation_completes_with_confirmed_plan(self):
        sim = self._simulate(1)
        s = self._start(sim["run_id"])
        self.assertEqual(s["status"], "ACTIVE")
        self.assertEqual([r["supplier_id"] for r in s["rfqs"]], ["SUP-PNY-02"])
        s = self._reply(sim["run_id"], "SUP-PNY-02", "YES 150 pcs @600 in 4h")
        self.assertEqual(s["status"], "COMPLETE")
        winner = next(p for p in s["playbooks"] if p["id"] == s["recommended_plan_id"])
        self.assertTrue(all(a["confirmed"] for a in winner["vendor_allocations"]))

    def test_sourcing_uses_the_runs_factory_snapshot(self):
        sim = self._simulate(1)
        # Vendor data changes after the analysis: the enquiry must still match the analysed plan.
        update_rows("suppliers", "id", "SUP-PNY-02", {"extra_cost_per_unit_inr": 999})
        s = self._start(sim["run_id"])
        rfq = s["rfqs"][0]
        self.assertEqual((rfq["supplier_id"], rfq["expected_unit_price_inr"]), ("SUP-PNY-02", 600))
        session = sourcing_store.load(sim["run_id"])
        self.assertEqual(session.model, run_store.get_run(sim["run_id"])["factory_model"])
        self.assertEqual(session.params["line_speeds"], run_store.get_run(sim["run_id"])["line_speeds"])

    def test_rfq_deadline_uses_the_factory_qa_time(self):
        sim = self._simulate(1)
        run = run_store.get_run(sim["run_id"])
        run["factory_model"] = dataclasses.replace(run["factory_model"], qa_dispatch_hours=5.0)
        run_store.save_run(run)
        s = self._start(sim["run_id"])
        deadline = sourcing_store.load(sim["run_id"]).params["deadline_hours"]
        self.assertEqual(s["rfqs"][0]["needed_within_hours"], round(deadline - 5.0 - 1, 1))

    def test_session_not_registered_when_first_rfq_fails(self):
        sim = self._simulate(1)
        with mock.patch.object(sourcing, "_send_rfq", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                sourcing.start_sourcing(sim["run_id"])
        self.assertIsNone(sourcing_store.load(sim["run_id"]))
        s = self._start(sim["run_id"])  # a retry starts cleanly
        self.assertEqual(s["status"], "ACTIVE")

    def test_partial_offer_triggers_replan_and_new_enquiry(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        s = self._reply(sim["run_id"], "SUP-PNY-02", "haan 100 pcs only, rate 620, 5 hours")
        self.assertEqual(s["status"], "ACTIVE")
        self.assertEqual(s["round"], 2)
        open_rfq = next(r for r in s["rfqs"] if r["status"] == "SENT")
        self.assertEqual((open_rfq["supplier_id"], open_rfq["units_requested"]), ("SUP-HSR-03", 50))
        s = self._reply(sim["run_id"], "SUP-HSR-03", "yes 50 units @850 in 8h")
        self.assertEqual(s["status"], "COMPLETE")
        winner = next(p for p in s["playbooks"] if p["id"] == s["recommended_plan_id"])
        units = {a["supplier_id"]: a["units_allocated"] for a in winner["vendor_allocations"]}
        self.assertEqual(units, {"SUP-PNY-02": 100, "SUP-HSR-03": 50})
        peenya = next(a for a in winner["vendor_allocations"] if a["supplier_id"] == "SUP-PNY-02")
        self.assertEqual(peenya["cost_per_unit_inr"], 620)  # confirmed price replaces the catalogue price

    def test_decline_changes_the_decision(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        s = self._reply(sim["run_id"], "SUP-PNY-02", "NO, out of stock")
        self.assertIn("SUP-HSR-03", [r["supplier_id"] for r in s["rfqs"] if r["status"] == "SENT"])
        s = self._reply(sim["run_id"], "SUP-HSR-03", "sorry nahi hoga")
        # Both regional vendors out → agent asks the air charter next.
        self.assertIn("SUP-AIR-04", [r["supplier_id"] for r in s["rfqs"] if r["status"] == "SENT"])
        s = self._reply(sim["run_id"], "SUP-AIR-04", "NO")
        self.assertEqual(s["status"], "COMPLETE")
        self.assertEqual(s["recommended_plan_id"], "PLAN_C")  # renegotiation once no vendor can supply

    def test_timeout_drops_vendor(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        session = sourcing_store.load(sim["run_id"])
        session.rfqs[0].sent_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        sourcing_store.save(session)
        s = self.client.get(f"/api/v1/sourcing/{sim['run_id']}").json()
        self.assertEqual(s["rfqs"][0]["status"], "NO_REPLY")
        self.assertEqual(s["round"], 2)

    def test_sourced_run_executes_once_across_parent_and_child(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        s = self._reply(sim["run_id"], "SUP-PNY-02", "YES 150 pcs @600 in 4h")
        sourced = s["sourced_run_id"]
        r = self.client.post("/api/v1/execute-plan",
                             json={"run_id": sourced, "playbook_id": s["recommended_plan_id"]}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        again = self.client.post("/api/v1/execute-plan",
                                 json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]}, headers=KEY)
        self.assertEqual(again.status_code, 409)  # the original run cannot create a second PO

    def test_reply_needs_open_enquiry_and_api_key(self):
        sim = self._simulate(1)
        self._start(sim["run_id"])
        r = self.client.post(f"/api/v1/sourcing/{sim['run_id']}/vendor-reply",
                             json={"supplier_id": "SUP-HSR-03", "text": "yes"}, headers=KEY)
        self.assertEqual(r.status_code, 409)
        r = self.client.post(f"/api/v1/sourcing/{sim['run_id']}/vendor-reply",
                             json={"supplier_id": "SUP-PNY-02", "text": "yes"})
        self.assertEqual(r.status_code, 401)

    def test_plan_without_vendors_needs_no_sourcing(self):
        sim = self._simulate(2)  # overtime + safety stock wins
        s = self._start(sim["run_id"])
        self.assertEqual(s["status"], "NOTHING_TO_SOURCE")

    def test_whatsapp_reply_from_vendor_is_routed_to_agent(self):
        update_rows("suppliers", "id", "SUP-PNY-02", {"whatsapp_number": "+91 98450 00001"})
        sim = self._simulate(1)
        self._start(sim["run_id"])
        body = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": [{
            "from": "919845000001", "type": "text", "text": {"body": "YES 150 pcs @600 in 4h"}}]}}]}]}
        raw = json.dumps(body).encode()
        sig = "sha256=" + hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()
        r = self.client.post("/api/v1/webhooks/whatsapp", content=raw,
                             headers={"content-type": "application/json", "x-hub-signature-256": sig})
        self.assertEqual(r.json()["action"], "vendor_reply_recorded")
        self.assertEqual(sourcing.view(sim["run_id"])["status"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
