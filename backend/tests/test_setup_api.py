"""Factory setup and data APIs (Round S Task 1): offline only, fake Telegram transport."""

import unittest
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_OWNER, DEV_VIEWER, OTHER_OWNER, dev_client
from tests.test_channels import TelegramHarness, _ChannelCase

from app import db, main, setup_api as setup_api_mod
from app.config import settings
from app.factory_model import load_factory_model

NEW = "viewer-works"
Q = f"?factory_id={NEW}"
FACTORY = {"name": "Viewer Works", "stock_item_code": "PART", "stock_item_name": "Widget",
           "qa_dispatch_hours": 2, "safety_stock_units": 10, "production_hours_in_window": 16}


class SetupCase(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        self.c = dev_client(main.app, user=DEV_VIEWER)    # a viewer of apex creates and owns NEW
        self.apex_owner = dev_client(main.app)
        self.other = dev_client(main.app, user=OTHER_OWNER)

    def tearDown(self):
        db.reset_to_seed()

    def make_factory(self):
        r = self.c.post("/api/v1/factories", json=FACTORY)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["id"], NEW)
        return r

    def supplier(self, **kw):
        body = {"name": "Backup One", "sourcing_role": "BACKUP", "unit_cost": 50, "max_units": 100,
                "lead_hours": 6, "route": "NH4", "risk_profile": "medium"}
        body.update(kw)
        return self.c.post("/api/v1/suppliers" + Q, json=body)

    def populate(self):
        self.make_factory()
        self.assertEqual(self.c.post("/api/v1/lines" + Q, json={
            "name": "Line A", "rated_units_per_hour": 10, "ot_units_per_hour": 4, "ot_cost_per_hour": 900,
            "max_ot_hours": 4}).status_code, 201)
        self.assertEqual(self.c.post("/api/v1/lines" + Q, json={
            "name": "Line B", "rated_units_per_hour": 8}).status_code, 201)
        self.assertEqual(self.supplier(name="Prime Metals", sourcing_role="PRIMARY", max_units=300,
                                       risk_profile="low", lead_hours=10).status_code, 201)
        self.assertEqual(self.supplier().status_code, 201)
        self.assertEqual(self.supplier(name="Backup Two", sourcing_role="EXPEDITE", flat_cost=5000,
                                       risk_profile="high", lead_hours=5, past_orders=4, on_time=3).status_code, 201)


