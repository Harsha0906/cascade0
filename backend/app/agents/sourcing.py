"""
CascadeZero — Sourcing Agent

The planner's vendor numbers (capacity, price, lead time) are assumptions. The Sourcing Agent
replaces them with what vendors actually say, and re-plans when reality differs:

    perceive  → vendor replies (Telegram, or entered by an operator / simulated vendor)
    decide    → who to ask, for how many units; whether to re-plan, ask someone else, or stop
    act       → send enquiries (RFQs), update the plan with confirmed offers, hand back a
                confirmed plan for human approval

Loop for one analysis run:
  1. Send an RFQ to every vendor in the chosen plan ("enquiry, not an order").
  2. Each reply is parsed into a structured offer (Gemini structured output, regex fallback).
     Confirmed / partial offers become per-run vendor overrides; declines and timeouts remove
     the vendor for this run.
  3. When no enquiry is outstanding, re-solve the MILP + Monte Carlo with those overrides.
     If the new best plan relies on a vendor that has not confirmed, ask that vendor (next round).
  4. Stop when the best plan uses only confirmed vendors (or needs none), or after MAX_ROUNDS.
     The result is saved as a new run (`<run_id>-S<round>`) that goes through the normal
     human-approval / execution path.
  5. Coordination with the Client Agent: a session that ends without full cover hands over to
     `client.on_sourcing_failed` (it drafts a deadline-extension request, never sends it), and
     the client's answer comes back through `restart_with_plan`, which starts a new round on the
     re-planned target (longer deadline, or expedite allowed after a refusal).

What the LLM does here: reads free-text vendor replies (English/Hinglish). Who to contact and
whether to re-plan is decided by the optimiser, so decisions stay auditable.

Nothing is ever ordered by this agent: messages are enquiries; purchase orders are created only
after a human approves the confirmed plan.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app import run_store
from app.agents import sourcing_store
from app.config import settings
from app.db import get_all_suppliers, get_supplier, log_agent_step, upsert_row
from app.factory_model import FactoryModel, Vendor, load_factory_model
from app.solver import generate_playbooks

logger = logging.getLogger("cascadezero.sourcing")

_lock = threading.RLock()
_MAX_ATTEMPTS = 3


class SourcingError(Exception):
    """Raised for invalid sourcing requests (unknown run, no open enquiry, ...)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ─── Data model ──────────────────────────────────────────────────────────────

class VendorOffer(BaseModel):
    """Structured reading of a vendor's reply (also used as the Gemini response_schema)."""
    declined: bool = Field(default=False, description="True if the vendor cannot supply at all")
    available_units: Optional[int] = Field(default=None, description="Units the vendor can supply")
    unit_price_inr: Optional[int] = Field(default=None, description="Price per unit in INR (total charter price for air)")
    eta_hours: Optional[float] = Field(default=None, description="Hours until delivery at our plant")
    notes: str = Field(default="", description="Anything else the vendor said, briefly")


@dataclass
class RFQ:
    id: str
    run_id: str
    round: int
    supplier_id: str
    supplier_name: str
    units_requested: int
    expected_unit_price_inr: int
    needed_within_hours: float
    channel: str
    status: str = "SENT"   # SENT | CONFIRMED | PARTIAL | DECLINED | NO_REPLY | SEND_FAILED
    message: str = ""
    offered_units: Optional[int] = None
    offered_unit_price_inr: Optional[int] = None
    offered_eta_hours: Optional[float] = None
    reply_text: str = ""
    parsed_by: str = ""
    reply_source: str = ""
    sent_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    replied_at: Optional[str] = None


@dataclass
class SourcingSession:
    run_id: str
    playbook_id: str
    params: Dict[str, Any]
    model: FactoryModel   # the run's factory snapshot: the plan being sourced was solved on it
    status: str = "ACTIVE"   # ACTIVE | COMPLETE | COMPLETE_UNCONFIRMED | NOTHING_TO_SOURCE
    round: int = 0
    rfqs: List[RFQ] = field(default_factory=list)
    overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    confirmed: set = field(default_factory=set)
    events: List[str] = field(default_factory=list)
    sourced_run_id: Optional[str] = None
    log_step: int = 20
    restart_round: int = 0   # round at the last restart_with_plan; MAX_ROUNDS counts from here
    version: int = 0   # optimistic-concurrency counter; 0 = never saved

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "playbook_id": self.playbook_id,
            "params": self.params,
            "model": self.model.to_dict(),
            "status": self.status,
            "round": self.round,
            "rfqs": [asdict(r) for r in self.rfqs],
            "overrides": self.overrides,
            "confirmed": sorted(self.confirmed),
            "events": list(self.events),
            "sourced_run_id": self.sourced_run_id,
            "log_step": self.log_step,
            "restart_round": self.restart_round,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SourcingSession":
        return cls(
            run_id=d["run_id"],
            playbook_id=d["playbook_id"],
            params=dict(d["params"]),
            model=FactoryModel.from_dict(d["model"]),
            status=d.get("status", "ACTIVE"),
            round=d.get("round", 0),
            rfqs=[RFQ(**r) for r in d.get("rfqs", [])],
            overrides={k: dict(v) for k, v in d.get("overrides", {}).items()},
            confirmed=set(d.get("confirmed", [])),
            events=list(d.get("events", [])),
            sourced_run_id=d.get("sourced_run_id"),
            log_step=d.get("log_step", 20),
            restart_round=d.get("restart_round", 0),
            version=d.get("version", 0),
        )


