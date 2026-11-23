"""Client Agent tests (offline: simulated channel, in-memory DB, pinned clock)."""

import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_HEADERS, dev_client  # noqa: F401
from fastapi.testclient import TestClient

from app import db, main, run_store
from app.agents import client as client_agent
from app.agents import sourcing, sourcing_store
from app.config import settings
from app.deadlines import parse_timestamp

KEY = DEV_HEADERS  # dev-owner@example.test (AUTH_MODE=dev)
# Pinned clock for the Client Agent (whole hour, so the quoted deadlines are exact).
PIN = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _fmt(dt):
    return dt.strftime("%d %b %Y %H:%M UTC")
SLOW = "SUP-MYS-05"


def _add_slow_vendor():
    """A cheap BACKUP vendor whose 60h lead time cannot meet the 38h deadline (it can meet 86h)."""
    row = copy.deepcopy(db.get_supplier("SUP-PNY-02"))
    row.update(id=SLOW, name="Mysuru Bulk Castings", route="Mysuru Road (140 km)", tier="TIER-3",
               extra_cost_per_unit_inr=300, lead_time_hours=60, min_lead_hours=50,
               lead_time_sigma_hours=2.0, max_available_qty=200)
    db.upsert_row("suppliers", row)
    db.upsert_row("vendor_history", {
        "id": 5, "supplier_id": SLOW, "past_orders_count": 20, "on_time_deliveries": 18,
        "reliability_score_pct": 90.0, "quality_rejection_rate_pct": 1.0,
        "last_incident_note": "Slow road freight from Mysuru; cheapest casings."})


class ClientAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = dev_client(main.app)

    def setUp(self):
        self.api.post("/api/v1/reset", headers=KEY)
        db.update_rows("orders", "order_id", "EV-402", {"due_at": (PIN + timedelta(hours=38)).isoformat()})
        p = mock.patch.object(client_agent, "_now", lambda: PIN)
        p.start()
        self.addCleanup(p.stop)

    # ── helpers ──
    def _simulate(self, scenario=1):
        r = self.api.post("/api/v1/simulate-crisis", json={"scenario_id": scenario}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _reply(self, run_id, supplier_id, text):
        r = self.api.post(f"/api/v1/sourcing/{run_id}/vendor-reply",
                          json={"supplier_id": supplier_id, "text": text}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _fail_sourcing(self, run_id):
        """Start sourcing on the cost plan and have every vendor decline."""
        r = self.api.post("/api/v1/sourcing/start", json={"run_id": run_id}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([x["supplier_id"] for x in r.json()["rfqs"]], ["SUP-PNY-02"])
        self._reply(run_id, "SUP-PNY-02", "NO, out of stock")
        self._reply(run_id, "SUP-HSR-03", "sorry nahi hoga")
        s = self._reply(run_id, "SUP-AIR-04", "NO")
        self.assertEqual(s["status"], "COMPLETE")
        self.assertEqual(s["recommended_plan_id"], "PLAN_C")
        return s

    def _client(self, run_id):
        r = self.api.get(f"/api/v1/client/{run_id}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _approve(self, run_id, who="ops-lead@apex"):
        return self.api.post("/api/v1/client/approve", json={"run_id": run_id, "approved_by": who}, headers=KEY)

    def _answer(self, run_id, accepted, **extra):
        return self.api.post("/api/v1/client/answer",
                             json={"run_id": run_id, "accepted": accepted, **extra}, headers=KEY)

    # ── Done-when ──
    def test_accepted_extension_changes_enquiries_and_final_plan(self):
        _add_slow_vendor()
        sim = self._simulate(1)
        self.assertEqual(sim["recommended_plan_id"], "PLAN_B")
        run_id = sim["run_id"]
        before = self._fail_sourcing(run_id)
        asked_before = {(x["supplier_id"], x["units_requested"]) for x in before["rfqs"]}
        self.assertNotIn(SLOW, {sid for sid, _ in asked_before})

        # 1. Sourcing failed → the Client Agent drafted an extension request on its own.
        c = self._client(run_id)
        self.assertEqual(c["status"], "DRAFTED")
        self.assertEqual(c["drafted_by"], "sourcing_failure")
        self.assertEqual(c["extension_hours"], 48)   # the run's upstream delay
        msg = c["draft_message"]
        for fact in ("EV-402", "Ather-Grid Mobility Corp", "Chennai Precision Casings Ltd +48h", "₹500,000",
                     _fmt(PIN + timedelta(hours=38)), _fmt(PIN + timedelta(hours=86))):
            self.assertIn(fact, msg)
        self.assertEqual(c["outbox"], [])

        r = self._approve(run_id)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "SENT")
        self.assertEqual(len(r.json()["outbox"]), 1)

        r = self._answer(run_id, True, text="OK, 48h extension accepted with the delay fee")
        self.assertEqual(r.status_code, 200, r.text)
        c = r.json()
        self.assertEqual(c["status"], "ACCEPTED")
        # The order's absolute deadline moved by 48h.
        self.assertEqual(parse_timestamp(db.get_order("EV-402")["due_at"]), PIN + timedelta(hours=86))
        # 2. The re-plan uses the longer deadline: the slow vendor is now feasible and asked.
        replan = run_store.get_run(c["replan_run_id"])
        self.assertEqual(replan["parent_run_id"], run_id)
        self.assertEqual(replan["solver_result"]["deadline_hours"], 86.0)
        # The extension is granted: "ask for an extension" is no longer a plan (final review I-2).
        self.assertNotIn("SLA_RENEGOTIATION", [p["strategy_type"] for p in replan["playbooks"]])
        s = sourcing.view(run_id)
        self.assertEqual(s["status"], "ACTIVE")
        open_rfqs = [x for x in s["rfqs"] if x["status"] == "SENT"]
        self.assertEqual([(x["supplier_id"], x["units_requested"]) for x in open_rfqs], [(SLOW, 150)])
        self.assertNotIn((SLOW, 150), asked_before)
        self.assertEqual(open_rfqs[0]["needed_within_hours"], 82.5)

        # 3. The final recommended plan differs from before.
        s = self._reply(run_id, SLOW, "YES 150 pcs @300 in 60h")
        self.assertEqual(s["status"], "COMPLETE")
        self.assertNotEqual(s["recommended_plan_id"], before["recommended_plan_id"])
        winner = next(p for p in s["playbooks"] if p["id"] == s["recommended_plan_id"])
        self.assertEqual({a["supplier_id"]: a["units_allocated"] for a in winner["vendor_allocations"]},
                         {SLOW: 150})
        self.assertNotEqual(s["sourced_run_id"], before["sourced_run_id"])
        # The new round ended covered: no second auto-draft; the record stays ACCEPTED.
        self.assertEqual(self._client(run_id)["status"], "ACCEPTED")

    def test_refused_extension_widens_sourcing_to_the_expedite_vendor(self):
        sim = self._simulate(1)
        run_id = sim["run_id"]
        self._fail_sourcing(run_id)
        self.assertEqual(self._approve(run_id).status_code, 200)
        due_before = db.get_order("EV-402")["due_at"]
        r = self._answer(run_id, False, text="No extension possible")
        self.assertEqual(r.status_code, 200, r.text)
        c = r.json()
        self.assertEqual(c["status"], "REFUSED")
        self.assertEqual(db.get_order("EV-402")["due_at"], due_before)
        replan = run_store.get_run(c["replan_run_id"])
        plan_c = next(p for p in replan["playbooks"] if p["id"] == "PLAN_C")
        self.assertEqual(plan_c["confidence_pct"], 0.0)
        self.assertEqual(c["sourcing_target_plan_id"], "PLAN_A")
        s = sourcing.view(run_id)
        self.assertEqual(s["status"], "ACTIVE")
        open_ids = [x["supplier_id"] for x in s["rfqs"] if x["status"] == "SENT"]
        self.assertIn("SUP-AIR-04", open_ids)
        self.assertEqual(max(x["round"] for x in s["rfqs"]), 4)

    # ── Review Focus 3 ──
    def test_answer_before_approval_twice_or_conflicting_is_409(self):
        sim = self._simulate(1)
        run_id = sim["run_id"]
        r = self.api.post("/api/v1/client/draft", json={"run_id": run_id, "extension_hours": 24}, headers=KEY)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._answer(run_id, True).status_code, 409)   # not approved yet
        self.assertEqual(self._approve(run_id).status_code, 200)
        self.assertEqual(self._approve(run_id).status_code, 409)        # already sent
        self.assertEqual(self._answer(run_id, True).status_code, 200)
        self.assertEqual(self._answer(run_id, True).status_code, 409)   # duplicate
        self.assertEqual(self._answer(run_id, False).status_code, 409)  # conflicting
        self.assertEqual(self._client(run_id)["status"], "ACCEPTED")
        # Only one extension was applied.
        self.assertEqual(parse_timestamp(db.get_order("EV-402")["due_at"]), PIN + timedelta(hours=62))

    def test_answer_without_any_request_is_409_and_unknown_run_404(self):
        sim = self._simulate(1)
        self.assertEqual(self._answer(sim["run_id"], True).status_code, 409)
        self.assertEqual(self.api.get("/api/v1/client/RUN-NOPE").status_code, 404)
        r = self.api.post("/api/v1/client/draft", json={"run_id": "RUN-NOPE", "extension_hours": 5}, headers=KEY)
        self.assertEqual(r.status_code, 404)

    def test_draft_validation_and_api_key(self):
        sim = self._simulate(1)
        r = self.api.post("/api/v1/client/draft", json={"run_id": sim["run_id"], "extension_hours": 0}, headers=KEY)
        self.assertEqual(r.status_code, 422)
        with self.assertRaises(client_agent.ClientAgentError) as cm:
            client_agent.draft_extension(sim["run_id"], -3)
        self.assertEqual(cm.exception.status_code, 422)
        anon = TestClient(main.app)  # no credentials
        r = anon.post("/api/v1/client/draft", json={"run_id": sim["run_id"], "extension_hours": 5})
        self.assertEqual(r.status_code, 401)
        r = anon.post("/api/v1/client/approve", json={"run_id": sim["run_id"], "approved_by": "x"})
        self.assertEqual(r.status_code, 401)
        r = anon.post("/api/v1/client/answer", json={"run_id": sim["run_id"], "accepted": True})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self._approve(sim["run_id"]).status_code, 404)  # nothing drafted

    def test_new_deadline_hours_counter_offer(self):
        sim = self._simulate(1)
        run_id = sim["run_id"]
        client_agent.draft_extension(run_id, 48)
        client_agent.approve_extension(run_id, "ops-lead")
        r = self._answer(run_id, True, new_deadline_hours=20)   # earlier than today's deadline
        self.assertEqual(r.status_code, 422)
        r = self._answer(run_id, True, new_deadline_hours=60)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(parse_timestamp(db.get_order("EV-402")["due_at"]), PIN + timedelta(hours=60))
        self.assertEqual(run_store.get_run(r.json()["replan_run_id"])["solver_result"]["deadline_hours"], 60.0)

    # ── Review Focus 4 ──
    def test_no_duplicate_draft_when_request_already_open(self):
        sim = self._simulate(1)
        run_id = sim["run_id"]
        client_agent.draft_extension(run_id, 24, reason="operator asked first")
        version = client_agent.view(run_id)["version"]
        self._fail_sourcing(run_id)
        c = self._client(run_id)
        self.assertEqual((c["drafted_by"], c["extension_hours"], c["version"]), ("operator", 24, version))
        # Also once sent: still no new draft.
        client_agent.approve_extension(run_id, "ops-lead")
        self.assertIsNone(client_agent.on_sourcing_failed(run_id))
        self.assertEqual(self._client(run_id)["status"], "SENT")

    def test_covered_sourcing_does_not_draft(self):
        sim = self._simulate(1)
        self.api.post("/api/v1/sourcing/start", json={"run_id": sim["run_id"]}, headers=KEY)
        self._reply(sim["run_id"], "SUP-PNY-02", "YES 150 pcs @600 in 4h")
        self.assertEqual(self.api.get(f"/api/v1/client/{sim['run_id']}").status_code, 404)

    # ── Human sign-off ──
    def test_no_outbound_message_before_approval(self):
        sent = mock.Mock(return_value=True)
        with mock.patch.object(client_agent.sourcing, "outbound_channel", return_value=mock.Mock(send_text=sent)), \
                mock.patch.object(settings, "SOURCING_MODE", "telegram"):
            sim = self._simulate(1)
            run_id = sim["run_id"]
            client_agent.draft_extension(run_id, 24)
            client_agent.draft_extension(run_id, 36)   # re-draft while DRAFTED is allowed
            self.assertEqual(client_agent.view(run_id)["extension_hours"], 36)
            sent.assert_not_called()
            self.assertEqual(client_agent.view(run_id)["outbox"], [])
            # Telegram mode needs the client's chat id on the order.
            with self.assertRaises(client_agent.ClientAgentError) as cm:
                client_agent.approve_extension(run_id, "ops-lead")
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("no client contact", str(cm.exception))
            sent.assert_not_called()
            self.assertEqual(client_agent.view(run_id)["status"], "DRAFTED")
            with self.assertRaises(client_agent.ClientAgentError) as cm:
                client_agent.approve_extension(run_id, "  ")
            self.assertEqual(cm.exception.status_code, 422)
            db.update_rows("orders", "order_id", "EV-402", {"client_contact": "telegram:8800001"})
            c = client_agent.approve_extension(run_id, "ops-lead")
            self.assertEqual(c["status"], "SENT")
            sent.assert_called_once()
            self.assertEqual(sent.call_args[0][0], "8800001")
            self.assertIn("EV-402", sent.call_args[0][1])

    def test_telegram_send_failure_keeps_draft(self):
        with mock.patch.object(client_agent.sourcing, "outbound_channel", return_value=mock.Mock(send_text=lambda *a, **k: False)), \
                mock.patch.object(settings, "SOURCING_MODE", "telegram"):
            sim = self._simulate(1)
            db.update_rows("orders", "order_id", "EV-402", {"client_contact": "telegram:8800001"})
            client_agent.draft_extension(sim["run_id"], 24)
            with self.assertRaises(client_agent.ClientAgentError) as cm:
                client_agent.approve_extension(sim["run_id"], "ops-lead")
            self.assertEqual(cm.exception.status_code, 502)
            self.assertEqual(client_agent.view(sim["run_id"])["status"], "DRAFTED")

    def test_sourced_child_run_maps_to_root_record(self):
        sim = self._simulate(1)
        s = self._fail_sourcing(sim["run_id"])
        child = s["sourced_run_id"]
        self.assertEqual(self._client(child)["root_run_id"], sim["run_id"])

    def test_record_survives_reload_and_uses_optimistic_concurrency(self):
        sim = self._simulate(1)
        client_agent.draft_extension(sim["run_id"], 24)
        rec = client_agent.load(sim["run_id"])
        stale = copy.deepcopy(rec)
        client_agent.save(rec)
        with self.assertRaises(client_agent.ConcurrentUpdateError):
            client_agent.save(stale)
        row = db.fetch_by_id("order_coordination", "root_run_id", sim["run_id"])
        self.assertEqual((row["order_id"], row["factory_id"], row["status"]), ("EV-402", "apex-volt-blr2", "DRAFTED"))

    def test_reset_clears_coordination(self):
        sim = self._simulate(1)
        client_agent.draft_extension(sim["run_id"], 24)
        self.api.post("/api/v1/reset", headers=KEY)
        self.assertEqual(db.fetch_all("order_coordination"), [])

    # ── Fix round 1 ──
    def test_answer_resumes_after_a_failed_side_effect(self):
        sim = self._simulate(1)
        run_id = sim["run_id"]
        self._fail_sourcing(run_id)
        self.assertEqual(self._approve(run_id).status_code, 200)
        real = sourcing.restart_with_plan
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise db.DatabaseError("update", "sourcing_sessions")
            return real(*a, **k)

        with mock.patch.object(sourcing, "restart_with_plan", flaky):
            r = self._answer(run_id, True)
            self.assertEqual(r.status_code, 503, r.text)
            rec = client_agent.view(run_id)
            self.assertEqual(rec["status"], "ANSWERING")
            self.assertTrue(rec["answer"]["accepted"])
            self.assertEqual(self._answer(run_id, False).status_code, 409)   # different answer
            r = self._answer(run_id, True)                                     # same answer resumes
            self.assertEqual(r.status_code, 200, r.text)
        c = r.json()
        self.assertEqual(c["status"], "ACCEPTED")
        self.assertEqual(c["replan_run_id"], f"{run_id}-C")
        self.assertTrue(c["sourcing_restarted"])
        self.assertEqual(parse_timestamp(db.get_order("EV-402")["due_at"]), PIN + timedelta(hours=86))
        s = sourcing.view(run_id)
        self.assertEqual(s["deadline_hours"], 86.0)                    # restarted on the new deadline
        self.assertEqual(s["sourced_run_id"], f"{run_id}-S4")          # exactly one restart round
        self.assertEqual(self._answer(run_id, True).status_code, 409)   # finished: duplicate

    def test_resume_does_not_restart_sourcing_twice(self):
        sim = self._simulate(1)
        run_id = sim["run_id"]
        self._fail_sourcing(run_id)
        client_agent.approve_extension(run_id, "ops-lead")
        real_save = client_agent.save
        state = {"fail": True}

        def save_fails_on_finalize(record):
            if state["fail"] and record["status"] == "ACCEPTED":
                state["fail"] = False
                raise db.DatabaseError("update", "order_coordination")
            return real_save(record)

        with mock.patch.object(client_agent, "save", save_fails_on_finalize):
            with self.assertRaises(db.DatabaseError):
                client_agent.record_client_answer(run_id, True)
        rounds_before = sourcing_store.load(run_id).round
        c = client_agent.record_client_answer(run_id, True)
        self.assertEqual(c["status"], "ACCEPTED")
        self.assertEqual(sourcing_store.load(run_id).round, rounds_before)   # no second restart
        self.assertEqual(parse_timestamp(db.get_order("EV-402")["due_at"]), PIN + timedelta(hours=86))

    def test_answer_and_sourcing_reply_concurrently_do_not_deadlock(self):
        import threading
        sim_a = self._simulate(1)
        run_a = sim_a["run_id"]
        self._fail_sourcing(run_a)
        client_agent.approve_extension(run_a, "ops-lead")
        sim_b = self._simulate(1)
        run_b = sim_b["run_id"]
        self.api.post("/api/v1/sourcing/start", json={"run_id": run_b}, headers=KEY)
        self._reply(run_b, "SUP-PNY-02", "NO")
        self._reply(run_b, "SUP-HSR-03", "NO")

        a_planning, b_in_sourcing = threading.Event(), threading.Event()
        real_plan, real_apply = client_agent.generate_playbooks, sourcing._apply_reply

        def plan(*a, **k):            # thread A, inside the answer
            a_planning.set()
            b_in_sourcing.wait(2)
            return real_plan(*a, **k)

        def apply(*a, **k):           # thread B, holding the sourcing lock
            a_planning.wait(2)
            b_in_sourcing.set()
            return real_apply(*a, **k)   # finishes uncovered → Client Agent hook

        errors = []

        def run(fn, *args):
            try:
                fn(*args)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with mock.patch.object(client_agent, "generate_playbooks", plan), \
                mock.patch.object(sourcing, "_apply_reply", apply):
            ta = threading.Thread(target=run, args=(client_agent.record_client_answer, run_a, True), daemon=True)
            tb = threading.Thread(target=run, args=(sourcing.record_reply, run_b, "SUP-AIR-04", "NO"), daemon=True)
            ta.start()
            tb.start()
            ta.join(10)
            tb.join(10)
        self.assertFalse(ta.is_alive() or tb.is_alive(), "deadlock between Client and Sourcing agents")
        self.assertEqual(errors, [])
        self.assertEqual(client_agent.view(run_a)["status"], "ACCEPTED")
        self.assertEqual(client_agent.view(run_b)["status"], "DRAFTED")

    def test_send_exception_reverts_to_draft(self):
        def boom(*a, **k):
            raise RuntimeError("socket closed")
        with mock.patch.object(client_agent.sourcing, "outbound_channel", return_value=mock.Mock(send_text=boom)), \
                mock.patch.object(settings, "SOURCING_MODE", "telegram"):
            sim = self._simulate(1)
            db.update_rows("orders", "order_id", "EV-402", {"client_contact": "telegram:8800001"})
            client_agent.draft_extension(sim["run_id"], 24)
            with self.assertRaises(client_agent.ClientAgentError) as cm:
                client_agent.approve_extension(sim["run_id"], "ops-lead")
            self.assertEqual(cm.exception.status_code, 502)
            self.assertEqual(client_agent.view(sim["run_id"])["status"], "DRAFTED")

    def test_refusal_without_feasible_expedite_plan_is_409(self):
        import dataclasses
        sim = self._simulate(1)
        run_id = sim["run_id"]
        run = run_store.get_run(run_id)
        model = run["factory_model"]
        slow_air = [dataclasses.replace(v, lead_hours=200.0, min_lead_hours=190.0)
                    if v.supplier_id == "SUP-AIR-04" else v for v in model.vendors]
        run["factory_model"] = dataclasses.replace(model, vendors=tuple(slow_air))
        run_store.save_run(run)
        client_agent.draft_extension(run_id, 24)
        client_agent.approve_extension(run_id, "ops-lead")
        r = self._answer(run_id, False)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("expedite", r.json()["detail"])
        self.assertEqual(client_agent.view(run_id)["status"], "SENT")   # nothing claimed

    def test_refusal_target_falls_back_to_cheapest_feasible_plan_with_expedite(self):
        from types import SimpleNamespace as NS

        def plan(pid, feasible, cost, vendors):
            return NS(id=pid, feasible=feasible, expected_cost_inr=cost,
                      vendor_allocations=[NS(supplier_id=v) for v in vendors])
        plans = [plan("PLAN_A", False, 10, ["AIR"]), plan("PLAN_B", True, 50, ["AIR", "PNY"]),
                 plan("PLAN_C", True, 5, []), plan("PLAN_X", True, 70, ["AIR"])]
        self.assertEqual(client_agent._refusal_target(plans, "AIR").id, "PLAN_B")
        plans[0].feasible = True
        self.assertEqual(client_agent._refusal_target(plans, "AIR").id, "PLAN_A")
        with self.assertRaises(client_agent.ClientAgentError):
            client_agent._refusal_target(plans, None)


class SolverAnswerTests(unittest.TestCase):
    def test_known_answer_replaces_heuristic(self):
        from app.solver import generate_playbooks
        from tests.factories import small_factory
        model = small_factory()
        kw = dict(model=model, shortfall_units=500, delay_hours=10, line_speeds={}, order_id="O",
                  sla_penalty_inr=1_000_000, partial_penalty_inr=100_000, deadline_hours=30, client="C")
        by_answer = {}
        for answer in (None, 1.0, 0.0):
            res = generate_playbooks(**kw, renegotiation_acceptance=answer)
            by_answer[answer] = next(p for p in res.playbooks if p.id == "PLAN_C")
        if by_answer[None].strategy_type != "SLA_RENEGOTIATION":
            self.skipTest("small_factory safety stock covers the shortfall")
        self.assertEqual(by_answer[1.0].confidence_pct, 100.0)
        self.assertEqual(by_answer[1.0].expected_cost_inr, 100_000)
        self.assertEqual(by_answer[0.0].confidence_pct, 0.0)
        self.assertEqual(by_answer[0.0].expected_cost_inr, 1_000_000)
        self.assertNotIn(by_answer[None].confidence_pct, (0.0, 100.0))
        with self.assertRaises(Exception):
            generate_playbooks(**kw, renegotiation_acceptance=1.5)


class CoordinationSchemaTests(unittest.TestCase):
    def test_migration_and_schema_define_order_coordination(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "supabase"
        for path in (root / "migrations" / "007_learning_and_coordination.sql", root / "schema.sql"):
            sql = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("CREATE TABLE IF NOT EXISTS order_coordination", sql)
                self.assertIn("root_run_id  TEXT PRIMARY KEY", sql)
                self.assertIn("ALTER TABLE order_coordination ENABLE ROW LEVEL SECURITY", sql)
        mig = (root / "migrations" / "007_learning_and_coordination.sql").read_text(encoding="utf-8")
        self.assertLess(mig.index("order_coordination"), mig.index("VALUES (7)"))


if __name__ == "__main__":
    unittest.main()
