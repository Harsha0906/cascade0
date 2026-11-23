"""
CascadeZero — the shared inbound flow for every chat channel (Telegram).

`await handle(channel, msg)` runs one inbound message:

  1. de-duplicate on the platform message id (`record_webhook_event`); if processing then fails
     unexpectedly the id is released and the error re-raised, so the platform's retry runs;
  2. `/link <code>` (or `/start <code>`): bind this chat to the user who created the one-time
     code in the dashboard (single use, 15 minutes), for that code's factory;
  3. `/start`, `/help`, `help`: how to link and what to send;
  4. a vendor's reply to an open enquiry (matched on the sender's address for this channel);
  5. `status`: the plant status of the sender's factory;
  6. anything else is a disruption alert: the pipeline runs for the sender's factory and the
     plan summary is sent with an Approve button;
  7. the Approve button executes the plan with `approved_by = "<channel>:<user email>"`, only
     when the sender is linked and holds owner/approver in the RUN's factory (not merely in the
     chat's factory). An unknown/foreign run and a viewer are refused and nothing executes.

Identity: a chat address is linked in `user_channels` (channel, address -> user, factory). The
user's role comes from `factory_members` on every message, so a removed membership takes effect
at once. An unlinked sender is told how to `/link`.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from app import db
from app.agents import sourcing
from app.auth import WRITE_ROLES, Actor
from app.channels.base import Channel, InboundMessage
from app.config import settings
from app.factory_model import FactoryDataError
from app.schemas import ExecutePlanRequest
from app.solver import SolverInputError

logger = logging.getLogger("cascadezero.inbound")

LINK_CODE_TTL = timedelta(minutes=15)
CONTACT_INVITE_TTL = timedelta(days=7)   # Telegram deep-link invites for suppliers and clients
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I: codes are typed by hand
_CODE_LENGTH = 10                                       # ~50 bits; single use, 15 minutes

_LINK_RE = re.compile(r"^(?:/?link|/start)(?:@\w+)?\s+([A-Za-z0-9_-]{4,64})\s*$", re.IGNORECASE)
_HELP_WORDS = {"/start", "/help", "help", "/link", "link"}
_STATUS_WORDS = {"status", "plant", "check", "/status"}

HELP_TEXT = (
    "👋 *CascadeZero*\n"
    "• Link this chat: in the dashboard create a link code, then send /link <code> here.\n"
    "• Send a disruption alert (delay in hours, units short, line, order) to get a recovery plan.\n"
    "• Send *status* for the plant status.\n"
    "Plans can be approved here only by a linked owner or approver."
)
UNLINKED_TEXT = (
    "🔒 This chat is not linked to a CascadeZero user. In the dashboard create a link code, "
    "then send /link <code> here."
)
_LINK_REFUSED = "⛔ That link code is invalid, used or expired. Create a new one in the dashboard."


# ─── Link codes ──────────────────────────────────────────────────────────────

def _hash_code(code: str) -> str:
    """Codes are stored as their SHA-256 hash, so a read of link_codes cannot link a chat."""
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def create_link_code(user_id: str, factory_id: str) -> Dict[str, str]:
    """A one-time code binding a chat to `user_id` in `factory_id`: {code, expires_at (ISO UTC)}."""
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    expires_at = (datetime.now(timezone.utc) + LINK_CODE_TTL).isoformat()
    db.create_link_code(_hash_code(code), user_id, factory_id, expires_at)
    return {"code": code, "expires_at": expires_at}


def _hash_invite(token: str) -> str:
    """Invite tokens are case-sensitive; only their SHA-256 is stored."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def create_contact_invite(factory_id: str, kind: str, target_id: str) -> Dict[str, str]:
    """A single-use Telegram deep-link token (24 URL-safe chars, 7 days) that connects a supplier's
    (kind 'supplier') or an order's client's (kind 'client') chat: {token, expires_at (ISO UTC)}."""
    token = secrets.token_urlsafe(18)
    expires_at = (datetime.now(timezone.utc) + CONTACT_INVITE_TTL).isoformat()
    db.create_contact_invite(_hash_invite(token), factory_id, kind, target_id, expires_at)
    return {"token": token, "expires_at": expires_at}


# ─── Message text ────────────────────────────────────────────────────────────