# ─── Reply parsing (perception) ──────────────────────────────────────────────

_DECLINE = re.compile(
    r"\b(no|nope|nahi|nahin|nai|not\s+available|unavailable|can\s*not|can['’]?t|unable|sorry|"
    r"out\s+of\s+stock|regret|not\s+possible|mushkil|won['’]?t|will\s+not|not\s+able|"
    r"no\s+way|denied|pass\s+on|not\s+(?:in|within|by)\s+\d[\d.]*)\b", re.I)
# An explicit smaller counter-offer inside a decline: "only 100 units", "80 units only",
# "can't do 150 but can do 60 units". Any other reply with a decline cue is a decline.
_NOT_TIME = r"(?!\s*(?:h|hr|hrs|hour|hours|ghante|ghanta|day|days|din)\b)"
_PARTIAL = re.compile(
    r"\bonly\s+(\d(?:[\d,]*\d)?)\b" + _NOT_TIME
    + r"|\b(\d(?:[\d,]*\d)?)\s*(?:units?|pcs|pieces|nos|casings|piece)?\s+only\b"
    + r"|\bbut\s+(?:we\s+)?(?:can|could|will)\s+(?:do|supply|send|manage|give|provide)\s+(\d(?:[\d,]*\d)?)\b"
    + _NOT_TIME, re.I)
_ACCEPT = re.compile(
    r"\b(yes|yeah|ok|okay|haan|han|ha|ji|confirm(?:ed)?|done|sure|can\s+do|available|possible|ho\s*jayega)\b", re.I)
_PRICE = re.compile(r"(?:₹|(?<![a-z])rs\.?|(?<![a-z])inr|@|rate\s*(?:is|:)?)\s*(\d(?:[\d,]*\d)?)", re.I)
_ETA_H = re.compile(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours|ghante|ghanta)\b", re.I)
_ETA_D = re.compile(r"(\d+)\s*(?:day|days|din)\b", re.I)
_UNITS = re.compile(r"(\d[\d,]*)\s*(?:units?|pcs|pieces|nos|casings|qty|piece)\b", re.I)


def _regex_parse(text: str, rfq: RFQ) -> VendorOffer:
    t = text.strip()
    price_m = _PRICE.search(t)
    price = int(price_m.group(1).replace(",", "")) if price_m else None
    eta = None
    if (m := _ETA_H.search(t)):
        eta = float(m.group(1))
    elif (m := _ETA_D.search(t)):
        eta = float(m.group(1)) * 24
    elif re.search(r"\b(tomorrow|kal)\b", t, re.I):
        eta = 24.0
    units = None
    if (m := _UNITS.search(t)):
        units = int(m.group(1).replace(",", ""))
    else:
        # First bare number that is not the price or the ETA.
        used = {s for s in (price_m.group(1) if price_m else None,) if s}
        for n in re.findall(r"\b\d[\d,]*\b", t):
            if n in used or (eta is not None and float(n.replace(",", "")) == eta):
                continue
            units = int(n.replace(",", ""))
            break

    # A decline cue ("not available", "sorry") swallows the accept words inside it, so that
    # "not available" can never read as "available"; an accept cue must stand outside any decline.
    declines = bool(_DECLINE.search(t))
    accepts = bool(_ACCEPT.search(_DECLINE.sub(" ", t)))
    # Any decline cue beats any accept cue ("Yes but unable for 300 units"); only an explicit
    # smaller quantity ("only 100 units") turns a decline into a partial offer. An explicit
    # "only N" is the offered quantity even without a decline cue ("2000 chahiye? only 120 units").
    partial = _PARTIAL.search(t)
    if declines and not partial:
        return VendorOffer(declined=True, available_units=0, notes=t[:200])
    if partial:
        units = int(next(g for g in partial.groups() if g).replace(",", ""))
    if units is None and accepts:
        units = rfq.units_requested   # only an explicit acceptance defaults to the quantity asked for
    if units is None:
        # Could not understand the reply (or a price/ETA with no acceptance): no offer, never a guess.
        return VendorOffer(declined=True, available_units=0, notes=f"Unparsed reply: {t[:180]}")
    return VendorOffer(declined=units == 0, available_units=units, unit_price_inr=price, eta_hours=eta, notes=t[:200])