class FactoryAndModelTests(SetupCase):
    def test_create_owner_conflict_and_validation(self):
        self.make_factory()
        self.assertEqual(db.get_member(db.get_dev_user(DEV_VIEWER)[0], NEW)["role"], "owner")
        self.assertEqual(db.get_stock_levels(NEW), {"PART": 0})
        self.assertEqual(self.c.post("/api/v1/factories", json=FACTORY).status_code, 409)
        r = self.c.post("/api/v1/factories", json=dict(FACTORY, name="X", qa_dispatch_hours=-1))
        self.assertEqual(r.status_code, 422)
        self.assertIn("qa_dispatch_hours", r.text)
        missing = {k: v for k, v in FACTORY.items() if k != "stock_item_name"}
        r = self.c.post("/api/v1/factories", json=missing)
        self.assertEqual(r.status_code, 422)
        self.assertIn("stock_item_name", r.text)
        self.assertEqual(self.c.post("/api/v1/factories", json=dict(FACTORY, name="Y", safety_stock_units=True)).status_code, 422)

    def test_settings_patch_and_isolation(self):
        self.make_factory()
        r = self.c.patch("/api/v1/factory/settings" + Q, json={"safety_stock_units": 25})
        self.assertEqual(r.json()["safety_stock_units"], 25)
        self.assertEqual(self.other.get("/api/v1/factory/settings" + Q).status_code, 404)
        self.assertEqual(self.other.patch("/api/v1/factory/settings" + Q, json={"name": "x"}).status_code, 404)

    def test_new_factory_model_uses_profile_values_and_pipeline_runs(self):
        self.populate()
        model = load_factory_model(NEW)
        by_name = {v.name: v for v in model.vendors}
        v = by_name["Backup One"]
        self.assertEqual((v.lead_sigma, v.delay_shock_pct, v.delay_shock_range, v.unreliability_delay_range),
                         (1.0, 6.0, (1.0, 3.0), (2.0, 4.0)))
        self.assertEqual(v.min_lead_hours, 6.0)               # no stated minimum: = lead hours
        self.assertEqual(v.prior_total, 0)                     # no history yet
        e = by_name["Backup Two"]
        self.assertEqual((e.lead_sigma, e.delay_shock_pct, e.prior_total), (2.0, 15.0, 4))
        self.assertEqual([s[1] for s in model.primary_suppliers], ["Prime Metals"])
        order = self.c.post("/api/v1/orders" + Q, json={
            "order_id": "WO-N1", "client": "Acme", "required_qty": 100, "hours_remaining": 40,
            "sla_penalty_inr": 100000, "partial_delay_penalty_inr": 20000})
        self.assertEqual(order.status_code, 201, order.text)
        r = self.c.post("/api/v1/simulate-crisis", json={
            "raw_message": "Prime Metals shipment delayed 6 hours, Line A at 50%, 40 units short on order WO-N1",
            "factory_id": NEW})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["run_id"])
        self.assertTrue(r.json()["playbooks"])

    def test_supplier_views_and_edit(self):
        self.populate()
        rows = {s["name"]: s for s in self.c.get("/api/v1/suppliers" + Q).json()["suppliers"]}
        self.assertEqual(rows["Backup One"]["reliability"]["reliability_note"], "no history yet")
        self.assertEqual(rows["Backup Two"]["reliability"]["past_orders"], 4)
        self.assertEqual(rows["Backup One"]["derived"]["shock_pct"], 6.0)
        sid = rows["Backup One"]["id"]
        r = self.c.patch(f"/api/v1/suppliers/{sid}", json={"risk_profile": "high", "lead_hours": 8})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["derived"]["lead_sigma_hours"], 2.0)
        self.assertEqual(r.json()["min_lead_hours"], 8.0)
        self.assertEqual(self.c.patch(f"/api/v1/suppliers/{sid}", json={"lead_hours": 0}).status_code, 422)
        self.assertEqual(self.c.patch(f"/api/v1/suppliers/{sid}", json={"min_lead_hours": 99}).status_code, 422)
        self.assertEqual(self.supplier(name="Bad", risk_profile="extreme").status_code, 422)
        self.assertEqual(self.supplier(name="Bad", past_orders=2, on_time=3).status_code, 422)
        self.assertEqual(self.supplier(name="Bad", max_units=-5).status_code, 422)
        self.assertEqual(self.supplier(name="Bad", lead_hours=2.5).status_code, 422)
        self.assertEqual(self.c.delete(f"/api/v1/suppliers/{sid}").status_code, 200)
        load_factory_model(NEW)

    def test_lines_orders_stock(self):
        self.populate()
        lines = self.c.get("/api/v1/lines" + Q).json()["lines"]
        self.assertEqual(len(lines), 2)
        lid = lines[0]["line_id"]
        self.assertEqual(self.c.patch(f"/api/v1/lines/{lid}", json={"max_ot_hours": 6}).json()["max_ot_hours"], 6)
        self.assertEqual(self.c.patch(f"/api/v1/lines/{lid}", json={"max_ot_hours": -1}).status_code, 422)
        base = {"client": "A", "required_qty": 5, "sla_penalty_inr": 1, "partial_delay_penalty_inr": 1}
        self.assertEqual(self.c.post("/api/v1/orders" + Q, json={**base, "due_at": "2000-01-01T00:00:00Z"}).status_code, 422)
        self.assertEqual(self.c.post("/api/v1/orders" + Q, json=base).status_code, 422)   # no deadline
        o = self.c.post("/api/v1/orders" + Q, json={**base, "hours_remaining": 24}).json()
        oid = o["order_id"]
        self.assertEqual(self.c.patch(f"/api/v1/orders/{oid}", json={"required_qty": 9}).json()["required_qty"], 9)
        self.assertEqual([l["qty"] for l in db.get_order_lines([oid])], [9])
        self.assertEqual(self.c.get("/api/v1/stock" + Q).json()["items"][0]["on_hand_qty"], 0)
        self.assertEqual(self.c.get("/api/v1/shipments" + Q).json()["shipments"], [])
        self.assertEqual(self.c.delete(f"/api/v1/lines/{lid}").status_code, 200)

    def test_line_in_open_run_cannot_be_deleted(self):
        r = self.apex_owner.post("/api/v1/simulate-crisis", json={"scenario_id": 1})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.apex_owner.delete("/api/v1/lines/LINE-1").status_code, 409)