def status_text(factory_id: Optional[str] = None) -> str:
    state = db.get_full_state(factory_id or settings.DEFAULT_FACTORY_ID)
    lines = [
        f"• {l.get('name', l['line_id'])}: {l.get('status', '?')} "
        f"({l.get('speed_pct', '?')}% speed, {l.get('temp_celsius', '?')}°C)"
        for l in state["production_lines"] if l.get("status") != "NORMAL"
    ]
    orders = [
        f"• Order #{o['order_id']} ({o.get('client', '')}): {o['status']}, "
        f"SLA penalty exposure ₹{o.get('sla_penalty_inr', 0):,}"
        for o in state["orders"] if o.get("status") != "ON_TRACK"
    ]
    if not lines and not orders:
        return "🏭 *PLANT STATUS*\nAll lines normal; all orders on track."
    return "🏭 *PLANT STATUS*\n" + "\n".join(lines + orders)


def winner_summary(result: Dict[str, Any]) -> str:
    winner = next(p for p in result["playbooks"] if p["id"] == result["recommended_plan_id"])
    penalty = result.get("blast_radius", {}).get("sla_penalty_inr", 0)
    mode = result.get("ai_mode", {}).get("overall", "fallback")
    return (
        f"🚨 *CASCADEZERO RECOVERY PLAN* ({result['run_id']})\n"
        f"• Order #{result['order_id']} — ₹{penalty:,} SLA exposure\n"
        f"• Shortfall: {result['shortfall_units']} {result['factory_model'].stock_item_name} (+{result['delay_hours']}h delay)\n\n"
        f"⚖️ *Recommended: {winner['id']}* — {winner['name']}\n"
        f"• Cost: ₹{winner['total_mitigation_cost_inr']:,}\n"
        f"• Modelled P(on-time): {winner['confidence_pct']}%\n"
        f"• Expected cost incl. risk: ₹{winner['expected_cost_inr']:,}\n"
        f"_Numbers from MILP + Monte Carlo; narration mode: {mode}._"
    )


# ─── Identity ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Identity:
    actor: Actor            # memberships used to authorise against a RUN's factory
    factory_id: str         # the factory alerts and status act on
    approved_by: str        # "<channel>:<email>"
    may_plan: bool          # may trigger an analysis
    linked: bool


def _address(channel: Channel, sender: str) -> str:
    normalize = getattr(channel, "normalize_address", None)
    return normalize(sender) if normalize else str(sender)


def identify(channel: Channel, sender: str) -> Optional[Identity]:
    """Who is behind a chat address, or None (unlinked, or linked to a removed membership)."""
    address = _address(channel, sender)
    link = db.get_user_channel(channel.name, address)
    if link is not None:
        member = db.get_member(link["user_id"], link["factory_id"])
        if member is None or not member.get("email"):
            logger.warning("%s chat %s is linked to a user without a membership in %s",
                           channel.name, address, link["factory_id"])
            return None
        # The chat is scoped to its linked factory: the actor carries ONLY that membership, so a
        # chat linked for factory A can never act on factory B even if the user also belongs to B.
        actor = Actor("user", link["user_id"], member["email"], {link["factory_id"]: member["role"]})
        return Identity(actor, link["factory_id"], f"{channel.name}:{member['email']}",
                        member["role"] in WRITE_ROLES, True)
    return None


# ─── The flow ────────────────────────────────────────────────────────────────

def _main():
    """app.main, imported lazily (it imports this module). Its helpers are looked up at call
    time so tests patching `main._execute` / `main._run_pipeline` see their patches."""
    from app import main
    return main


async def handle(channel: Channel, msg: InboundMessage) -> Dict[str, Any]:
    # The id is recorded before processing so a replayed approval or vendor reply can never run
    # twice. On an unexpected failure (database error or any exception) it is released and the
    # error re-raised (503/500), so the platform's retry is processed rather than dropped. Handled
    # outcomes (a reply was sent, including error replies) keep the id recorded.
    message_id = msg.message_id
    if message_id and not await run_in_threadpool(db.record_webhook_event, message_id):
        logger.info("Duplicate %s message %s ignored", channel.name, message_id)
        return {"status": "duplicate"}
    try:
        return await _process(channel, msg)
    except Exception:
        if message_id:
            try:
                await run_in_threadpool(db.release_webhook_event, message_id)
            except Exception:
                logger.exception("Could not release webhook event %s after a processing failure", message_id)
        raise


async def _reply(channel: Channel, to: str, text: str) -> None:
    await run_in_threadpool(channel.send_text, to, text)