def _ground_offer(offer: VendorOffer, text: str, rfq: RFQ) -> VendorOffer:
    """Keep only the numbers the vendor actually wrote (as for disruption alerts): Gemini sees our
    enquiry's quantity, price and deadline and could copy them back as the vendor's offer.
    A price or ETA not in the reply becomes None; a quantity not in the reply is kept only for a
    plain acceptance of the requested quantity, otherwise the reply goes to operator review.
    The regex decline cues are a veto: a decline is never read as an acceptance."""
    t = (text or "").strip()
    plain = re.sub(r"(?<=\d),(?=\d)", "", t)
    stated = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", plain)}

    def said(value) -> bool:
        return value is not None and float(value) in stated

    if offer.declined or (_DECLINE.search(t) and not _PARTIAL.search(t)):
        return VendorOffer(declined=True, available_units=0, notes=(offer.notes or t)[:200])
    eta = offer.eta_hours
    if eta is not None and not (said(eta) or (eta % 24 == 0 and said(eta / 24))
                                or (eta == 24 and re.search(r"\b(tomorrow|kal)\b", t, re.I))):
        logger.warning("Gemini returned eta %r, which the reply does not state; ignored", eta)
        eta = None
    price = offer.unit_price_inr if said(offer.unit_price_inr) else None
    if offer.unit_price_inr is not None and price is None:
        logger.warning("Gemini returned price %r, which the reply does not state; ignored", offer.unit_price_inr)
    units = offer.available_units
    accepts = bool(_ACCEPT.search(_DECLINE.sub(" ", t)))
    if units is not None and not said(units) and not (units == rfq.units_requested and accepts):
        logger.warning("Gemini returned %r units, which the reply does not state; operator review", units)
        units = None
    if not units:
        return VendorOffer(declined=True, available_units=0,
                           notes=f"Unparsed reply (operator review): {t[:160]}")
    return VendorOffer(declined=False, available_units=units, unit_price_inr=price, eta_hours=eta,
                       notes=(offer.notes or t)[:200])


def parse_vendor_reply(text: str, rfq: RFQ, item: str = "units") -> Tuple[VendorOffer, str]:
    """Returns (offer, parsed_by) where parsed_by is 'gemini:<model>' or 'regex-fallback'."""
    if settings.has_gemini:
        try:
            from google import genai

            client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options={"timeout": 10000})
            prompt = (
                "A supplier replied to our purchase enquiry. Extract their offer.\n"
                f"Our enquiry: {rfq.units_requested} {item} within "
                f"{rfq.needed_within_hours:g} hours at about ₹{rfq.expected_unit_price_inr}/unit.\n"
                f'Supplier reply: "{text}"\n'
                "Rules: if they accept without a quantity, available_units = our requested quantity. "
                "If they refuse, declined = true and available_units = 0. Leave price/eta empty if not "
                "stated. Do not invent numbers."
            )
            started = time.perf_counter()
            resp = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": VendorOffer},
            )
            from app.agents.tools import usage_tokens
            logger.info("Gemini reply parsing: %s", {
                "latency_ms": round((time.perf_counter() - started) * 1000, 1), **usage_tokens(resp)})
            if resp.text:
                offer = _ground_offer(VendorOffer(**json.loads(resp.text)), text, rfq)
                return offer, f"gemini:{settings.GEMINI_MODEL}"
        except Exception as exc:
            logger.warning("Gemini reply parsing failed (%s) — using regex fallback", exc)
    return _regex_parse(text, rfq), "regex-fallback"


# ─── Helpers ─────────────────────────────────────────────────────────────────


def outbound_channel(name: str):
    """The channel adapter for outbound vendor/client messages, resolved from app.main at call
    time (the same factories the webhooks use, so tests patching them cover both directions)."""
    from app import main
    return main._telegram_channel()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _factory_of(session: SourcingSession) -> str:
    return session.params.get("factory_id") or session.model.factory_id


