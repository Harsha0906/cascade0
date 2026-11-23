"""
CascadeZero — Client Agent

Negotiates a deadline extension with the customer when the shortfall cannot be covered in time,
and coordinates the answer with the Sourcing Agent through one durable record per root run
(table `order_coordination`, optimistic concurrency like `sourcing_sessions`):

    perceive  → the run (cause, shortfall), the order row (due_at, partial-delay penalty, client
                contact), the Sourcing Agent's session, and the client's answer
    decide    → how long an extension to ask for (the operator's figure, or the run's upstream
                delay when drafted after a sourcing failure); which plan to source after the answer
                (accepted: the re-planned winner on the longer deadline; refused: the expedite plan)
    act       → draft the request (DRAFTED), send it only after a named human approves it (SENT),
                extend the order's due_at, re-plan, and restart sourcing on the new target

Status: DRAFTED → (APPROVED, transient while sending) → SENT → (ANSWERING, resumable) →
ACCEPTED | REFUSED. A failed send returns to DRAFTED; a failed answer step stays ANSWERING
and is resumed by recording the same answer again.
Lock order: sourcing → client is allowed; client → sourcing is forbidden (see the answer section).
One open negotiation per root run: while a request is DRAFTED/APPROVED/SENT/ANSWERING a sourcing
failure never drafts another. After an ACCEPTED extension the renegotiation plan is no longer
offered by re-plans (the deadline already is the extended one); if sourcing then fails again the
Client Agent drafts a follow-up request (request_number + 1; the earlier request moves to
`history`). After a REFUSED answer nothing more is drafted; the failure is logged.

Human sign-off: nothing reaches the client before `approve_extension(..., approved_by)`.
Sending uses the Sourcing Agent's channel setting (`SOURCING_MODE`): simulated records the
message; telegram sends it to the order's `client_contact` ("telegram:<chat_id>", set with `python -m app.admin
set-client-contact`); 409 "no client contact" when there is none.
The message quotes only data (order id, client, deadlines, the disruption headline, the order's
partial-delay penalty); no number is written by an LLM.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app import db, run_store
from app.agents import sourcing, sourcing_store
from app.config import settings
from app.deadlines import deadline_hours, parse_timestamp
from app.solver import SolverInputError, generate_playbooks

logger = logging.getLogger("cascadezero.client_agent")

_TABLE = "order_coordination"
_lock = threading.RLock()
_store_lock = threading.Lock()


class ClientAgentError(Exception):
    """Invalid Client Agent request (unknown run, wrong state, bad input...)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ConcurrentUpdateError(RuntimeError):
    """The stored coordination record changed since it was loaded."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC")


# ─── Durable record (compare-and-set on `version`) ───────────────────────────

def load(root_run_id: str) -> Optional[Dict[str, Any]]:
    row = db.fetch_by_id(_TABLE, "root_run_id", root_run_id)
    if row is None:
        return None
    record = copy.deepcopy(row["payload"])
    record["version"] = int(row["version"])
    return record


def save(record: Dict[str, Any]) -> None:
    """Persist `record`; ConcurrentUpdateError if the stored version is not the loaded one."""
    current = int(record.get("version", 0))
    next_version = current + 1
    payload = json.loads(json.dumps({**record, "version": next_version}))
    row = {
        "root_run_id": record["root_run_id"],
        "order_id": record["order_id"],
        "factory_id": record["factory_id"],
        "status": record["status"],
        "version": next_version,
        "updated_at": _now().isoformat(),
        "payload": payload,
    }
    with _store_lock:
        if current == 0:
            if db.fetch_by_id(_TABLE, "root_run_id", record["root_run_id"]) is not None:
                raise ConcurrentUpdateError(record["root_run_id"])
            try:
                db.insert_row(_TABLE, row)
            except db.DatabaseError:
                if db.fetch_by_id(_TABLE, "root_run_id", record["root_run_id"]) is not None:
                    raise ConcurrentUpdateError(record["root_run_id"])
                raise
        else:
            updates = {k: v for k, v in row.items() if k != "root_run_id"}
            if not db.update_rows_where(_TABLE, {"root_run_id": record["root_run_id"], "version": current}, updates):
                raise ConcurrentUpdateError(record["root_run_id"])
    record["version"] = next_version


def _save_or_409(record: Dict[str, Any]) -> None:
    try:
        save(record)
    except ConcurrentUpdateError:
        raise ClientAgentError("The extension request changed concurrently; reload and retry.", 409)


# ─── Perception helpers ──────────────────────────────────────────────────────

def _root(run_id: str) -> tuple[str, Dict[str, Any]]:
    run = run_store.get_run(run_id)
    if run is None:
        raise ClientAgentError("Unknown or expired run_id; run the analysis again.", 404)
    root_id = run.get("parent_run_id") or run_id
    root = run if root_id == run_id else run_store.get_run(root_id)
    if root is None:
        raise ClientAgentError(f"Root run {root_id} not found.", 404)
    return root_id, root


def _order(order_id: str) -> Dict[str, Any]:
    order = db.get_order(order_id)
    if order is None:
        raise ClientAgentError(f"Order {order_id} not found.", 409)
    return order


def _log(record: Dict[str, Any], summary: str, message: str, tool: str) -> None:
    record.setdefault("events", []).append(message)
    record["log_step"] = int(record.get("log_step", 40)) + 1
    db.log_agent_step(
        factory_id=record.get("factory_id"),
        run_id=record["root_run_id"], step_order=record["log_step"],
        agent_name="Client Agent", agent_role="Deadline Negotiation", badge_color="amber",
        tool_called=tool, tool_output_summary=summary, message=message,
    )


def _public(record: Dict[str, Any], run_id: Optional[str] = None) -> Dict[str, Any]:
    out = copy.deepcopy(record)
    out["run_id"] = run_id or record["root_run_id"]
    out["mode"] = settings.SOURCING_MODE
    return out


# ─── Draft ───────────────────────────────────────────────────────────────────

def draft_extension(run_id: str, extension_hours: int, reason: str = "") -> Dict[str, Any]:
    return _draft(run_id, extension_hours, reason, drafted_by="operator")


# Fields of one request; a follow-up moves them into `history` and starts afresh.
_REQUEST_FIELDS = (
    "request_number", "status", "drafted_by", "drafted_at", "extension_hours", "reason", "original_due_at",
    "proposed_due_at", "partial_penalty_inr", "draft_message", "approved_by", "approved_at", "answer",
    "new_due_at", "replan_deadline_hours", "replan_run_id", "replan_recommended_plan_id",
    "sourcing_target_plan_id", "sourcing_restarted",
)


def _request_number(record: Optional[Dict[str, Any]]) -> int:
    return int((record or {}).get("request_number") or 1)


def _renegotiation_used(record: Optional[Dict[str, Any]]) -> bool:
    """True once the client has granted an extension for this run (any earlier request)."""
    return any(h.get("status") == "ACCEPTED" for h in (record or {}).get("history", []))


def _draft(run_id: str, extension_hours: int, reason: str, drafted_by: str,
           follow_up: bool = False) -> Dict[str, Any]:
    if isinstance(extension_hours, bool) or not isinstance(extension_hours, int) or extension_hours <= 0:
        raise ClientAgentError("extension_hours must be a positive whole number of hours.", 422)
    with _lock:
        root_id, root = _root(run_id)
        existing = load(root_id)
        if follow_up:
            if existing is None or existing["status"] != "ACCEPTED" or not existing.get("replan_run_id"):
                raise ClientAgentError("A follow-up request needs an earlier ACCEPTED extension.", 409)
            earlier = {k: copy.deepcopy(existing.get(k)) for k in _REQUEST_FIELDS}
            earlier["request_number"] = _request_number(existing)
            existing.setdefault("history", []).append(earlier)
            for k in _REQUEST_FIELDS:
                existing[k] = None
            existing["request_number"] = earlier["request_number"] + 1
        elif existing is not None and existing["status"] != "DRAFTED":
            raise ClientAgentError(
                f"An extension request for this run is already {existing['status']}; only a draft can be changed.", 409)

        order_id = root.get("order_id")
        order = _order(order_id)
        if not order.get("due_at"):
            raise ClientAgentError(f"Order {order_id} has no due_at; its deadline cannot be extended.", 409)
        partial = order.get("partial_delay_penalty_inr")
        if partial is None:
            raise ClientAgentError(f"Order {order_id} has no partial_delay_penalty_inr to offer.", 409)
        cause = root.get("crisis_headline")
        if not cause:
            raise ClientAgentError(f"Run {root_id} has no crisis_headline to quote as the cause.", 409)
        model = root.get("factory_model")
        client_name = order.get("client") or (root.get("blast_radius") or {}).get("client")
        if not client_name:
            raise ClientAgentError(f"Order {order_id} has no client name.", 409)
        session = sourcing_store.load(root_id)

        original = parse_timestamp(order["due_at"])
        proposed = original + timedelta(hours=extension_hours)
        factory_name = model.name if model is not None else db.default_factory_name()
        message = (
            f"Dear {client_name} team,\n"
            f"{factory_name} here regarding Order #{order_id}.\n"
            f"Cause: {cause}.\n"
            f"Original deadline: {_fmt(original)}. We request an extension of {extension_hours} hours, "
            f"to {_fmt(proposed)}.\n"
            f"We offer a partial-delay payment of ₹{int(partial):,} for this extension.\n"
            f"Please reply ACCEPT or DECLINE. Ref: {root_id}"
        )
        record = existing or {
            "root_run_id": root_id, "order_id": order_id,
            "factory_id": root.get("factory_id") or (model.factory_id if model is not None else None),
            "version": 0, "events": [], "outbox": [], "log_step": 40, "history": [], "request_number": 1,
        }
        record.update({
            "status": "DRAFTED",
            "client": client_name,
            "drafted_by": drafted_by,
            "drafted_at": _now().isoformat(),
            "extension_hours": extension_hours,
            "reason": (reason or "")[:500],
            "cause": cause,
            "original_due_at": original.isoformat(),
            "proposed_due_at": proposed.isoformat(),
            "partial_penalty_inr": int(partial),
            "draft_message": message,
            "sourcing_status_at_draft": session.status if session is not None else None,
            "approved_by": None, "approved_at": None, "answer": None,
        })
        label = "follow-up " if follow_up else ""
        _log(record, f"Drafted {label}{extension_hours}h extension for {order_id} ({drafted_by})",
             f"📝 Drafted a {label}{extension_hours}h deadline-extension request to {client_name} for #{order_id} "
             f"(new deadline {_fmt(proposed)}, offering ₹{int(partial):,}). Awaiting human approval; nothing sent.",
             "draft_extension()")
        _save_or_409(record)
        return _public(record, run_id)


def on_sourcing_failed(run_id: str, reason: str = "") -> Optional[Dict[str, Any]]:
    """Called by the Sourcing Agent when a session ends without full cover.

    Drafts an extension request of the run's upstream delay (DRAFTED, drafted_by
    "sourcing_failure"). Returns None when a request is already open (DRAFTED, APPROVED, SENT,
    ANSWERING) or the client REFUSED (logged, nothing drafted). After an ACCEPTED extension the
    order is still not covered, so a follow-up request is drafted from the extended deadline.
    """
    with _lock:
        root_id, root = _root(run_id)
        existing = load(root_id)
        follow_up = False
        if existing is not None:
            answered = existing["status"] in ("ACCEPTED", "REFUSED") and existing.get("replan_run_id")
            if not answered:
                return None   # a request is still open: never a duplicate
            if existing["status"] == "REFUSED":
                _log(existing, "Not covered after the client's refusal",
                     f"⚠ #{existing['order_id']} is still not covered after {existing['client']} refused the "
                     f"extension; no further request drafted. Re-plan manually.", "client.on_sourcing_failed()")
                try:
                    save(existing)
                except ConcurrentUpdateError:
                    pass   # the note is best effort; the state is unchanged
                return None
            follow_up = True
        delay = root.get("delay_hours")
        if not isinstance(delay, int) or isinstance(delay, bool) or delay <= 0:
            raise ClientAgentError("the run has no upstream delay to base an extension request on", 409)
        note = (f"Not covered after the client's accepted extension. {reason}" if follow_up
                else f"Sourcing ended without full cover. {reason}").strip()
        return _draft(root_id, delay, note, drafted_by="sourcing_failure", follow_up=follow_up)


# ─── Approve & send (human sign-off) ─────────────────────────────────────────

def approve_extension(run_id: str, approved_by: str) -> Dict[str, Any]:
    approver = (approved_by or "").strip()
    if not approver:
        raise ClientAgentError("approved_by is required: a named person must approve the message.", 422)
    with _lock:
        root_id, _ = _root(run_id)
        record = load(root_id)
        if record is None:
            raise ClientAgentError("No extension request drafted for this run.", 404)
        if record["status"] != "DRAFTED":
            raise ClientAgentError(f"The extension request is already {record['status']}.", 409)

        mode = settings.SOURCING_MODE
        number = ""
        if mode == "telegram":
            order = _order(record["order_id"])
            contact_channel, _, contact_address = str(order.get("client_contact") or "").partition(":")
            if contact_channel.strip().lower() == mode and contact_address.strip():
                number = contact_address.strip()
            if not number:
                raise ClientAgentError(
                    f"no client contact: order {record['order_id']} has no {mode} contact "
                    f"(python -m app.admin set-client-contact).", 409)

        # Claim before sending, so two approvals can never send twice.
        record.update({"status": "APPROVED", "approved_by": approver[:120], "approved_at": _now().isoformat()})
        _save_or_409(record)

        try:
            if mode == "telegram":
                sent = bool(sourcing.outbound_channel("telegram").send_text(number, record["draft_message"]))
            else:
                sent = True
        except Exception as exc:  # noqa: BLE001 - any send error must release the claim
            logger.warning("Client %s send raised: %s", mode, type(exc).__name__)
            sent = False
        if not sent:
            label = "Telegram"
            record.update({"status": "DRAFTED", "approved_by": None, "approved_at": None})
            _log(record, f"{label} send failed", f"⚠ {label} send to the client failed; the request stays a draft.",
                 "send_client_message()")
            _save_or_409(record)
            raise ClientAgentError(f"{label} send to the client failed; the request is still a draft.", 502)

        record["status"] = "SENT"
        record.setdefault("outbox", []).append({
            "channel": mode, "to": number or "simulated", "text": record["draft_message"],
            "approved_by": record["approved_by"], "sent_at": _now().isoformat(),
        })
        _log(record, f"Sent to {record['client']} ({mode}), approved by {record['approved_by']}",
             f"📤 Extension request sent to {record['client']} via {mode} (approved by {record['approved_by']}).",
             "send_client_message()")
        _save_or_409(record)
        return _public(record, run_id)


# ─── Answer → extend, re-plan, restart sourcing ──────────────────────────────
#
# Lock order: sourcing._lock → client._lock is allowed (Sourcing's _finish calls
# on_sourcing_failed while holding its lock); client._lock → sourcing._lock is FORBIDDEN.
# record_client_answer therefore takes client._lock only around load/save of the record and
# calls restart_with_plan with no Client Agent lock held; compare-and-set on `version`
# guarantees correctness (one claim wins), the lock only serialises in-process access.
#
# The answer is resumable: it is first claimed as ANSWERING (answer, target due_at and
# re-plan deadline stored), then the idempotent steps run (due_at set absolutely, `<root>-C`
# upserted, sourcing restarted once — marked by `client_answer_ref` in the session params),
# then the record becomes ACCEPTED/REFUSED with replan_run_id. A failed step leaves
# ANSWERING; calling again with the SAME answer resumes, a different answer is 409.


def _refusal_target(playbooks, expedite_id: Optional[str]):
    """After a refusal: PLAN_A if feasible, else the cheapest feasible plan that uses the
    EXPEDITE vendor, else ClientAgentError 409."""
    if expedite_id is None:
        raise ClientAgentError("The client refused and this factory has no EXPEDITE vendor to fall back on.", 409)
    plan_a = next((p for p in playbooks if p.id == "PLAN_A"), None)
    if plan_a is not None and plan_a.feasible:
        return plan_a
    with_expedite = [p for p in playbooks if p.feasible
                     and any(a.supplier_id == expedite_id for a in p.vendor_allocations)]
    if not with_expedite:
        raise ClientAgentError(
            f"The client refused, and no feasible plan uses the expedite vendor {expedite_id} "
            f"before the current deadline; re-plan manually.", 409)
    return min(with_expedite, key=lambda p: p.expected_cost_inr)


def _answer_ref(root_id: str, accepted: bool, number: int = 1) -> str:
    prefix = root_id if number <= 1 else f"{root_id}#{number}"
    return f"{prefix}:{'ACCEPTED' if accepted else 'REFUSED'}"


def _replan(root_id: str, root: Dict[str, Any], accepted: bool, hours: float, used: bool = False):
    """Pure: re-plan on the run's stored (risk-adjusted) model with the answered deadline.
    Returns (result, target playbook, vendor ids to allow again)."""
    model = root["factory_model"]
    br = root.get("blast_radius") or {}
    session = sourcing_store.load(root_id)
    overrides = {k: dict(v) for k, v in (session.overrides if session else {}).items()}
    confirmed = set(session.confirmed) if session else set()
    expedite_id = model.expedite_vendor_id
    widen: tuple = ()
    if not accepted and expedite_id is not None:
        widen = (expedite_id,)   # refusal: the expedite vendor is allowed (asked) again
        if expedite_id not in confirmed:
            overrides.pop(expedite_id, None)
    try:
        result = generate_playbooks(
            model=model,
            shortfall_units=root["shortfall_units"],
            delay_hours=root["delay_hours"],
            line_speeds=root["line_speeds"],
            order_id=root["order_id"],
            sla_penalty_inr=int(br["sla_penalty_inr"]),
            partial_penalty_inr=int(br["partial_delay_penalty_inr"]),
            deadline_hours=hours,
            client=br["client"],
            vendor_overrides=overrides,
            confirmed_vendor_ids=confirmed,
            renegotiation_acceptance=1.0 if accepted else 0.0,
            renegotiation_used=used,
        )
    except SolverInputError as exc:
        raise ClientAgentError(f"Cannot re-plan: {exc}", 409)
    except KeyError as exc:
        raise ClientAgentError(f"Run {root_id} lacks {exc} needed to re-plan; run the analysis again.", 409)
    winner = next(p for p in result.playbooks if p.recommended)
    target = winner if accepted else _refusal_target(result.playbooks, expedite_id)
    return result, target, widen


def record_client_answer(run_id: str, accepted: bool, text: str = "",
                         new_deadline_hours: Optional[int] = None,
                         entered_by: str = "operator") -> Dict[str, Any]:
    if not isinstance(accepted, bool):
        raise ClientAgentError("accepted must be true or false.", 422)
    root_id, root = _root(run_id)

    # Phase 1 (record lock only): check the state; a resumable ANSWERING keeps its stored values.
    with _lock:
        record = load(root_id)
        if record is None:
            raise ClientAgentError("No extension request has been sent for this run.", 409)
        status = record["status"]
        stored = record.get("answer") or {}
        resumable = status == "ANSWERING" or (status in ("ACCEPTED", "REFUSED") and not record.get("replan_run_id"))
        if status in ("ANSWERING", "ACCEPTED", "REFUSED"):
            same = bool(stored.get("accepted")) == accepted
            if not same:
                raise ClientAgentError(
                    f"The client's answer is already recorded ({'ACCEPTED' if stored.get('accepted') else 'REFUSED'}); "
                    "a conflicting answer cannot replace it.", 409)
            if not resumable:
                raise ClientAgentError(f"The client's answer is already recorded ({status}); duplicate answer.", 409)
        elif status != "SENT":
            raise ClientAgentError(
                f"The request has not been sent (status {status}); approve it before recording an answer.", 409)

    now = _now()
    if not resumable:
        order = _order(record["order_id"])
        if accepted:
            if new_deadline_hours is not None:
                if isinstance(new_deadline_hours, bool) or not isinstance(new_deadline_hours, int) \
                        or new_deadline_hours <= 0:
                    raise ClientAgentError("new_deadline_hours must be a positive whole number of hours.", 422)
                new_due = now + timedelta(hours=new_deadline_hours)
                if new_due <= parse_timestamp(order["due_at"]):
                    raise ClientAgentError("new_deadline_hours is not later than the order's current deadline.", 422)
            else:
                new_due = parse_timestamp(record["proposed_due_at"])
            hours = (new_due - now).total_seconds() / 3600.0
        else:
            if new_deadline_hours is not None:
                raise ClientAgentError("new_deadline_hours only applies to an accepted extension.", 422)
            new_due = None
            hours = deadline_hours(order, now)
        hours = round(hours, 2)
    else:
        new_due = parse_timestamp(stored["target_due_at"]) if stored.get("target_due_at") else None
        hours = float(stored["deadline_hours"])

    # Pure re-plan (no lock held): solver input problems are reported before anything is claimed.
    # Once an extension is granted (now or earlier) the plan "ask for an extension" is gone.
    number = _request_number(record)
    used = accepted or _renegotiation_used(record)
    result, target, widen = _replan(root_id, root, accepted, hours, used)

    if not resumable:
        # Phase 2: claim the answer (compare-and-set). From here a different answer is 409.
        with _lock:
            record["status"] = "ANSWERING"
            record["answer"] = {
                "accepted": accepted, "text": (text or "")[:1000], "entered_by": entered_by[:120],
                "new_deadline_hours": new_deadline_hours, "recorded_at": now.isoformat(),
                "target_due_at": new_due.isoformat() if new_due else None, "deadline_hours": hours,
            }
            _save_or_409(record)

    # Phase 3: idempotent side effects, no Client Agent lock held (sourcing takes its own lock).
    if new_due is not None:
        db.update_rows("orders", "order_id", record["order_id"], {
            "due_at": new_due.isoformat(), "hours_remaining": round((new_due - now).total_seconds() / 3600.0, 1),
            "updated_at": now.isoformat(),
        })
    br = root.get("blast_radius") or {}
    replan_id = f"{root_id}-C" if number <= 1 else f"{root_id}-C{number}"
    replan = dict(root)
    replan.update({
        "run_id": replan_id,
        "parent_run_id": root_id,
        "playbooks": [p.model_dump() for p in result.playbooks],
        "recommended_plan_id": result.recommended_plan_id,
        "solver_result": result.model_dump(),
        "blast_radius": {**br, "hours_remaining": hours},
        "client_answer": "ACCEPTED" if accepted else "REFUSED",
    })
    run_store.save_run(replan)

    ref = _answer_ref(root_id, accepted, number)
    session = sourcing_store.load(root_id)
    restarted = False
    if session is not None:
        restarted = True
        if session.params.get("client_answer_ref") != ref:   # not restarted for this answer yet
            why = (f"Client accepted the extension: deadline now {hours:g}h." if accepted else
                   "Client refused the extension: expedite allowed again.")
            sourcing.restart_with_plan(
                root_id, target.model_dump(), why,
                params_update={"deadline_hours": hours, "renegotiation_acceptance": 1.0 if accepted else 0.0,
                               "renegotiation_used": used, "client_answer_ref": ref},
                allow_vendor_ids=widen,
            )

    # Phase 4: finalise (reload: the version moved if anything else touched the record).
    final = "ACCEPTED" if accepted else "REFUSED"
    with _lock:
        record = load(root_id)
        if record["status"] == final and record.get("replan_run_id"):
            return _public(record, run_id)   # a concurrent resume finished first
        record.update({
            "status": final,
            "new_due_at": new_due.isoformat() if new_due else None,
            "replan_deadline_hours": hours,
            "replan_run_id": replan_id,
            "replan_recommended_plan_id": result.recommended_plan_id,
            "sourcing_target_plan_id": target.id,
            "sourcing_restarted": restarted,
        })
        _log(record,
             f"{final}: re-planned at {hours:g}h → {result.recommended_plan_id}; sourcing target {target.id}",
             (f"✅ {record['client']} accepted: #{record['order_id']} now due {_fmt(new_due)}. " if accepted else
              f"❌ {record['client']} refused the extension. ")
             + f"Re-planned ({result.recommended_plan_id} recommended); "
             + (f"sourcing restarted on {target.id}." if restarted else "no sourcing session to restart."),
             "record_client_answer() + generate_playbooks()")
        _save_or_409(record)
        return _public(record, run_id)


def view(run_id: str) -> Dict[str, Any]:
    with _lock:
        root_id, _ = _root(run_id)
        record = load(root_id)
        if record is None:
            raise ClientAgentError("No extension request for this run.", 404)
        return _public(record, run_id)
