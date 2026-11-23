"""Round B Task 5: channel adapters (WhatsApp, Telegram) and the shared inbound flow.

Every flow test runs over both channels with fake transports (nothing reaches Meta or Telegram):
alert -> plan with an Approve button; Approve by a linked approver -> executed once; unlinked,
viewer and foreign-factory senders -> refused with nothing executed (Review Focus 3); a duplicate
update -> processed once (Review Focus 4); a processing failure releases the event.
"""

import contextlib
import hashlib
import hmac
import itertools
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_OWNER, DEV_VIEWER, OTHER_OWNER, dev_client
from tests.factories import seed_second_factory

from fastapi.testclient import TestClient

from app import db, inbound, main, run_store
from app.channels.base import InboundMessage
from app.channels.telegram import TelegramChannel
from app.channels.whatsapp import WhatsAppChannel

APEX = "apex-volt-blr2"
TP = "test-plant"
ALERT = "Flood on NH48, 48h delay, 150 casings short"
TP_MESSAGE = "L-B at 40%, 80 units short on WO-77, 5h delay from Vendor V1"
TG_SECRET = "test-telegram-secret"
_ids = itertools.count(1000)


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"ok": True, "result": {}}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeTelegramTransport:
    """Stands in for httpx: records every Bot API call, never touches the network."""

    def __init__(self):
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url.rsplit("/", 1)[-1], json))
        return _Resp()


class _Harness:
    """Drives one channel end to end through its webhook with a fake transport."""

    name = ""
    sender = ""

    def sent(self):
        raise NotImplementedError

    def text(self, client, sender, text, msg_id=None):
        raise NotImplementedError

    def button(self, client, sender, button_id, msg_id=None):
        raise NotImplementedError


class WhatsAppHarness(_Harness):
    name = "whatsapp"
    sender = "919811111111"
    other_sender = "919822222222"

    def __init__(self):
        self.log = []
        self.channel = WhatsAppChannel(
            send_text=lambda to, text: self.log.append({"to": to, "text": text, "buttons": []}) or True,
            send_buttons=lambda to, text, buttons, header=None, footer=None: self.log.append(
                {"to": to, "text": text, "buttons": [b["id"] for b in buttons]}) or True,
        )
        self.patch = mock.patch.object(main, "_whatsapp_channel", lambda: self.channel)

    def sent(self):
        return self.log

    def _post(self, client, msg):
        msg.setdefault("id", f"wamid.T{next(_ids)}")
        body = {"object": "whatsapp_business_account",
                "entry": [{"changes": [{"value": {"messages": [msg]}}]}]}
        raw = json.dumps(body).encode()
        sig = "sha256=" + hmac.new(b"test-app-secret", raw, hashlib.sha256).hexdigest()
        return client.post("/api/v1/webhooks/whatsapp", content=raw,
                           headers={"content-type": "application/json", "x-hub-signature-256": sig})

    def text(self, client, sender, text, msg_id=None):
        msg = {"from": sender, "type": "text", "text": {"body": text}}
        if msg_id:
            msg["id"] = f"wamid.{msg_id}"
        return self._post(client, msg)

    def button(self, client, sender, button_id, msg_id=None):
        msg = {"from": sender, "type": "interactive", "interactive": {"button_reply": {"id": button_id}}}
        if msg_id:
            msg["id"] = f"wamid.{msg_id}"
        return self._post(client, msg)


class TelegramHarness(_Harness):
    name = "telegram"
    sender = "5550001"
    other_sender = "5550002"

    def __init__(self):
        self.transport = FakeTelegramTransport()
        self.channel = TelegramChannel("TEST-TOKEN", transport=self.transport)
        self.patch = mock.patch.object(main, "_telegram_channel", lambda: self.channel)

    def sent(self):
        out = []
        for method, body in self.transport.calls:
            if method == "sendMessage":
                rows = (body.get("reply_markup") or {}).get("inline_keyboard") or []
                out.append({"to": str(body["chat_id"]), "text": body["text"],
                            "buttons": [b["callback_data"] for row in rows for b in row]})
        return out

    def _post(self, client, update, msg_id):
        update["update_id"] = int(msg_id) if msg_id is not None else next(_ids)
        return client.post("/api/v1/telegram/webhook", json=update,
                           headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET})

    def text(self, client, sender, text, msg_id=None):
        chat = {"id": int(sender), "type": "private"}
        return self._post(client, {"message": {"message_id": 1, "chat": chat, "from": {"id": int(sender)},
                                               "text": text}}, msg_id)

    def button(self, client, sender, button_id, msg_id=None):
        chat = {"id": int(sender), "type": "private"}
        return self._post(client, {"callback_query": {
            "id": f"cq{next(_ids)}", "from": {"id": int(sender)},
            "message": {"message_id": 2, "chat": chat}, "data": button_id}}, msg_id)