class AccessTests(SetupCase):
    def test_viewer_403_foreign_404(self):
        v = dev_client(main.app, user=DEV_VIEWER)
        self.assertEqual(v.post("/api/v1/lines", json={"name": "L", "rated_units_per_hour": 1}).status_code, 403)
        self.assertEqual(v.patch("/api/v1/suppliers/SUP-PNY-02", json={"max_units": 5}).status_code, 403)
        self.assertEqual(v.get("/api/v1/suppliers").status_code, 200)
        self.assertEqual(v.get("/api/v1/team").status_code, 403)
        self.assertEqual(self.other.patch("/api/v1/suppliers/SUP-PNY-02", json={"max_units": 5}).status_code, 404)
        self.assertEqual(self.other.delete("/api/v1/lines/LINE-1").status_code, 404)
        self.assertEqual(self.other.patch("/api/v1/orders/EV-402", json={"priority": 1}).status_code, 404)
        self.assertEqual(self.other.get("/api/v1/suppliers?factory_id=apex-volt-blr2").status_code, 404)
        self.assertEqual(self.other.post("/api/v1/suppliers/SUP-PNY-02/telegram-invite").status_code, 404)
        self.assertEqual(db.get_supplier("SUP-PNY-02")["max_available_qty"], 200)


class CsvTests(SetupCase):
    def test_supplier_csv_row_errors_and_upsert(self):
        self.make_factory()
        csv = ("name,sourcing_role,max_units,lead_hours,route,risk_profile\n"
               "Good Co,BACKUP,100,4,R1,low\n"
               "Bad Co,BACKUP,100,4,R1,wild\n"
               "Neg Co,BACKUP,-4,4,R1,low\n")
        r = self.c.post("/api/v1/ingest/suppliers-csv", json={"filename": "s.csv", "csv_content": csv, "factory_id": NEW})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["imported_count"], 1)
        self.assertEqual(sorted(e["line"] for e in body["errors"]), [3, 4])
        self.assertIn("risk_profile", body["errors"][0]["error"])
        again = "name,sourcing_role,max_units,lead_hours,route,risk_profile\nGood Co,BACKUP,150,4,R1,low\n"
        self.c.post("/api/v1/ingest/suppliers-csv", json={"filename": "s.csv", "csv_content": again, "factory_id": NEW})
        rows = self.c.get("/api/v1/suppliers" + Q).json()["suppliers"]
        self.assertEqual([(s["name"], s["max_units"]) for s in rows], [("Good Co", 150)])

    def test_lines_csv(self):
        self.make_factory()
        r = self.c.post("/api/v1/ingest/lines-csv", json={
            "filename": "l.csv", "factory_id": NEW,
            "csv_content": "name,rated_units_per_hour,max_ot_hours\nL1,12,2\nL2,abc,1\n"}).json()
        self.assertEqual((r["imported_count"], [e["line"] for e in r["errors"]]), (1, [3]))


