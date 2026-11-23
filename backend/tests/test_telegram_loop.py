"""Telegram vendor/client messaging, the polling worker and the admin contact commands (offline:
fake transports only; nothing reaches Telegram or WhatsApp)."""

import asyncio
import io
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_OWNER, OTHER_OWNER, dev_client

from app import admin, db, main, telegram_poll
from app.agents import client as client_agent
from app.agents import sourcing
from app.channels.telegram import TelegramChannel
from app.config import settings
from tests.test_channels import (ALERT, TG_SECRET, FakeTelegramTransport, TelegramHarness, WhatsAppHarness,
                                 _ChannelCase)

VENDOR_ADDRESS = {"telegram": "7000001", "whatsapp": "919900000001"}
VENDOR_COLUMN = {"telegram": "telegram_chat_id", "whatsapp": "whatsapp_number"}


class ParityFlowTests(_ChannelCase):
    """alert -> plan -> RFQs to vendor chats -> vendor YES -> approve -> receipt, per channel."""

    def test_full_flow_on_each_channel(self):
        for h in (TelegramHarness(), WhatsAppHarness()):
            with self.subTest(channel=h.name), self.active(h), \
                    mock.patch.object(settings, "SOURCING_MODE", h.name):
                db.update_rows("suppliers", "id", "SUP-PNY-02", {VENDOR_COLUMN[h.name]: VENDOR_ADDRESS[h.name]})
                self.link(h, DEV_OWNER, h.sender)

                # 1-2. the approver's alert creates a plan; the bot replies with a summary + Approve
                r = h.text(self.webhook, h.sender, ALERT)
                self.assertEqual(r.json()["status"], "success", r.text)
                run_id = r.json()["run_id"]
                summary = h.sent()[-1]
                self.assertEqual(summary["to"], h.sender)
                approve = [b for b in summary["buttons"] if b.startswith("APPROVE:")]
                self.assertEqual(len(approve), 1)

                # 3. the operator starts sourcing: RFQs go to the vendor chat id
                started = self.owner.post("/api/v1/sourcing/start", json={"run_id": run_id})
                self.assertEqual(started.status_code, 200, started.text)
                self.assertEqual(started.json()["status"], "ACTIVE", started.text)
                rfqs = [m for m in h.sent() if m["to"] == VENDOR_ADDRESS[h.name]]
                self.assertEqual(len(rfqs), 1)
                self.assertIn("RFQ-", rfqs[0]["text"])

                # 4. the vendor chat replies YES -> confirmed
                r = h.text(self.webhook, VENDOR_ADDRESS[h.name], "YES 150 @600 in 4h")
                self.assertEqual(r.json().get("action"), "vendor_reply_recorded", r.text)
                self.assertEqual(sourcing.view(run_id)["status"], "COMPLETE")

                # 5. the approver presses Approve -> executed once, approved_by = channel:email
                r = h.button(self.webhook, h.sender, approve[0])
                self.assertEqual(r.json().get("action"), "plan_executed", r.text)
                self.assertEqual(len(self.receipts()), 1)
                self.assertEqual(db.get_receipt(run_id)["approved_by"], f"{h.name}:{DEV_OWNER}")
                self.assertEqual(len(self.pos(run_id)), 1)

                # 6. the receipt is sent back
                self.assertEqual(h.sent()[-1]["to"], h.sender)
                self.assertIn("APPROVED", h.sent()[-1]["text"])

    def test_vendor_without_a_chat_id_is_send_failed(self):
        h = TelegramHarness()
        with self.active(h), mock.patch.object(settings, "SOURCING_MODE", "telegram"):
            self.link(h, DEV_OWNER, h.sender)
            run_id = h.text(self.webhook, h.sender, ALERT).json()["run_id"]
            self.owner.post("/api/v1/sourcing/start", json={"run_id": run_id})
            rfqs = sourcing.view(run_id)["rfqs"]
            self.assertTrue(rfqs and all(r["status"] == "SEND_FAILED" for r in rfqs))
            self.assertIn("No Telegram chat id", rfqs[0]["reply_text"])

    def test_telegram_vendor_address_lookup(self):
        h = TelegramHarness()
        with self.active(h), mock.patch.object(settings, "SOURCING_MODE", "telegram"):
            db.update_rows("suppliers", "id", "SUP-PNY-02", {"telegram_chat_id": "7000001"})
            self.link(h, DEV_OWNER, h.sender)
            run_id = h.text(self.webhook, h.sender, ALERT).json()["run_id"]
            self.owner.post("/api/v1/sourcing/start", json={"run_id": run_id})
            self.assertEqual(sourcing.find_open_rfq_by_address("telegram", "7000001"), (run_id, "SUP-PNY-02"))
            self.assertIsNone(sourcing.find_open_rfq_by_address("telegram", "7000002"))
            self.assertIsNone(sourcing.find_open_rfq_by_address("telegram", ""))
            self.assertIsNone(sourcing.find_open_rfq_by_address("whatsapp", "7000001"))