def _log(session: SourcingSession, summary: str, message: str, tool: str) -> None:
    session.events.append(message)
    session.log_step += 1
    log_agent_step(
        factory_id=_factory_of(session),
        run_id=session.run_id, step_order=session.log_step,
        agent_name="Sourcing Agent", agent_role="Vendor Confirmation", badge_color="violet",
        tool_called=tool, tool_output_summary=summary, message=message,
    )


def _persist(session: SourcingSession, rfq: RFQ) -> None:
    row = {**asdict(rfq), "factory_id": _factory_of(session)}
    upsert_row("sourcing_rfqs", row)


def _is_charter(vendor: Vendor) -> bool:
    """A charter vendor is paid a flat fee, not per unit: its quoted price is the charter total."""
    return vendor.flat_cost > 0 and vendor.unit_cost == 0


def _rfq_text(model: FactoryModel, rfq: RFQ) -> str:
    vendor = model.vendor(rfq.supplier_id)
    item = model.stock_item_name
    if _is_charter(vendor):
        ask = f"a dedicated delivery of {rfq.units_requested} {item} for a flat fee"
        price = f"(our reference: ₹{vendor.flat_cost:,} total)"
    else:
        ask = f"{rfq.units_requested} {item}"
        price = f"at about ₹{rfq.expected_unit_price_inr}/unit"
    return (
        f"Namaste {rfq.supplier_name.split(' (')[0]} team — {model.name} purchase desk here.\n"
        f"ENQUIRY (not a purchase order): can you deliver {ask} to our plant "
        f"within {rfq.needed_within_hours:g} hours {price}?\n"
        f"Please reply with quantity, price and delivery time, e.g. \"YES 150 pcs @600 in 4h\" or \"NO\".\n"
        f"Ref: {rfq.id}"
    )


def _send_rfq(session: SourcingSession, supplier_id: str, units: int) -> RFQ:
    model = session.model
    vendor = model.vendor(supplier_id)
    override = session.overrides.get(supplier_id, {})
    rfq = RFQ(
        id=f"RFQ-{uuid.uuid4().hex[:6].upper()}",
        run_id=session.run_id,
        round=session.round,
        supplier_id=supplier_id,
        supplier_name=vendor.name,
        units_requested=units,
        expected_unit_price_inr=int(override.get("unit_cost", vendor.unit_cost)),
        needed_within_hours=max(1.0, round(session.params["deadline_hours"] - model.qa_dispatch_hours - 1, 1)),
        channel=settings.SOURCING_MODE,
    )
    rfq.message = _rfq_text(model, rfq)

    mode = settings.SOURCING_MODE
    if mode == "telegram":
        chat_id = str((get_supplier(supplier_id) or {}).get("telegram_chat_id") or "").strip()
        if not chat_id:
            rfq.status = "SEND_FAILED"
            rfq.reply_text = ("No Telegram chat id on file for this vendor "
                              "(python -m app.admin set-vendor-contact).")
        elif not outbound_channel("telegram").send_text(chat_id, rfq.message):
            rfq.status = "SEND_FAILED"
            rfq.reply_text = ("Telegram send failed (check TELEGRAM_BOT_TOKEN; a vendor must have "
                              "started the bot first).")
    if rfq.status == "SEND_FAILED":
        session.overrides[supplier_id] = {"max_units": 0}
        rfq.replied_at = _now().isoformat()

    session.rfqs.append(rfq)
    _persist(session, rfq)
    return rfq


def _expire_timeouts(session: SourcingSession) -> List[RFQ]:
    expired = []
    cutoff = _now() - timedelta(minutes=settings.SOURCING_REPLY_TIMEOUT_MIN)
    for rfq in session.rfqs:
        if rfq.status == "SENT" and datetime.fromisoformat(rfq.sent_at) < cutoff:
            rfq.status = "NO_REPLY"
            rfq.replied_at = _now().isoformat()
            session.overrides[rfq.supplier_id] = {"max_units": 0}
            session.confirmed.discard(rfq.supplier_id)
            _persist(session, rfq)
            expired.append(rfq)
    return expired


def _solve(session: SourcingSession):
    p = session.params
    return generate_playbooks(
        model=session.model,
        shortfall_units=p["shortfall_units"],
        delay_hours=p["delay_hours"],
        line_speeds=p["line_speeds"],
        order_id=p["order_id"],
        sla_penalty_inr=p["sla_penalty_inr"],
        partial_penalty_inr=p["partial_penalty_inr"],
        deadline_hours=p["deadline_hours"],
        client=p["client"],
        vendor_overrides=session.overrides,
        confirmed_vendor_ids=session.confirmed,
        renegotiation_acceptance=p.get("renegotiation_acceptance"),
        renegotiation_used=bool(p.get("renegotiation_used")),
    )