class TeamTests(SetupCase):
    def test_team_rules(self):
        self.make_factory()
        t = self.c.get("/api/v1/team" + Q).json()
        self.assertEqual([m["email"] for m in t["members"]], [DEV_VIEWER])
        owner_id = t["members"][0]["user_id"]
        self.assertEqual(self.c.post("/api/v1/team" + Q, json={"email": "nobody@example.test", "role": "viewer"}).status_code, 404)
        r = self.c.post("/api/v1/team" + Q, json={"email": DEV_OWNER, "role": "approver"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(self.c.post("/api/v1/team" + Q, json={"email": DEV_OWNER, "role": "viewer"}).status_code, 409)
        self.assertEqual(self.c.patch(f"/api/v1/team/{owner_id}" + Q, json={"role": "viewer"}).status_code, 409)
        self.assertEqual(self.c.delete(f"/api/v1/team/{owner_id}" + Q).status_code, 409)
        a = dev_client(main.app)   # the new approver can edit but not manage the team
        self.assertEqual(a.post("/api/v1/lines" + Q, json={"name": "L", "rated_units_per_hour": 1}).status_code, 201)
        self.assertEqual(a.get("/api/v1/team" + Q).status_code, 403)
        uid = r.json()["user_id"]
        self.assertEqual(self.c.patch(f"/api/v1/team/{uid}" + Q, json={"role": "owner"}).status_code, 200)
        self.assertEqual(self.c.delete(f"/api/v1/team/{owner_id}" + Q).status_code, 200)   # no longer the last owner
        self.assertEqual(self.other.get("/api/v1/team" + Q).status_code, 404)


class InviteTests(_ChannelCase):
    def setUp(self):
        super().setUp()
        self.h = TelegramHarness()
        self.h.patch.start()
        self.name = mock.patch.object(settings, "TELEGRAM_BOT_USERNAME", "CascadeBot")
        self.name.start()

    def tearDown(self):
        self.name.stop()
        self.h.patch.stop()
        super().tearDown()

    def invite(self, path):
        r = self.owner.post(path)
        self.assertEqual(r.status_code, 200, r.text)
        link = r.json()["link"]
        self.assertTrue(link.startswith("https://t.me/CascadeBot?start="))
        return link.split("start=")[1]

    def test_supplier_invite_to_rfq_delivery(self):
        token = self.invite("/api/v1/suppliers/SUP-PNY-02/telegram-invite")
        self.assertEqual(len(token), 24)
        self.assertNotIn(token, str(db._mirror.contact_invites))   # only the hash is stored
        r = self.h.text(self.webhook, "7000009", f"/start {token}")
        self.assertEqual(r.json().get("action"), "contact_connected", r.text)
        self.assertIn("connected to Apex Volt", self.h.sent()[-1]["text"])
        self.assertEqual(db.get_supplier("SUP-PNY-02")["telegram_chat_id"], "7000009")
        r = self.h.text(self.webhook, "7000010", f"/start {token}")   # reuse is refused
        self.assertEqual(r.json().get("action"), "invite_refused")
        self.assertEqual(db.get_supplier("SUP-PNY-02")["telegram_chat_id"], "7000009")
        with mock.patch.object(settings, "SOURCING_MODE", "telegram"):   # the RFQ goes to that chat
            self.link(self.h, DEV_OWNER, self.h.sender)
            run_id = self.apex_run()["run_id"]
            self.assertEqual(self.owner.post("/api/v1/sourcing/start", json={"run_id": run_id}).status_code, 200)
        self.assertTrue([m for m in self.h.sent() if m["to"] == "7000009" and "RFQ-" in m["text"]])

    def test_client_invite_expired_and_cross_factory(self):
        token = self.invite("/api/v1/orders/EV-402/telegram-invite")
        r = self.h.text(self.webhook, "7000020", f"/start {token}")
        self.assertEqual(r.json().get("kind"), "client", r.text)
        self.assertEqual(db.get_order("EV-402")["client_contact"], "telegram:7000020")
        self.assertIn("client of order EV-402", self.h.sent()[-1]["text"])
        token = self.invite("/api/v1/suppliers/SUP-HSR-03/telegram-invite")
        for row in db._mirror.contact_invites:
            row["expires_at"] = "2000-01-01T00:00:00+00:00"
        r = self.h.text(self.webhook, "7000021", f"/start {token}")
        self.assertEqual(r.json().get("action"), "invite_refused")
        self.assertFalse(db.get_supplier("SUP-HSR-03").get("telegram_chat_id"))
        token = self.invite("/api/v1/suppliers/SUP-AIR-04/telegram-invite")
        db._mirror.contact_invites[-1]["factory_id"] = "test-plant"   # invite factory != target's factory
        r = self.h.text(self.webhook, "7000022", f"/start {token}")
        self.assertEqual(r.json().get("action"), "invite_refused")
        self.assertFalse(db.get_supplier("SUP-AIR-04").get("telegram_chat_id"))

    def test_no_bot_username_is_409_and_viewer_403(self):
        with mock.patch.object(settings, "TELEGRAM_BOT_USERNAME", ""):
            self.assertEqual(self.owner.post("/api/v1/suppliers/SUP-PNY-02/telegram-invite").status_code, 409)
        viewer = dev_client(main.app, user=DEV_VIEWER)
        self.assertEqual(viewer.post("/api/v1/suppliers/SUP-PNY-02/telegram-invite").status_code, 403)


if __name__ == "__main__":
    unittest.main()


class RoundSFinalFixTests(SetupCase):
    def test_multi_factory_409_picker_and_my_factories(self):
        self.make_factory()          # DEV_VIEWER is now in apex (viewer) + NEW (owner): apex is the default
        r = self.c.get("/api/v1/my/factories")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({f["factory_id"]: f["role"] for f in r.json()["factories"]},
                         {settings.DEFAULT_FACTORY_ID: "viewer", NEW: "owner"})
        self.assertTrue(all(f["name"] for f in r.json()["factories"]))
        # two memberships, none the default -> 409 with the list
        db.delete_rows_where("factory_members", {"user_id": db.get_dev_user(DEV_VIEWER)[0],
                                                 "factory_id": settings.DEFAULT_FACTORY_ID})
        r = self.c.get("/api/v1/lines")
        self.assertEqual(r.status_code, 200)    # single membership again: fine
        self.other.post("/api/v1/factories", json=dict(FACTORY, name="Second Works"))
        r = self.other.get("/api/v1/lines")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"], "choose a factory")
        self.assertEqual({f["factory_id"] for f in r.json()["factories"]}, {"test-plant", "second-works"})
        self.assertEqual(self.other.get("/api/v1/lines?factory_id=second-works").status_code, 200)

    def test_delete_last_line_or_primary_supplier_is_409(self):
        self.populate()
        lines = self.c.get("/api/v1/lines" + Q).json()["lines"]
        self.assertEqual(self.c.delete(f"/api/v1/lines/{lines[0]['line_id']}").status_code, 200)
        r = self.c.delete(f"/api/v1/lines/{lines[1]['line_id']}")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(len(self.c.get("/api/v1/lines" + Q).json()["lines"]), 1)
        sups = self.c.get("/api/v1/suppliers" + Q).json()["suppliers"]
        primary = next(s for s in sups if s["sourcing_role"] == "PRIMARY")
        r = self.c.delete(f"/api/v1/suppliers/{primary['id']}")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(len(self.c.get("/api/v1/suppliers" + Q).json()["suppliers"]), len(sups))

    def test_order_id_in_other_factory_is_generic_422(self):
        self.make_factory()
        r = self.c.post("/api/v1/orders" + Q, json={"order_id": "EV-402", "client": "C", "required_qty": 5,
                        "hours_remaining": 48, "sla_penalty_inr": 1, "partial_delay_penalty_inr": 1, "priority": 1})
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("order id not available", r.text)

    def test_factory_creation_capped_at_five(self):
        for i in range(5):
            r = self.c.post("/api/v1/factories", json=dict(FACTORY, name=f"Cap {i}"))
            self.assertEqual(r.status_code, 201, r.text)
        r = self.c.post("/api/v1/factories", json=dict(FACTORY, name="Cap 6"))
        self.assertEqual(r.status_code, 409, r.text)

    def test_settings_rollback_restores_item_name(self):
        self.make_factory()

        def flaky(fid):
            raise setup_api_mod.FactoryDataError("boom")
        with mock.patch.object(setup_api_mod, "_model_ok", return_value=True), \
                mock.patch.object(setup_api_mod, "load_factory_model", side_effect=flaky):
            r = self.c.patch("/api/v1/factory/settings" + Q, json={"stock_item_name": "Gadget"})
        self.assertEqual(r.status_code, 422, r.text)
        item = db.fetch_where("items", {"factory_id": NEW, "item_code": "PART"})[0]
        self.assertEqual(item["name"], "Widget")