async def _process(channel: Channel, msg: InboundMessage) -> Dict[str, Any]:
    sender = msg.sender
    if msg.button_id is not None:
        button_id = msg.button_id
        if button_id.startswith("APPROVE:"):
            return await _approve(channel, sender, button_id)
        if button_id == "VIEW_STATUS":
            identity = await run_in_threadpool(identify, channel, sender)
            if identity is None:
                await _reply(channel, sender, UNLINKED_TEXT)
                return {"status": "unlinked"}
            await _reply(channel, sender, await run_in_threadpool(status_text, identity.factory_id))
            return {"status": "success", "action": "status_sent"}
        return {"status": "ignored"}

    text = msg.text.strip()
    if not text:
        return {"status": "ignored"}

    match = _LINK_RE.match(text)
    if match:
        return await _link(channel, sender, match.group(1))
    if text.lower() in _HELP_WORDS:
        await _reply(channel, sender, HELP_TEXT)
        return {"status": "success", "action": "help_sent"}

    address = _address(channel, sender)
    open_rfq = await run_in_threadpool(sourcing.find_open_rfq_by_address, channel.name, address, text)
    if open_rfq:
        return await _vendor_reply(channel, sender, text, open_rfq)
    matches = await run_in_threadpool(sourcing.find_open_rfqs, channel.name, address) if open_rfq is None else []
    if len(matches) > 1:
        # Several open enquiries for this vendor address (e.g. one vendor, two plants) and the reply
        # quotes no valid ref: never guess; ask for it so a reply cannot land in the wrong factory.
        refs = ", ".join(sorted({m[2] for m in matches}))
        await _reply(channel, sender,
                     f"We have more than one open enquiry for you ({refs}). Please reply again and "
                     f"include the reference, e.g. \"Ref: {matches[0][2]} YES 150 @600 in 4h\".")
        return {"status": "ambiguous", "action": "vendor_ref_needed"}

    identity = await run_in_threadpool(identify, channel, sender)
    if identity is None:
        await _reply(channel, sender, UNLINKED_TEXT)
        return {"status": "unlinked"}
    if text.lower() in _STATUS_WORDS:
        await _reply(channel, sender, await run_in_threadpool(status_text, identity.factory_id))
        return {"status": "ok"}
    if not identity.may_plan:
        await _reply(channel, sender, "⛔ Your role in this factory does not allow running an analysis.")
        return {"status": "forbidden"}
    return await _alert(channel, sender, text, identity)


_INVITE_REFUSED = "⛔ That invite link is invalid, used or expired. Ask the plant for a new one."


async def _connect_contact(channel: Channel, sender: str, token: str) -> Optional[Dict[str, Any]]:
    """`/start <token>` from a supplier's or client's Telegram: store this chat on the invited
    supplier / order, scoped to the invite's factory. None when the token is not a valid invite."""
    invite = await run_in_threadpool(db.consume_contact_invite, _hash_invite(token))
    if invite is None:
        return None
    factory_id, target_id = invite["factory_id"], invite["target_id"]
    address = _address(channel, sender)
    factory = await run_in_threadpool(db.get_factory_row, factory_id)
    if invite["kind"] == "supplier":
        target = await run_in_threadpool(db.get_supplier, target_id)
        if target is None or target.get("factory_id") != factory_id:
            return None
        await run_in_threadpool(db.update_rows_where, "suppliers", {"id": target_id, "factory_id": factory_id},
                                {"telegram_chat_id": address})
        role = target.get("name") or target_id
    else:
        target = await run_in_threadpool(db.get_order, target_id)
        if target is None or target.get("factory_id") != factory_id:
            return None
        await run_in_threadpool(db.update_rows_where, "orders", {"order_id": target_id, "factory_id": factory_id},
                                {"client_contact": f"telegram:{address}"})
        role = f"client of order {target_id}"
    logger.info("telegram chat %s connected to %s (%s %s)", address, factory_id, invite["kind"], target_id)
    await _reply(channel, sender, f"✅ You're connected to {(factory or {}).get('name') or factory_id} as {role}.")
    return {"status": "success", "action": "contact_connected", "kind": invite["kind"]}


async def _link(channel: Channel, sender: str, code: str) -> Dict[str, Any]:
    row = await run_in_threadpool(db.consume_link_code, _hash_code(code))
    if row is None and channel.name == "telegram":
        connected = await _connect_contact(channel, sender, code)
        if connected is not None:
            return connected
        if len(code) >= 20:   # shaped like an invite token, not a typed link code
            logger.warning("Refused a telegram contact invite from %s", _address(channel, sender))
            await _reply(channel, sender, _INVITE_REFUSED)
            return {"status": "forbidden", "action": "invite_refused"}
    member = None
    if row is not None:
        member = await run_in_threadpool(db.get_member, row["user_id"], row["factory_id"])
    if row is None or member is None:
        logger.warning("Refused a %s link code from %s", channel.name, _address(channel, sender))
        await _reply(channel, sender, _LINK_REFUSED)
        return {"status": "forbidden", "action": "link_refused"}
    await run_in_threadpool(db.link_user_channel, channel.name, _address(channel, sender),
                            row["user_id"], row["factory_id"])
    logger.info("%s chat %s linked to %s in %s", channel.name, _address(channel, sender),
                member.get("email"), row["factory_id"])
    await _reply(channel, sender,
                 f"✅ This chat is linked to {member.get('email')} ({row['factory_id']}, role "
                 f"{member['role']}). Send a disruption alert or *status*.")
    return {"status": "success", "action": "linked"}