class SharedVendorAddressTests(_ChannelCase):
    """One vendor address serving two factories: a reply never lands in the wrong one."""

    def test_reply_needs_the_ref_when_two_enquiries_are_open(self):
        for h in (TelegramHarness(), WhatsAppHarness()):
            with self.subTest(channel=h.name), self.active(h),                     mock.patch.object(settings, "SOURCING_MODE", h.name):
                addr = VENDOR_ADDRESS[h.name]
                col = VENDOR_COLUMN[h.name]
                db.update_rows("suppliers", "id", "SUP-PNY-02", {col: addr})
                for sid in ("V1", "V2", "V3"):
                    db.update_rows("suppliers", "id", sid, {col: addr})
                apex = self.apex_run()["run_id"]
                self.owner.post("/api/v1/sourcing/start", json={"run_id": apex})
                tp = self.tp_run()
                r = dev_client(main.app, user=OTHER_OWNER).post("/api/v1/sourcing/start", json={"run_id": tp["run_id"]})
                self.assertEqual(r.status_code, 200, r.text)
                matches = sourcing.find_open_rfqs(h.name, addr)
                self.assertEqual({m[0] for m in matches}, {apex, tp["run_id"]})
                self.assertIsNone(sourcing.find_open_rfq_by_address(h.name, addr))   # never guesses

                before = len(h.sent())
                r = h.text(self.webhook, addr, "YES 100 @600 in 4h")
                self.assertEqual(r.json()["status"], "ambiguous", r.text)
                reply = h.sent()[before]
                self.assertEqual(reply["to"], addr)
                for m in matches:
                    self.assertIn(m[2], reply["text"])
                for run_id in (apex, tp["run_id"]):
                    self.assertTrue(all(x["status"] == "SENT" for x in sourcing.view(run_id)["rfqs"]
                                        if x["supplier_id"] in ("SUP-PNY-02", "V1", "V2", "V3")))

                pick = next(m for m in matches if m[0] == tp["run_id"])
                r = h.text(self.webhook, addr, f"Ref: {pick[2]} YES 100 @600 in 4h")
                self.assertEqual(r.json().get("action"), "vendor_reply_recorded", r.text)
                self.assertEqual(r.json()["run_id"], tp["run_id"])
                self.assertTrue(all(x["status"] == "SENT" for x in sourcing.view(apex)["rfqs"]))

                # a ref belonging to someone else's enquiry is never honoured
                self.assertIsNone(sourcing.match_open_rfq(matches, "Ref: RFQ-ZZZZZZ"))


class ClientTelegramTests(_ChannelCase):
    def _drafted(self):
        run_id = self.apex_run()["run_id"]
        client_agent.draft_extension(run_id, 24)
        order_id = client_agent.view(run_id)["order_id"]
        return run_id, order_id

    def test_approval_sends_to_the_orders_telegram_contact(self):
        h = TelegramHarness()
        with self.active(h), mock.patch.object(settings, "SOURCING_MODE", "telegram"):
            run_id, order_id = self._drafted()
            with self.assertRaises(client_agent.ClientAgentError) as cm:
                client_agent.approve_extension(run_id, "ops-lead")
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("no client contact", str(cm.exception))
            self.assertEqual(client_agent.view(run_id)["status"], "DRAFTED")
            db.update_rows("orders", "order_id", order_id, {"client_contact": "telegram:8800001"})
            self.assertEqual(client_agent.approve_extension(run_id, "ops-lead")["status"], "SENT")
            self.assertEqual([m["to"] for m in h.sent()], ["8800001"])

    def test_failed_send_keeps_the_draft(self):
        h = TelegramHarness()
        with self.active(h), mock.patch.object(settings, "SOURCING_MODE", "telegram"), \
                mock.patch.object(h.channel, "send_text", lambda *a: False):
            run_id, order_id = self._drafted()
            db.update_rows("orders", "order_id", order_id, {"client_contact": "telegram:8800001"})
            with self.assertRaises(client_agent.ClientAgentError) as cm:
                client_agent.approve_extension(run_id, "ops-lead")
            self.assertEqual(cm.exception.status_code, 502)
            self.assertEqual(client_agent.view(run_id)["status"], "DRAFTED")

    def test_a_whatsapp_contact_is_not_used_in_telegram_mode(self):
        h = TelegramHarness()
        with self.active(h), mock.patch.object(settings, "SOURCING_MODE", "telegram"):
            run_id, order_id = self._drafted()
            db.update_rows("orders", "order_id", order_id, {"client_contact": "whatsapp:919845011111"})
            with self.assertRaises(client_agent.ClientAgentError) as cm:
                client_agent.approve_extension(run_id, "ops-lead")
            self.assertEqual(cm.exception.status_code, 409)