def _unconfirmed_needs(playbook: Dict[str, Any], session: SourcingSession) -> Dict[str, int]:
    return {
        a["supplier_id"]: a["units_allocated"]
        for a in playbook["vendor_allocations"]
        if a["supplier_id"] not in session.confirmed
    }


def _finish(session: SourcingSession, result, status: str, reason: str) -> None:
    base = run_store.get_run(session.run_id) or {}
    sourced = dict(base)
    sourced_id = f"{session.run_id}-S{max(1, session.round)}"
    sourced.update({
        "run_id": sourced_id,
        "parent_run_id": session.run_id,
        "playbooks": [p.model_dump() for p in result.playbooks],
        "recommended_plan_id": result.recommended_plan_id,
        "solver_result": result.model_dump(),
        "sourcing_status": status,
    })
    if isinstance(sourced.get("blast_radius"), dict):
        # After a client-agreed extension the session plans against the new deadline.
        sourced["blast_radius"] = {**sourced["blast_radius"], "hours_remaining": session.params["deadline_hours"]}
    run_store.save_run(sourced)
    session.sourced_run_id = sourced_id
    session.status = status
    winner = next(p for p in result.playbooks if p.recommended)
    _log(
        session,
        f"{status}: {winner.id} — {winner.description}",
        f"🤝 {reason} Recommended {winner.id}: ₹{winner.total_mitigation_cost_inr:,}, "
        f"P(on-time) {winner.confidence_pct}%. Ready for human approval as run {sourced_id}.",
        "finalise_sourced_plan()",
    )
    if not _fully_covered(status, winner):
        # Hand over to the Client Agent: it drafts an extension request (sends nothing) unless
        # a request for this run is already open. Imported here: client imports this module.
        from app.agents import client

        try:
            drafted = client.on_sourcing_failed(session.run_id, reason=reason)
        except client.ClientAgentError as exc:
            _log(session, f"Client Agent could not draft: {exc}",
                 f"⚠ Not fully covered, and no extension request could be drafted: {exc}",
                 "client.on_sourcing_failed()")
        else:
            if drafted is not None:
                _log(session, f"Client Agent drafted a {drafted['extension_hours']}h extension request",
                     f"📝 Not fully covered → Client Agent drafted a {drafted['extension_hours']}h deadline-"
                     f"extension request for {drafted['order_id']} (awaiting human approval; nothing sent).",
                     "client.on_sourcing_failed()")


def _fully_covered(status: str, winner) -> bool:
    """True when the finished plan covers the shortfall in time with confirmed supply (or needs none)."""
    if status == "COMPLETE_UNCONFIRMED" or not winner.feasible or winner.uncovered_units:
        return False
    if winner.strategy_type == "SLA_RENEGOTIATION":
        return False   # the plan is to ask the client to wait
    if winner.strategy_type == "NO_ACTION" and winner.confidence_pct < 100.0:
        return False   # accepting the breach is not cover
    return True


def _advance(session: SourcingSession) -> None:
    """Decide what to do next. Called after every reply and on every status check."""
    if session.status != "ACTIVE":
        return
    for rfq in _expire_timeouts(session):
        _log(session, f"{rfq.supplier_name}: no reply within {settings.SOURCING_REPLY_TIMEOUT_MIN} min",
             f"⏱ No reply from {rfq.supplier_name.split(' (')[0]}; dropping them for this run.",
             "expire_enquiry()")
    if any(r.status == "SENT" for r in session.rfqs):
        return  # still waiting for replies

    result = _solve(session)
    winner = next(p for p in result.playbooks if p.recommended).model_dump()
    needs = _unconfirmed_needs(winner, session)
    if not needs:
        reason = (
            "All suppliers in the best plan have confirmed."
            if winner["vendor_allocations"] else
            "Best plan after vendor replies needs no supplier purchase."
        )
        _finish(session, result, "COMPLETE", reason)
        return
    if session.round - session.restart_round >= settings.SOURCING_MAX_ROUNDS:
        _finish(session, result, "COMPLETE_UNCONFIRMED",
                f"Stopped after {session.round - session.restart_round} rounds; "
                       f"some suppliers in the plan are still unconfirmed.")
        return

    session.round += 1
    sent = [_send_rfq(session, sid, units) for sid, units in needs.items()]
    names = ", ".join(f"{r.supplier_name.split(' (')[0]} ({r.units_requested}u)" for r in sent)
    _log(session, f"Round {session.round}: re-planned → asking {names}",
         f"🔁 Re-planned with confirmed offers (best now: {winner['id']}). Asking {names}.",
         "solve_pulp_milp(vendor_overrides) + send_rfq()")
    if any(r.status == "SEND_FAILED" for r in sent):
        _advance(session)