HARNESSES = (WhatsAppHarness, TelegramHarness)


class _ChannelCase(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        seed_second_factory()
        self._secret = mock.patch.object(main.settings, "TELEGRAM_WEBHOOK_SECRET", TG_SECRET)
        self._secret.start()
        self.webhook = TestClient(main.app, raise_server_exceptions=False)  # no credentials at all
        self.owner = dev_client(main.app)

    def tearDown(self):
        self._secret.stop()
        db.reset_to_seed()

    @staticmethod
    def channels():
        return [cls() for cls in HARNESSES]

    @contextlib.contextmanager
    def active(self, h):
        """Fresh data and the channel's fake transport for one subTest."""
        db.reset_to_seed()
        seed_second_factory()
        h.patch.start()
        try:
            yield h
        finally:
            h.patch.stop()

    def link(self, h, user, sender):
        code = dev_client(main.app, user=user).post("/api/v1/channels/link-code", json={}).json()["code"]
        r = h.text(self.webhook, sender, f"/link {code}")
        self.assertEqual(r.json().get("action"), "linked", r.text)
        return code

    def apex_run(self):
        r = self.owner.post("/api/v1/simulate-crisis", json={"scenario_id": 1})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def tp_run(self):
        r = dev_client(main.app, user=OTHER_OWNER).post(
            "/api/v1/simulate-crisis", json={"raw_message": TP_MESSAGE, "factory_id": TP})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    @staticmethod
    def receipts():
        return list(db._mirror.execution_receipts)

    @staticmethod
    def pos(run_id):
        return [p for p in db._mirror.purchase_orders if p.get("run_id") == run_id]


class SharedFlowTests(_ChannelCase):
    def test_alert_from_linked_approver_gets_plan_with_approve_button(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.sender)
                r = h.text(self.webhook, h.sender, ALERT)
                self.assertEqual(r.status_code, 200, r.text)
                run_id = r.json()["run_id"]
                run = run_store.get_run(run_id)
                self.assertEqual(run["factory_id"], APEX)
                last = h.sent()[-1]
                self.assertEqual(last["to"], h.sender)
                self.assertIn(f"APPROVE:{run_id}:{run['recommended_plan_id']}", last["buttons"])
                self.assertIn("VIEW_STATUS", last["buttons"])
                self.assertIn(run_id, last["text"])

    def test_alert_runs_for_the_senders_factory(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, OTHER_OWNER, h.sender)
                r = h.text(self.webhook, h.sender, TP_MESSAGE)
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(run_store.get_run(r.json()["run_id"])["factory_id"], TP)

    def test_approve_by_linked_approver_executes_once(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.sender)
                run_id = h.text(self.webhook, h.sender, ALERT).json()["run_id"]
                plan = run_store.get_run(run_id)["recommended_plan_id"]
                button = f"APPROVE:{run_id}:{plan}"
                r1 = h.button(self.webhook, h.sender, button)
                self.assertEqual(r1.json().get("action"), "plan_executed", r1.text)
                r2 = h.button(self.webhook, h.sender, button)   # a second press is not a second PO
                self.assertNotEqual(r2.json().get("status"), "forbidden")
                self.assertEqual(len(self.pos(run_id)), 1)
                self.assertEqual(db.get_receipt(run_id)["approved_by"], f"{h.name}:{DEV_OWNER}")
                self.assertIn("APPROVED", h.sent()[-1]["text"])

    def test_approver_role_member_can_approve(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                db._mirror.factory_members.append({"user_id": "00000000-0000-4000-8000-0000000000a9",
                                                   "factory_id": APEX, "role": "approver",
                                                   "email": "approver@example.test"})
                self.link(h, "approver@example.test", h.sender)
                sim = self.apex_run()
                r = h.button(self.webhook, h.sender, f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
                self.assertEqual(r.json().get("action"), "plan_executed", r.text)
                self.assertEqual(db.get_receipt(sim["run_id"])["approved_by"], f"{h.name}:approver@example.test")

    def test_unlinked_sender_is_refused(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.other_sender)   # a linked chat exists, so no WhatsApp fallback
                sim = self.apex_run()
                with mock.patch.object(main, "_execute") as execute:
                    r = h.button(self.webhook, h.sender, f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
                execute.assert_not_called()
                self.assertEqual(r.json()["status"], "forbidden")
                self.assertIsNone(db.get_receipt(sim["run_id"]))
                self.assertEqual(h.sent()[-1]["to"], h.sender)
                self.assertIn("/link", h.sent()[-1]["text"])

    def test_linked_chat_cannot_approve_another_factory_even_if_user_owns_it(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                # DEV_OWNER owns Apex; also make them owner of test-plant, but link the chat for Apex.
                self.link(h, DEV_OWNER, h.sender)
                owner_id = "00000000-0000-4000-8000-000000000001"
                db.upsert_row("factory_members", {"user_id": owner_id, "factory_id": TP, "role": "owner",
                                                  "email": "dev-owner@example.test"},
                              key_columns=("user_id", "factory_id"))
                sim = self.tp_run()
                with mock.patch.object(main, "_execute") as execute:
                    r = h.button(self.webhook, h.sender, f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
                execute.assert_not_called()
                self.assertEqual(r.json()["status"], "forbidden")

    def test_unlinked_alert_is_not_planned(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.other_sender)
                with mock.patch.object(main, "_run_pipeline") as pipeline:
                    r = h.text(self.webhook, h.sender, ALERT)
                pipeline.assert_not_called()
                self.assertEqual(r.json()["status"], "unlinked")
                self.assertIn("/link", h.sent()[-1]["text"])

    def test_viewer_is_refused(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_VIEWER, h.sender)
                sim = self.apex_run()
                with mock.patch.object(main, "_execute") as execute:
                    r = h.button(self.webhook, h.sender, f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
                execute.assert_not_called()
                self.assertEqual(r.json()["status"], "forbidden")
                self.assertIsNone(db.get_receipt(sim["run_id"]))
                self.assertIn("role", h.sent()[-1]["text"])

    def test_viewer_alert_is_not_planned_but_status_works(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_VIEWER, h.sender)
                with mock.patch.object(main, "_run_pipeline") as pipeline:
                    r = h.text(self.webhook, h.sender, ALERT)
                pipeline.assert_not_called()
                self.assertEqual(r.json()["status"], "forbidden")
                r = h.text(self.webhook, h.sender, "status")
                self.assertEqual(r.json()["status"], "ok")
                self.assertIn("PLANT STATUS", h.sent()[-1]["text"])

    def test_foreign_factory_run_is_refused(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, OTHER_OWNER, h.sender)      # owner of test-plant only
                sim = self.apex_run()
                with mock.patch.object(main, "_execute") as execute:
                    r = h.button(self.webhook, h.sender, f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
                execute.assert_not_called()
                self.assertEqual(r.json()["status"], "forbidden")
                self.assertIsNone(db.get_receipt(sim["run_id"]))
                self.assertNotIn(APEX, h.sent()[-1]["text"])

    def test_owner_of_apex_cannot_approve_test_plant_run(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.sender)
                sim = self.tp_run()
                r = h.button(self.webhook, h.sender, f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
                self.assertEqual(r.json()["status"], "forbidden")
                self.assertIsNone(db.get_receipt(sim["run_id"]))

    def test_removed_membership_is_refused(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.sender)
                sim = self.apex_run()
                db._mirror.factory_members[:] = [m for m in db._mirror.factory_members if m["email"] != DEV_OWNER]
                r = h.button(self.webhook, h.sender, f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
                self.assertEqual(r.json()["status"], "forbidden")
                self.assertIsNone(db.get_receipt(sim["run_id"]))

    def test_duplicate_update_is_processed_once(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.sender)
                msg_id = str(next(_ids))
                with mock.patch.object(main, "_run_pipeline", wraps=main._run_pipeline) as spy:
                    first = h.text(self.webhook, h.sender, ALERT, msg_id=msg_id)
                    second = h.text(self.webhook, h.sender, ALERT, msg_id=msg_id)
                self.assertEqual(spy.call_count, 1)
                self.assertNotEqual(first.json()["status"], "duplicate")
                self.assertEqual(second.json()["status"], "duplicate")

    def test_duplicate_approval_is_processed_once(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.sender)
                sim = self.apex_run()
                msg_id = str(next(_ids))
                button = f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}"
                with mock.patch.object(main, "_execute", wraps=main._execute) as spy:
                    h.button(self.webhook, h.sender, button, msg_id=msg_id)
                    again = h.button(self.webhook, h.sender, button, msg_id=msg_id)
                self.assertEqual(spy.call_count, 1)
                self.assertEqual(again.json()["status"], "duplicate")

    def test_failure_releases_the_event(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.sender)
                sim = self.apex_run()
                msg_id = str(next(_ids))
                button = f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}"
                with mock.patch.object(main, "_execute", side_effect=db.DatabaseError("rpc", "execute_plan_tx")):
                    r = h.button(self.webhook, h.sender, button, msg_id=msg_id)
                self.assertEqual(r.status_code, 503)
                self.assertIsNone(db.get_receipt(sim["run_id"]))
                retry = h.button(self.webhook, h.sender, button, msg_id=msg_id)   # the platform's retry
                self.assertEqual(retry.json().get("action"), "plan_executed", retry.text)
                self.assertEqual(h.button(self.webhook, h.sender, button, msg_id=msg_id).json()["status"], "duplicate")

    def test_status_is_the_linked_factorys(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, OTHER_OWNER, h.sender)
                with mock.patch.object(inbound, "status_text", return_value="STATUS") as status:
                    h.button(self.webhook, h.sender, "VIEW_STATUS")
                status.assert_called_once_with(TP)

    def test_help(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                r = h.text(self.webhook, h.sender, "/start")
                self.assertEqual(r.json()["action"], "help_sent")
                self.assertIn("/link", h.sent()[-1]["text"])


class LinkCodeTests(_ChannelCase):
    def test_endpoint_returns_code_and_expiry(self):
        before = datetime.now(timezone.utc)
        r = self.owner.post("/api/v1/channels/link-code", json={})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(set(body), {"code", "expires_at"})
        expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        self.assertEqual(expires.utcoffset(), timedelta(0))
        self.assertAlmostEqual((expires - before).total_seconds(), 15 * 60, delta=30)
        self.assertGreaterEqual(len(body["code"]), 8)
        # The code itself is not stored (only its hash), so a database read cannot link a chat.
        self.assertNotIn(body["code"], json.dumps(db._mirror.link_codes))

    def test_endpoint_needs_a_user(self):
        self.assertEqual(TestClient(main.app).post("/api/v1/channels/link-code", json={}).status_code, 401)
        machine = TestClient(main.app).post("/api/v1/channels/link-code", json={},
                                            headers={"X-API-Key": "test-operator-key"})
        self.assertEqual(machine.status_code, 403)

    def test_endpoint_foreign_factory_is_404(self):
        r = self.owner.post("/api/v1/channels/link-code", json={"factory_id": TP})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(db._mirror.link_codes, [])

    def test_used_code_is_refused(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                code = self.link(h, DEV_OWNER, h.sender)
                r = h.text(self.webhook, h.other_sender, f"/link {code}")
                self.assertEqual(r.json()["status"], "forbidden")
                self.assertIsNone(db.get_user_channel(h.name, h.other_sender))
                self.assertIn("invalid", h.sent()[-1]["text"].lower())

    def test_expired_code_is_refused(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                code = self.owner.post("/api/v1/channels/link-code", json={}).json()["code"]
                past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                for row in db._mirror.link_codes:
                    row["expires_at"] = past
                r = h.text(self.webhook, h.sender, f"/link {code}")
                self.assertEqual(r.json()["status"], "forbidden")
                self.assertIsNone(db.get_user_channel(h.name, h.sender))

    def test_unknown_code_is_refused(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                r = h.text(self.webhook, h.sender, "/link NOTACODE")
                self.assertEqual(r.json()["status"], "forbidden")
                self.assertIsNone(db.get_user_channel(h.name, h.sender))

    def test_link_binds_user_and_factory(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, OTHER_OWNER, h.sender)
                row = db.get_user_channel(h.name, h.sender)
                self.assertEqual((row["factory_id"], row["user_id"]), (TP, "00000000-0000-4000-8000-000000000003"))

    def test_links_survive_a_factory_reset(self):
        for h in self.channels():
            with self.subTest(channel=h.name), self.active(h):
                self.link(h, DEV_OWNER, h.sender)
                self.assertEqual(self.owner.post("/api/v1/reset").status_code, 200)
                self.assertIsNotNone(db.get_user_channel(h.name, h.sender))


class WhatsAppFallbackTests(_ChannelCase):
    """WA_APPROVER_NUMBERS works only while user_channels has no WhatsApp rows, and only for
    DEFAULT_FACTORY_ID runs (Task 2 review I1)."""

    def setUp(self):
        super().setUp()
        self.h = WhatsAppHarness()
        self.h.patch.start()

    def tearDown(self):
        self.h.patch.stop()
        super().tearDown()

    def test_allowlisted_number_approves_default_factory_run(self):
        sim = self.apex_run()
        r = self.h.button(self.webhook, "919800000000", f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
        self.assertEqual(r.json().get("action"), "plan_executed")
        self.assertEqual(db.get_receipt(sim["run_id"])["approved_by"], "whatsapp:919800000000")

    def test_allowlisted_number_cannot_approve_other_factory_run(self):
        sim = self.tp_run()
        with mock.patch.object(main, "_execute") as execute:
            r = self.h.button(self.webhook, "919800000000", f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
        execute.assert_not_called()
        self.assertEqual(r.json()["status"], "forbidden")
        self.assertIsNone(db.get_receipt(sim["run_id"]))

    def test_allowlist_is_off_once_any_whatsapp_chat_is_linked(self):
        self.link(self.h, DEV_OWNER, self.h.other_sender)
        sim = self.apex_run()
        r = self.h.button(self.webhook, "919800000000", f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
        self.assertEqual(r.json()["status"], "forbidden")
        self.assertIsNone(db.get_receipt(sim["run_id"]))

    def test_telegram_links_do_not_end_the_whatsapp_fallback(self):
        db.link_user_channel("telegram", "5550009", "00000000-0000-4000-8000-000000000001", APEX)
        sim = self.apex_run()
        r = self.h.button(self.webhook, "919800000000", f"APPROVE:{sim['run_id']}:{sim['recommended_plan_id']}")
        self.assertEqual(r.json().get("action"), "plan_executed")

    def test_non_allowlisted_number_gets_no_status_or_alert(self):
        with mock.patch.object(main, "_run_pipeline") as pipeline:
            for text in (ALERT, "status"):
                r = self.h.text(self.webhook, "919000000001", text)
                self.assertEqual(r.json()["status"], "unlinked")
                self.assertIn("/link", self.h.sent()[-1]["text"])
        pipeline.assert_not_called()

    def test_fallback_alerts_run_for_the_default_factory(self):
        r = self.h.text(self.webhook, "919800000000", ALERT)
        self.assertEqual(run_store.get_run(r.json()["run_id"])["factory_id"], main.settings.DEFAULT_FACTORY_ID)


class TelegramWebhookTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        self.client = TestClient(main.app)
        self.transport = FakeTelegramTransport()
        self._p = [mock.patch.object(main.settings, "TELEGRAM_WEBHOOK_SECRET", TG_SECRET),
                   mock.patch.object(main, "_telegram_channel",
                                     lambda: TelegramChannel("TEST-TOKEN", transport=self.transport))]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        db.reset_to_seed()

    def _update(self):
        return {"update_id": next(_ids), "message": {"message_id": 1, "chat": {"id": 42, "type": "private"},
                                                     "from": {"id": 42}, "text": "/start"}}

    def test_wrong_secret_is_401(self):
        with mock.patch.object(inbound, "handle") as handle:
            for headers in ({"X-Telegram-Bot-Api-Secret-Token": "wrong"}, {}):
                r = self.client.post("/api/v1/telegram/webhook", json=self._update(), headers=headers)
                self.assertEqual(r.status_code, 401)
        handle.assert_not_called()
        self.assertEqual(self.transport.calls, [])

    def test_unconfigured_secret_is_401(self):
        with mock.patch.object(main.settings, "TELEGRAM_WEBHOOK_SECRET", ""):
            r = self.client.post("/api/v1/telegram/webhook", json=self._update(),
                                 headers={"X-Telegram-Bot-Api-Secret-Token": ""})
        self.assertEqual(r.status_code, 401)

    def test_right_secret_is_processed(self):
        r = self.client.post("/api/v1/telegram/webhook", json=self._update(),
                             headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.transport.calls[-1][0], "sendMessage")


class TelegramAdapterTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTelegramTransport()
        self.tg = TelegramChannel("TEST-TOKEN", transport=self.transport)

    def test_text_message(self):
        msgs = self.tg.parse_inbound({"update_id": 7, "message": {
            "chat": {"id": 99, "type": "private"}, "from": {"id": 99}, "text": " status "}})
        self.assertEqual(msgs, [InboundMessage("telegram", "99", "status", None, "tg:7")])

    def test_callback_is_answered_and_parsed(self):
        msgs = self.tg.parse_inbound({"update_id": 8, "callback_query": {
            "id": "cq-1", "from": {"id": 99}, "message": {"chat": {"id": 99, "type": "private"}},
            "data": "APPROVE:RUN-ABCDEF12:PLAN_B"}})
        self.assertEqual(msgs, [InboundMessage("telegram", "99", "", "APPROVE:RUN-ABCDEF12:PLAN_B", "tg:8")])
        self.assertEqual(self.transport.calls, [("answerCallbackQuery", {"callback_query_id": "cq-1"})])

    def test_group_chats_are_ignored(self):
        self.assertEqual(self.tg.parse_inbound({"update_id": 9, "message": {
            "chat": {"id": -100, "type": "group"}, "from": {"id": 99}, "text": "status"}}), [])
        self.assertEqual(self.tg.parse_inbound({"update_id": 10, "callback_query": {
            "id": "cq-2", "from": {"id": 98}, "message": {"chat": {"id": 99, "type": "private"}},
            "data": "VIEW_STATUS"}}), [])   # pressed by someone other than the chat's user

    def test_send_buttons_uses_inline_keyboard(self):
        self.assertTrue(self.tg.send_buttons("99", "Plan", [("APPROVE:RUN-ABCDEF12:PLAN_B", "Approve PLAN_B"),
                                                            ("VIEW_STATUS", "Plant status")]))
        method, body = self.transport.calls[-1]
        self.assertEqual(method, "sendMessage")
        self.assertEqual(body["chat_id"], "99")
        self.assertEqual(body["reply_markup"]["inline_keyboard"],
                         [[{"text": "Approve PLAN_B", "callback_data": "APPROVE:RUN-ABCDEF12:PLAN_B"}],
                          [{"text": "Plant status", "callback_data": "VIEW_STATUS"}]])

    def test_callback_data_over_64_bytes_is_never_sent(self):
        self.tg.send_buttons("99", "Plan", [("APPROVE:" + "X" * 70, "Approve")])
        _, body = self.transport.calls[-1]
        datas = [b["callback_data"] for row in (body.get("reply_markup") or {}).get("inline_keyboard", []) for b in row]
        self.assertTrue(all(len(d.encode()) <= 64 for d in datas))

    def test_approve_ids_fit_callback_data(self):
        self.assertLessEqual(len("APPROVE:RUN-ABCDEF12-S3:PLAN_B".encode()), 64)

    def test_no_token_sends_nothing(self):
        tg = TelegramChannel("", transport=self.transport)
        self.assertFalse(tg.send_text("99", "hi"))
        self.assertEqual(self.transport.calls, [])

    def test_send_failure_is_false_and_token_not_logged(self):
        class Boom:
            def post(self, url, json=None, timeout=None):
                raise RuntimeError(f"connect failed for {url}")
        tg = TelegramChannel("SECRET-TOKEN-123", transport=Boom())
        with self.assertLogs("cascadezero.telegram", level="ERROR") as logs:
            self.assertFalse(tg.send_text("99", "hi"))
        self.assertNotIn("SECRET-TOKEN-123", "\n".join(logs.output))


class WhatsAppAdapterTests(unittest.TestCase):
    def test_parse_text_and_button(self):
        wa = WhatsAppChannel(send_text=lambda *a: True, send_buttons=lambda *a, **k: True)
        payload = {"entry": [{"changes": [{"value": {"messages": [
            {"from": "919811111111", "id": "wamid.1", "type": "text", "text": {"body": " hi "}}]}}]}]}
        self.assertEqual(wa.parse_inbound(payload), [InboundMessage("whatsapp", "919811111111", "hi", None, "wamid.1")])
        payload["entry"][0]["changes"][0]["value"]["messages"][0] = {
            "from": "919811111111", "id": "wamid.2", "type": "interactive",
            "interactive": {"button_reply": {"id": "VIEW_STATUS"}}}
        self.assertEqual(wa.parse_inbound(payload),
                         [InboundMessage("whatsapp", "919811111111", "", "VIEW_STATUS", "wamid.2")])



class IdentitySqlTests(unittest.TestCase):
    """user_channels and link_codes: service-only (RLS on, no policy, no browser privileges)."""

    ROOT = Path(__file__).resolve().parents[2] / "supabase"
    m008 = (ROOT / "migrations" / "008_identity.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8").replace("\r\n", "\n")

    def _create(self, sql, table):
        m = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", sql, re.S)
        self.assertIsNotNone(m, table)
        return m.group(1)

    def test_tables_in_008_above_the_marker(self):
        marker = self.m008.index("APPEND their parts HERE")
        check = self.m008[self.m008.index("RAISE EXCEPTION 'RLS check failed: open policies remain"):]
        for table in ("user_channels", "link_codes"):
            with self.subTest(table=table):
                self.assertLess(self.m008.index(f"CREATE TABLE IF NOT EXISTS {table}"), marker)
                self.assertRegex(self.m008, rf"ALTER TABLE {table}\s+ENABLE ROW LEVEL SECURITY;")
                self.assertRegex(self.m008, rf"REVOKE ALL ON {table} FROM anon, authenticated;")
                self.assertNotRegex(self.m008, rf"CREATE POLICY \w+ ON {table}\b")
                self.assertIn(f"'{table}'", check)
        self.assertTrue(self.m008.rstrip().endswith(
            "INSERT INTO schema_migrations (version) VALUES (8) ON CONFLICT DO NOTHING;"))
        body = self._create(self.m008, "user_channels")
        self.assertRegex(body, r"user_id\s+UUID NOT NULL")
        self.assertRegex(body, r"factory_id\s+TEXT NOT NULL")
        self.assertIn("PRIMARY KEY (channel, address)", body)
        body = self._create(self.m008, "link_codes")
        self.assertRegex(body, r"code\s+TEXT PRIMARY KEY")
        self.assertRegex(body, r"expires_at\s+TIMESTAMPTZ NOT NULL")
        self.assertRegex(body, r"used_at\s+TIMESTAMPTZ")

    def test_schema_sql_has_the_tables(self):
        for table in ("user_channels", "link_codes"):
            with self.subTest(table=table):
                self._create(self.schema, table)
                self.assertRegex(self.schema, rf"ALTER TABLE {table}\s+ENABLE ROW LEVEL SECURITY;")
                self.assertRegex(self.schema, rf"REVOKE ALL ON {table} FROM anon, authenticated;")
                self.assertNotRegex(self.schema, rf"CREATE POLICY \w+ ON {table}\b")


if __name__ == "__main__":
    unittest.main()