class _PollTransport:
    """A Bot API double for the poller: queued getUpdates batches, everything recorded."""

    class _Resp:
        def __init__(self, body):
            self.status_code, self._body = 200, body

        def json(self):
            return self._body

    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json))
        if method == "getUpdates":
            return self._Resp({"ok": True, "result": self.batches.pop(0) if self.batches else []})
        return self._Resp({"ok": True, "result": True})


def _message(update_id, chat_id, text):
    chat = {"id": chat_id, "type": "private"}
    return {"update_id": update_id, "message": {"message_id": 1, "chat": chat, "from": {"id": chat_id}, "text": text}}


class PollerTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        telegram_poll._attempts.clear()

    def tearDown(self):
        db.reset_to_seed()

    def test_poll_once_feeds_the_inbound_flow_and_returns_the_next_offset(self):
        transport = _PollTransport([[_message(41, 5550001, "help"), _message(42, 5550001, "help")]])
        channel = TelegramChannel("TEST-TOKEN", transport=transport)
        offset = asyncio.run(telegram_poll.poll_once(channel, 10, timeout=0))
        self.assertEqual(offset, 43)
        calls = dict((m, b) for m, b in transport.calls)
        self.assertEqual(calls["getUpdates"]["offset"], 10)
        self.assertEqual(calls["getUpdates"]["timeout"], 0)
        self.assertEqual([b["chat_id"] for m, b in transport.calls if m == "sendMessage"], ["5550001", "5550001"])

    def test_empty_poll_keeps_the_offset(self):
        channel = TelegramChannel("TEST-TOKEN", transport=_PollTransport([[]]))
        self.assertEqual(asyncio.run(telegram_poll.poll_once(channel, 7, timeout=0)), 7)

    def test_a_failing_update_is_retried_then_skipped(self):
        transport = _PollTransport([[_message(50, 5550001, "help")]] * 3)
        channel = TelegramChannel("TEST-TOKEN", transport=transport)
        with mock.patch.object(telegram_poll.inbound, "handle", side_effect=RuntimeError("db down")), \
                self.assertLogs("cascadezero.telegram_poll", level="ERROR"):
            self.assertEqual(asyncio.run(telegram_poll.poll_once(channel, 50, timeout=0)), 50)
            self.assertEqual(asyncio.run(telegram_poll.poll_once(channel, 50, timeout=0)), 50)
            self.assertEqual(asyncio.run(telegram_poll.poll_once(channel, 50, timeout=0)), 51)

    def test_a_failed_getupdates_keeps_the_offset(self):
        class Down:
            def post(self, *a, **k):
                raise ConnectionError("https://api.telegram.org/botTEST-TOKEN/getUpdates")
        channel = TelegramChannel("TEST-TOKEN", transport=Down())
        with mock.patch.object(telegram_poll, "ERROR_BACKOFF_S", 0), \
                self.assertLogs("cascadezero.telegram", level="ERROR") as logs:
            self.assertEqual(asyncio.run(telegram_poll.poll_once(channel, 9, timeout=0)), 9)
        self.assertNotIn("TEST-TOKEN", "\n".join(logs.output))

    def test_run_deletes_the_webhook_once_and_persists_the_offset(self):
        transport = _PollTransport([[_message(60, 5550001, "help")]])
        channel = TelegramChannel("TEST-TOKEN", transport=transport)

        class Stop(BaseException):
            pass

        real = telegram_poll.poll_once
        rounds = []

        async def limited(ch, offset, timeout=telegram_poll.POLL_TIMEOUT_S):
            if len(rounds) == 2:
                raise Stop()
            rounds.append(offset)
            return await real(ch, offset, timeout=0)

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "offset")
            with mock.patch.object(telegram_poll, "poll_once", limited):
                with self.assertRaises(Stop):
                    asyncio.run(telegram_poll.run(channel, path))
            self.assertEqual(telegram_poll.load_offset(path), 61)
            self.assertEqual(rounds, [None, 61])
        self.assertEqual([m for m, _ in transport.calls].count("deleteWebhook"), 1)
        self.assertEqual(transport.calls[0][0], "deleteWebhook")

    def test_missing_token_is_a_clean_error(self):
        err = io.StringIO()
        with mock.patch.object(settings, "TELEGRAM_BOT_TOKEN", ""), redirect_stderr(err):
            self.assertEqual(telegram_poll.main(), 1)
        self.assertIn("TELEGRAM_BOT_TOKEN", err.getvalue())


class AdminContactTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()

    def tearDown(self):
        db.reset_to_seed()

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = admin.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_set_vendor_contact(self):
        code, out, _ = self._run("set-vendor-contact", "--supplier", "SUP-PNY-02",
                                 "--channel", "telegram", "--address", "7000001")
        self.assertEqual(code, 0, out)
        self.assertEqual(db.get_supplier("SUP-PNY-02")["telegram_chat_id"], "7000001")
        code, _, _ = self._run("set-vendor-contact", "--supplier", "SUP-PNY-02",
                               "--channel", "whatsapp", "--address", "+91 98450 00001")
        self.assertEqual(code, 0)
        self.assertEqual(db.get_supplier("SUP-PNY-02")["whatsapp_number"], "919845000001")

    def test_set_client_contact(self):
        order_id = db.get_all_orders()[0]["order_id"] if hasattr(db, "get_all_orders") else "EV-402"
        code, _, _ = self._run("set-client-contact", "--order", order_id, "--channel", "telegram",
                               "--address", "8800001")
        self.assertEqual(code, 0)
        self.assertEqual(db.get_order(order_id)["client_contact"], "telegram:8800001")

    def test_bad_input_is_a_clear_error_and_changes_nothing(self):
        for argv in (
            ("set-vendor-contact", "--supplier", "NOPE", "--channel", "telegram", "--address", "1"),
            ("set-vendor-contact", "--supplier", "SUP-PNY-02", "--channel", "telegram", "--address", "@vendor"),
            ("set-vendor-contact", "--supplier", "SUP-PNY-02", "--channel", "whatsapp", "--address", "12"),
            ("set-client-contact", "--order", "NOPE", "--channel", "telegram", "--address", "1"),
        ):
            with self.subTest(argv=argv):
                code, _, err = self._run(*argv)
                self.assertEqual(code, 1)
                self.assertTrue(err.startswith("error:"), err)
        self.assertFalse(db.get_supplier("SUP-PNY-02").get("telegram_chat_id"))


class MigrationColumnTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2] / "supabase"

    def test_columns_in_008_above_the_marker_and_in_schema(self):
        m008 = (self.ROOT / "migrations" / "008_identity.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
        schema = (self.ROOT / "schema.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
        marker = m008.index("APPEND their parts HERE")
        for stmt in (r"ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS telegram_chat_id TEXT;",
                     r"ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_contact TEXT;"):
            with self.subTest(stmt=stmt):
                m = re.search(stmt, m008)
                self.assertIsNotNone(m)
                self.assertLess(m.start(), marker)
        self.assertLess(m008.index("telegram_chat_id"), m008.rindex("INSERT INTO schema_migrations"))
        self.assertRegex(schema, r"telegram_chat_id\s+TEXT")
        self.assertRegex(schema, r"client_contact\s+TEXT")
        orders = re.search(r"CREATE TABLE IF NOT EXISTS orders \((.*?)\n\);", schema, re.S).group(1)
        self.assertRegex(orders, r"due_at\s+TIMESTAMPTZ,")   # the comma is not swallowed by a comment


if __name__ == "__main__":
    unittest.main()