# ─── Public API ──────────────────────────────────────────────────────────────

def start_sourcing(run_id: str, playbook_id: Optional[str] = None) -> Dict[str, Any]:
    with _lock:
        if sourcing_store.load(run_id) is not None:
            return view(run_id)
        run = run_store.get_run(run_id)
        if run is None:
            raise SourcingError("Unknown or expired run_id; run the analysis again.", 404)
        if run.get("parent_run_id"):
            raise SourcingError("This run is already a sourced plan.", 409)
        pid = playbook_id or run["recommended_plan_id"]
        playbook = next((p for p in run["playbooks"] if p["id"] == pid), None)
        if playbook is None:
            raise SourcingError(f"Playbook {pid} not in run {run_id}", 404)

        br = run.get("blast_radius") or {}
        for key in ("sla_penalty_inr", "partial_delay_penalty_inr", "hours_remaining", "client"):
            if key not in br:
                raise SourcingError(f"Run {run_id} has no blast_radius.{key}; run the analysis again.", 409)
        factory_id = run.get("factory_id")
        # Source against the factory data the plan was solved on, not today's database rows.
        model = run.get("factory_model") or load_factory_model(factory_id)   # FactoryDataError propagates
        line_speeds = run["line_speeds"]
        session = SourcingSession(
            run_id=run_id,
            playbook_id=pid,
            model=model,
            params={
                "factory_id": factory_id,
                "shortfall_units": run["shortfall_units"],
                "delay_hours": run["delay_hours"],
                "line_speeds": dict(line_speeds),
                "order_id": run["order_id"],
                "sla_penalty_inr": int(br["sla_penalty_inr"]),
                "partial_penalty_inr": int(br["partial_delay_penalty_inr"]),
                "deadline_hours": float(br["hours_remaining"]),
                "client": br["client"],
            },
        )
        if not playbook["vendor_allocations"]:
            result = _solve(session)
            _finish(session, result, "NOTHING_TO_SOURCE", f"{pid} needs no supplier purchase.")
            return _save_new(session)

        session.round = 1
        sent = [_send_rfq(session, a["supplier_id"], a["units_allocated"]) for a in playbook["vendor_allocations"]]
        names = ", ".join(f"{r.supplier_name.split(' (')[0]} ({r.units_requested}u)" for r in sent)
        _log(session, f"Round 1 ({settings.SOURCING_MODE}): enquiries sent to {names}",
             f"📨 Checking {pid} with suppliers before approval. Enquiries sent to {names} "
             f"({'via Telegram' if settings.SOURCING_MODE == 'telegram' else 'simulated channel — enter replies on the dashboard'}).",
             "send_rfq()")
        if any(r.status == "SEND_FAILED" for r in sent):
            _advance(session)
        # Persist only once the first-round enquiries exist: a failure above leaves no half-built session.
        return _save_new(session)


def _save_new(session: SourcingSession) -> Dict[str, Any]:
    try:
        sourcing_store.save(session)
    except sourcing_store.ConcurrentUpdateError:
        pass  # another worker started this run first; serve its session
    return view(session.run_id)


def record_reply(run_id: str, supplier_id: str, text: str, source: str = "operator") -> Dict[str, Any]:
    # Known multi-worker limitation: a retry re-runs reply side effects (re-planning may re-send RFQs),
    # and RFQs sent by the loser of a concurrent start are orphaned (the winner's session is served).
    with _lock:
        for _ in range(_MAX_ATTEMPTS):
            session = sourcing_store.load(run_id)
            if session is None:
                raise SourcingError("No sourcing session for this run.", 404)
            _apply_reply(session, supplier_id, text, source)
            try:
                sourcing_store.save(session)
            except sourcing_store.ConcurrentUpdateError:
                continue   # the session changed underneath us: reload and re-apply
            return view(run_id)
        raise SourcingError("Sourcing session changed concurrently; retry", 409)