async def _vendor_reply(channel: Channel, sender: str, text: str, open_rfq) -> Dict[str, Any]:
    run_id, supplier_id = open_rfq
    try:
        await run_in_threadpool(sourcing.record_reply, run_id, supplier_id, text, f"{channel.name}:{sender}")
    except (FactoryDataError, db.DatabaseError, sourcing.SourcingError) as exc:
        logger.error("Vendor reply from %s could not be processed: %s", sender, exc)
        await _reply(channel, sender,
                     "⚠️ We could not process your reply right now. Please contact the plant team directly.")
        return {"status": "error", "detail": str(exc), "run_id": run_id}
    await _reply(channel, sender, "🙏 Thank you — your reply has been recorded. This is not yet a purchase order.")
    return {"status": "success", "action": "vendor_reply_recorded", "run_id": run_id}


async def _alert(channel: Channel, sender: str, text: str, identity: Identity) -> Dict[str, Any]:
    main = _main()
    try:
        result = await run_in_threadpool(main._run_pipeline, text, channel.source_label,
                                         factory_id=identity.factory_id)
    except (FactoryDataError, db.DatabaseError) as exc:
        logger.error("%s pipeline failed, factory data/database unavailable: %s", channel.name, exc)
        await _reply(channel, sender, main._MISCONFIGURED_REPLY)
        return {"status": "error", "detail": "Factory data invalid (details in server log)"}
    except SolverInputError as exc:
        logger.warning("%s pipeline rejected inputs: %s", channel.name, exc)
        await _reply(channel, sender, f"⚠️ Cannot plan for these inputs: {exc}")
        return {"status": "error", "detail": str(exc)}
    winner_id = result["recommended_plan_id"]
    await run_in_threadpool(
        channel.send_buttons, sender, winner_summary(result),
        [(f"APPROVE:{result['run_id']}:{winner_id}", f"Approve {winner_id}"), ("VIEW_STATUS", "Plant status")],
    )
    return {"status": "success", "run_id": result["run_id"]}


async def _approve(channel: Channel, sender: str, button_id: str) -> Dict[str, Any]:
    run_id, _, playbook_id = button_id[len("APPROVE:"):].partition(":")
    identity = await run_in_threadpool(identify, channel, sender)
    if identity is None:
        logger.warning("Rejected %s approval from unlinked %s", channel.name, _address(channel, sender))
        await _reply(channel, sender, UNLINKED_TEXT)
        return {"status": "forbidden"}
    if not run_id or not playbook_id:
        return {"status": "ignored"}

    main = _main()
    # Authorise against the RUN's factory: a run of a factory the sender is not a member of is
    # the same 404 as an unknown run; a member without owner/approver is a 403.
    try:
        run = await run_in_threadpool(main._authorized_run, identity.actor, run_id, WRITE_ROLES,
                                      main._EXECUTE_RUN_GONE)
    except HTTPException as exc:
        logger.warning("Refused %s approval of %s by %s: %s", channel.name, run_id, identity.approved_by, exc.detail)
        await _reply(channel, sender, f"⛔ Not approved: {exc.detail}")
        return {"status": "forbidden", "detail": exc.detail}
    try:
        receipt = await run_in_threadpool(
            main._execute, ExecutePlanRequest(run_id=run_id, playbook_id=playbook_id), identity.approved_by, run,
        )
    except HTTPException as exc:
        await _reply(channel, sender, f"⚠️ Could not execute: {exc.detail}")
        return {"status": "error", "detail": exc.detail}
    await _reply(
        channel, sender,
        f"✅ *APPROVED* {receipt.playbook_id} for run {receipt.run_id}\n"
        f"• Draft PO: {receipt.po_number}\n• Cost: ₹{receipt.total_cost_inr:,}\n"
        f"• Modelled P(on-time): {receipt.confidence_pct}%\n"
        f"Drafts generated; send POs/notices through your normal channels.",
    )
    return {"status": "success", "action": "plan_executed"}