def _apply_reply(session: SourcingSession, supplier_id: str, text: str, source: str) -> None:
    if session.status != "ACTIVE":
        raise SourcingError(f"Sourcing already finished ({session.status}).", 409)
    rfq = next((r for r in reversed(session.rfqs) if r.supplier_id == supplier_id and r.status == "SENT"), None)
    if rfq is None:
        raise SourcingError(f"No open enquiry for {supplier_id} in this run.", 409)

    offer, parsed_by = parse_vendor_reply(text, rfq, session.model.stock_item_name)
    rfq.reply_text = text[:500]
    rfq.parsed_by = parsed_by
    rfq.reply_source = source
    rfq.replied_at = _now().isoformat()
    units = max(0, int(offer.available_units or 0))
    if offer.declined or units == 0:
        rfq.status = "DECLINED"
        rfq.offered_units = 0
        session.overrides[supplier_id] = {"max_units": 0}
        session.confirmed.discard(supplier_id)
    else:
        vendor = session.model.vendor(supplier_id)
        rfq.status = "CONFIRMED" if units >= rfq.units_requested else "PARTIAL"
        rfq.offered_units = units
        rfq.offered_eta_hours = offer.eta_hours if offer.eta_hours is not None else vendor.lead_hours
        # The vendor's own ETA replaces the planning model's (possibly route-shifted) lead, and the
        # minimum lead never floors it above what the vendor promised (else MILP and MC disagree).
        override: Dict[str, Any] = {"max_units": units, "lead_hours": rfq.offered_eta_hours,
                                    "min_lead_hours": min(vendor.min_lead_hours, rfq.offered_eta_hours)}
        if offer.eta_hours is not None:
            override["confirmed_eta_hours"] = offer.eta_hours   # the vendor's own promise (delivery outcomes)
        if _is_charter(vendor):
            rfq.offered_unit_price_inr = offer.unit_price_inr or vendor.flat_cost  # quoted as charter total
            override["flat_cost"] = rfq.offered_unit_price_inr
        else:
            rfq.offered_unit_price_inr = offer.unit_price_inr or rfq.expected_unit_price_inr
            override["unit_cost"] = rfq.offered_unit_price_inr
        session.overrides[supplier_id] = override
        session.confirmed.add(supplier_id)
    _persist(session, rfq)

    offer_txt = (
        "declined" if rfq.status == "DECLINED" else
        f"{rfq.status.lower()}: {rfq.offered_units}u @ ₹{rfq.offered_unit_price_inr:,} in {rfq.offered_eta_hours:g}h"
    )
    _log(session, f"{rfq.supplier_name}: {offer_txt} (parsed by {parsed_by})",
         f"📩 {rfq.supplier_name.split(' (')[0]} replied \"{text[:80]}\" → {offer_txt}.",
         f"parse_vendor_reply({parsed_by})")
    _advance(session)


def restart_with_plan(root_run_id: str, playbook: Dict[str, Any], reason: str, *,
                      params_update: Optional[Dict[str, Any]] = None,
                      allow_vendor_ids: Tuple[str, ...] = ()) -> Dict[str, Any]:
    """Start a new sourcing round on `playbook` (re-planned by the Client Agent).

    `params_update` changes the session's planning inputs (a longer `deadline_hours`, the
    client's `renegotiation_acceptance`); `allow_vendor_ids` lifts earlier declines/timeouts for
    those vendors so they are asked again. Confirmed offers are kept: RFQs go only to the plan's
    vendors that have not confirmed. Enquiries still open from the previous round are superseded.
    Known limitation (as for record_reply): a concurrent-update retry re-sends this round's RFQs.
    """
    with _lock:
        for _ in range(_MAX_ATTEMPTS):
            session = sourcing_store.load(root_run_id)
            if session is None:
                raise SourcingError("No sourcing session for this run.", 404)
            _apply_restart(session, playbook, reason, params_update or {}, tuple(allow_vendor_ids))
            try:
                sourcing_store.save(session)
            except sourcing_store.ConcurrentUpdateError:
                continue
            return view(root_run_id)
        raise SourcingError("Sourcing session changed concurrently; retry", 409)


def _apply_restart(session: SourcingSession, playbook: Dict[str, Any], reason: str,
                   params_update: Dict[str, Any], allow_vendor_ids: Tuple[str, ...]) -> None:
    known = {v.supplier_id for v in session.model.vendors}
    unknown = sorted({a["supplier_id"] for a in playbook.get("vendor_allocations", [])} - known)
    if unknown:
        raise SourcingError(f"Plan uses vendors not in this run's factory model: {unknown}", 409)
    for rfq in session.rfqs:
        if rfq.status == "SENT":
            rfq.status = "SUPERSEDED"
            rfq.replied_at = _now().isoformat()
            _persist(session, rfq)
    session.params.update(params_update)
    for sid in allow_vendor_ids:
        if sid not in session.confirmed:
            session.overrides.pop(sid, None)
    session.status = "ACTIVE"
    session.playbook_id = playbook["id"]
    session.restart_round = session.round
    session.round += 1   # a new round (and a new sourced run id) even when nothing is asked
    needs = _unconfirmed_needs(playbook, session)
    if not needs:
        _log(session, f"Restart on {playbook['id']}: nothing new to ask",
             f"🔁 {reason} Re-planned target {playbook['id']} needs no new enquiry.",
             "restart_with_plan()")
        _advance(session)   # re-solves with the new inputs; finishes or asks the winner's vendors
        return
    sent = [_send_rfq(session, sid, units) for sid, units in needs.items()]
    names = ", ".join(f"{r.supplier_name.split(' (')[0]} ({r.units_requested}u)" for r in sent)
    _log(session, f"Round {session.round} (restart on {playbook['id']}): asking {names}",
         f"🔁 {reason} New target {playbook['id']}: enquiries sent to {names} "
         f"(needed within {sent[0].needed_within_hours:g}h).",
         "restart_with_plan() + send_rfq()")
    if any(r.status == "SEND_FAILED" for r in sent):
        _advance(session)


_ADDRESS_COLUMN = {"telegram": "telegram_chat_id"}
_REF_RE = re.compile(r"RFQ-[A-Z0-9]{6}", re.IGNORECASE)


def _same_address(channel: str, stored: Any, wanted: str) -> bool:
    return bool(str(stored or "").strip()) and str(stored).strip() == str(wanted or "").strip()


def find_open_rfqs(channel: str, address: str) -> List[Tuple[str, str, str]]:
    """Every open enquiry (run_id, supplier_id, rfq_id) addressed to this chat on `channel`,
    across all factories (a vendor may supply several plants from one number)."""
    column = _ADDRESS_COLUMN.get(channel)
    if column is None or not str(address or "").strip():
        return []
    supplier_ids = {s["id"] for s in get_all_suppliers() if _same_address(channel, s.get(column), address)}
    if not supplier_ids:
        return []
    found = []
    for session in sourcing_store.active():
        for rfq in reversed(session.rfqs):
            if rfq.supplier_id in supplier_ids and rfq.status == "SENT":
                found.append((session.run_id, rfq.supplier_id, rfq.id))
    return found


def match_open_rfq(matches: List[Tuple[str, str, str]], text: str = "") -> Optional[Tuple[str, str, str]]:
    """The one enquiry a reply belongs to: the only open one, or the one whose `Ref: RFQ-XXXXXX`
    the reply quotes (only among this vendor's own open enquiries). None when ambiguous."""
    if len(matches) == 1:
        return matches[0]
    refs = {r.upper() for r in _REF_RE.findall(text or "")}
    chosen = [m for m in matches if m[2].upper() in refs]
    return chosen[0] if len(chosen) == 1 else None


def find_open_rfq_by_address(channel: str, address: str, text: str = "") -> Optional[Tuple[str, str]]:
    """Map an inbound chat sender to (run_id, supplier_id) with an open enquiry. Never guesses
    between several: with more than one open it needs the reply to quote the RFQ ref."""
    m = match_open_rfq(find_open_rfqs(channel, address), text)
    return (m[0], m[1]) if m else None


def view(run_id: str) -> Dict[str, Any]:
    with _lock:
        for attempt in range(_MAX_ATTEMPTS):
            session = sourcing_store.load(run_id)
            if session is None:
                raise SourcingError("No sourcing session for this run.", 404)
            before = session.to_dict()
            _advance(session)   # may expire timeouts / re-plan; persist whatever changed
            if session.to_dict() == before:
                break
            try:
                sourcing_store.save(session)
                break
            except sourcing_store.ConcurrentUpdateError:
                if attempt == _MAX_ATTEMPTS - 1:
                    raise SourcingError("Sourcing session changed concurrently; retry", 409)
        sourced = run_store.get_run(session.sourced_run_id) if session.sourced_run_id else None
        return {
            "run_id": session.run_id,
            "playbook_id": session.playbook_id,
            "status": session.status,
            "mode": settings.SOURCING_MODE,
            "round": session.round,
            "max_rounds": settings.SOURCING_MAX_ROUNDS,
            "reply_timeout_min": settings.SOURCING_REPLY_TIMEOUT_MIN,
            "rfqs": [asdict(r) for r in session.rfqs],
            "events": list(session.events),
            "sourced_run_id": session.sourced_run_id,
            "deadline_hours": session.params.get("deadline_hours"),
            "playbooks": sourced["playbooks"] if sourced else [],
            "recommended_plan_id": sourced["recommended_plan_id"] if sourced else None,
        }
