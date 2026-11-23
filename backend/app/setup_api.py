"""
CascadeZero — factory setup and data APIs (Round S).

A signed-in user creates a factory (and becomes its owner), then describes it: production lines,
suppliers (with an explicit risk profile), orders; stock and shipments are read-only here. Every
endpoint authorises against the factory of the resource it touches (Round B): reads need any role,
edits owner or approver, team management the owner; a foreign factory is a 404.

  POST  /api/v1/factories                         create a factory (caller becomes owner)
  GET|PATCH /api/v1/factory/settings              plant constants
  GET|POST  /api/v1/lines     PATCH|DELETE /api/v1/lines/{line_id}
  GET|POST  /api/v1/suppliers PATCH|DELETE /api/v1/suppliers/{supplier_id}
  GET|POST  /api/v1/orders    PATCH /api/v1/orders/{order_id}
  GET  /api/v1/stock          GET /api/v1/shipments
  POST /api/v1/suppliers/{id}/telegram-invite     POST /api/v1/orders/{id}/telegram-invite
  POST /api/v1/ingest/suppliers-csv               POST /api/v1/ingest/lines-csv
  GET|POST /api/v1/team       PATCH|DELETE /api/v1/team/{user_id}              [owner]

No silent defaults: a supplier's risk parameters come from the explicit risk profile the user
picked (RISK_PROFILES), shown in the response and editable. After a write the factory model must
still load (`load_factory_model`), otherwise the write is undone and answered with a 422.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app import admin, db, importers, inbound
from app.auth import ANY_ROLE, OWNER_ONLY, ROLES, WRITE_ROLES, Actor, machine_actor, user_actor
from app.config import settings
from app.factory_model import FactoryDataError, _Problems, _load_line, _load_vendor, load_factory_model
from app.reliability import beta_reliability, on_time as _on_time, parse_timestamp
from app.schemas import ErpCsvSyncRequest

logger = logging.getLogger("cascadezero.setup")
router = APIRouter(prefix="/api/v1")

# ─── Risk profiles ───────────────────────────────────────────────────────────

# lead sigma (h), delay-shock probability (%), shock range (h), unreliable delay range (h).
RISK_PROFILES: Dict[str, Dict[str, Any]] = {
    "low": {"lead_sigma_hours": 0.3, "shock_pct": 2.0, "shock_range_hours": (1.0, 2.0),
            "unreliable_delay_range_hours": (1.0, 2.0)},
    "medium": {"lead_sigma_hours": 1.0, "shock_pct": 6.0, "shock_range_hours": (1.0, 3.0),
               "unreliable_delay_range_hours": (2.0, 4.0)},
    "high": {"lead_sigma_hours": 2.0, "shock_pct": 15.0, "shock_range_hours": (2.0, 6.0),
             "unreliable_delay_range_hours": (3.0, 8.0)},
}
_TIER = {"PRIMARY": "TIER-1", "BACKUP": "TIER-2", "EXPEDITE": "EMERGENCY"}
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
_CHAT_RE = re.compile(r"^-?\d{1,20}$")
_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")

# ─── Validated request bodies ────────────────────────────────────────────────

NonNeg = Annotated[float, Field(ge=0, le=1e9, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, le=1e9, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0, le=1_000_000_000)]
Text = Annotated[str, Field(min_length=1, max_length=200)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def _no_booleans(cls, v):
        if isinstance(v, bool):
            raise ValueError("must be a number or text, not true/false")
        return v


class FactoryCreate(_Body):
    id: Optional[str] = Field(default=None, max_length=63)
    name: Text
    stock_item_code: str = Field(min_length=1, max_length=40)
    stock_item_name: Text
    qa_dispatch_hours: Annotated[float, Field(ge=0, le=720, allow_inf_nan=False)]
    safety_stock_units: Count
    production_hours_in_window: Annotated[float, Field(gt=0, le=8760, allow_inf_nan=False)]

    @field_validator("stock_item_code")
    @classmethod
    def _code(cls, v):
        if not _CODE_RE.match(v):
            raise ValueError("use letters, digits, '.', '_' or '-' (max 40 characters)")
        return v


class FactoryPatch(_Body):
    name: Optional[Text] = None
    stock_item_name: Optional[Text] = None
    qa_dispatch_hours: Optional[Annotated[float, Field(ge=0, le=720, allow_inf_nan=False)]] = None
    safety_stock_units: Optional[Count] = None
    production_hours_in_window: Optional[Annotated[float, Field(gt=0, le=8760, allow_inf_nan=False)]] = None


class LineIn(_Body):
    name: Text
    rated_units_per_hour: NonNeg
    ot_units_per_hour: Count = 0
    ot_cost_per_hour: Count = 0
    max_ot_hours: Annotated[int, Field(ge=0, le=168)] = 0


class LinePatch(_Body):
    name: Optional[Text] = None
    rated_units_per_hour: Optional[NonNeg] = None
    ot_units_per_hour: Optional[Count] = None
    ot_cost_per_hour: Optional[Count] = None
    max_ot_hours: Optional[Annotated[int, Field(ge=0, le=168)]] = None


Role = Literal["PRIMARY", "BACKUP", "EXPEDITE"]
Profile = Literal["low", "medium", "high"]
LeadHours = Annotated[int, Field(gt=0, le=24 * 365)]
MinLeadHours = Annotated[float, Field(gt=0, le=24 * 365, allow_inf_nan=False)]


def _check_chat(v):
    if v is not None and not _CHAT_RE.match(v):
        raise ValueError("a Telegram chat id is a number (or use a telegram invite link instead)")
    return v


class SupplierIn(_Body):
    name: Text
    sourcing_role: Role
    unit_cost: Count = 0
    flat_cost: Count = 0
    max_units: Count
    lead_hours: LeadHours
    min_lead_hours: Optional[MinLeadHours] = None
    route: Text
    risk_profile: Profile
    past_orders: Optional[Count] = None
    on_time: Optional[Count] = None
    telegram_chat_id: Optional[str] = Field(default=None, max_length=21)

    _chat = field_validator("telegram_chat_id")(_check_chat)

    @model_validator(mode="after")
    def _cross(self):
        _check_history(self.past_orders, self.on_time)
        if self.min_lead_hours is not None and self.min_lead_hours > self.lead_hours:
            raise ValueError("min_lead_hours cannot exceed lead_hours")
        return self


class SupplierPatch(_Body):
    name: Optional[Text] = None
    sourcing_role: Optional[Role] = None
    unit_cost: Optional[Count] = None
    flat_cost: Optional[Count] = None
    max_units: Optional[Count] = None
    lead_hours: Optional[LeadHours] = None
    min_lead_hours: Optional[MinLeadHours] = None
    route: Optional[Text] = None
    risk_profile: Optional[Profile] = None
    past_orders: Optional[Count] = None
    on_time: Optional[Count] = None
    telegram_chat_id: Optional[str] = Field(default=None, max_length=21)

    _chat = field_validator("telegram_chat_id")(_check_chat)


def _check_history(past, ontime) -> None:
    if (past is None) != (ontime is None):
        raise ValueError("past_orders and on_time go together (or leave both out: no history yet)")
    if past is not None and ontime > past:
        raise ValueError("on_time cannot exceed past_orders")


class OrderIn(_Body):
    order_id: Optional[str] = Field(default=None, max_length=40)
    client: Text
    required_qty: Annotated[int, Field(gt=0, le=1_000_000_000)]
    due_at: Optional[str] = Field(default=None, max_length=40)
    hours_remaining: Optional[Annotated[float, Field(gt=0, le=24 * 365, allow_inf_nan=False)]] = None
    sla_penalty_inr: Count
    partial_delay_penalty_inr: Count
    priority: Annotated[int, Field(ge=0, le=100000)] = 100

    @model_validator(mode="after")
    def _deadline(self):
        if (self.due_at is None) == (self.hours_remaining is None):
            raise ValueError("give exactly one of due_at (ISO date-time) or hours_remaining")
        if self.order_id is not None and not _ORDER_ID_RE.match(self.order_id):
            raise ValueError("order_id: use letters, digits, '.', '_' or '-' (max 40 characters)")
        return self


class OrderPatch(_Body):
    client: Optional[Text] = None
    required_qty: Optional[Annotated[int, Field(gt=0, le=1_000_000_000)]] = None
    due_at: Optional[str] = Field(default=None, max_length=40)
    hours_remaining: Optional[Annotated[float, Field(gt=0, le=24 * 365, allow_inf_nan=False)]] = None
    sla_penalty_inr: Optional[Count] = None
    partial_delay_penalty_inr: Optional[Count] = None
    priority: Optional[Annotated[int, Field(ge=0, le=100000)]] = None

    @model_validator(mode="after")
    def _one_deadline(self):
        if self.due_at is not None and self.hours_remaining is not None:
            raise ValueError("give only one of due_at or hours_remaining")
        return self


class MemberIn(_Body):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["owner", "approver", "viewer"]

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("not an email address")
        return v.lower()


class MemberPatch(_Body):
    role: Literal["owner", "approver", "viewer"]


# ─── Small helpers ───────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _422(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def _not_found(noun: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Unknown {noun}")


def _fields(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'body'}: {e['msg']}" for e in exc.errors())


def _owned(row: Optional[Dict[str, Any]], actor: Actor, roles, noun: str) -> Dict[str, Any]:
    """A resource row after authorising `roles` in ITS factory; a foreign or missing one is a 404."""
    factory_id = (row or {}).get("factory_id")
    if row is None or not factory_id or factory_id not in actor.memberships:
        raise _not_found(noun)
    actor.require_role(factory_id, *roles)
    return row


def _model_ok(factory_id: str) -> bool:
    try:
        load_factory_model(factory_id)
        return True
    except FactoryDataError:
        return False


def _guard(factory_id: str, was_ok: bool, undo) -> None:
    """After a write: the factory model must still load. If it no longer does (and it did before),
    `undo()` the write and answer 422 with the problem."""
    try:
        load_factory_model(factory_id)
    except FactoryDataError as exc:
        if was_ok:
            undo()
            raise _422(f"Rejected: the factory data would no longer load: {exc}") from None


def _delete_guarded(fid: str, noun: str, delete, restore) -> None:
    """Run `delete()`; if the factory model then no longer loads (and did before), `restore()`
    and answer 409 with the reason, leaving everything as it was."""
    was_ok = _model_ok(fid)
    delete()
    try:
        load_factory_model(fid)
    except FactoryDataError as exc:
        if was_ok:
            restore()
            raise HTTPException(status_code=409, detail=f"Cannot delete this {noun}: the factory would no "
                                f"longer work without it ({exc})") from None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:63].strip("-")


def _factory_of(actor: Actor, factory_id: Optional[str], *roles) -> str:
    return actor.authorize(factory_id, *roles)


def _factory_row(factory_id: str) -> Dict[str, Any]:
    row = db.get_factory_row(factory_id)
    if row is None:
        raise _not_found("factory")
    return row


def _settings_view(row: Dict[str, Any], role: Optional[str] = None) -> Dict[str, Any]:
    view = {k: row.get(k) for k in ("id", "name", "stock_item_code", "stock_item_name", "qa_dispatch_hours",
                                    "safety_stock_units", "production_hours_in_window")}
    if role is not None:
        view["role"] = role
    return view


# ─── Factory ─────────────────────────────────────────────────────────────────

MAX_FACTORIES_PER_USER = 5


@router.get("/my/factories")
def my_factories(actor: Actor = Depends(user_actor)):
    return {"factories": actor.factory_list()}


@router.post("/factories", status_code=201)
def create_factory(body: FactoryCreate, actor: Actor = Depends(user_actor)):
    """Any signed-in user may create a factory; they become its owner (no membership needed first)."""
    if not actor.user_id or not actor.email:
        raise HTTPException(status_code=403, detail="Creating a factory needs a signed-in user with an email")
    owned = [f for f, r in db.get_memberships(actor.user_id).items() if r == "owner"]
    if len(owned) >= MAX_FACTORIES_PER_USER:
        raise HTTPException(status_code=409, detail=f"You can own at most {MAX_FACTORIES_PER_USER} factories")
    factory_id = body.id if body.id is not None else _slug(body.name)
    if not _SLUG_RE.match(factory_id or ""):
        raise _422("id: use lowercase letters, digits and '-' (give an id, or a name with letters or digits)")
    if db.get_factory_row(factory_id) is not None:
        raise HTTPException(status_code=409, detail=f"Factory id {factory_id!r} is taken; choose another")
    row = {"id": factory_id, "name": body.name, "stock_item_name": body.stock_item_name,
           "stock_item_code": body.stock_item_code, "qa_dispatch_hours": body.qa_dispatch_hours,
           "safety_stock_units": body.safety_stock_units,
           "production_hours_in_window": body.production_hours_in_window}
    try:
        db.insert_row("factories", row)
    except db.DatabaseError:
        if db.get_factory_row(factory_id) is not None:   # a concurrent create took the id
            raise HTTPException(status_code=409, detail=f"Factory id {factory_id!r} is taken; choose another") from None
        raise
    db.upsert_row("items", {"factory_id": factory_id, "item_code": body.stock_item_code,
                            "name": body.stock_item_name, "unit": "pcs"}, key_columns=("factory_id", "item_code"))
    db.upsert_row("stock_levels", {"factory_id": factory_id, "item_code": body.stock_item_code, "on_hand_qty": 0,
                                   "as_of": _now().isoformat()}, key_columns=("factory_id", "item_code"))
    db.upsert_row("factory_members", {"user_id": actor.user_id, "factory_id": factory_id, "role": "owner",
                                      "email": actor.email}, key_columns=("user_id", "factory_id"))
    return _settings_view(row, "owner")


@router.get("/factory/settings")
def get_factory_settings(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *ANY_ROLE)
    return _settings_view(_factory_row(fid), actor.memberships[fid])


@router.patch("/factory/settings")
def patch_factory_settings(body: FactoryPatch, factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *WRITE_ROLES)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise _422("nothing to change")
    if any(v is None for v in updates.values()):
        raise _422("a value cannot be null")
    before = _factory_row(fid)
    was_ok = _model_ok(fid)
    db.update_rows("factories", "id", fid, updates)
    if "stock_item_name" in updates:
        db.update_rows_where("items", {"factory_id": fid, "item_code": before.get("stock_item_code")},
                             {"name": updates["stock_item_name"]})
    def undo():
        db.update_rows("factories", "id", fid, {k: before.get(k) for k in updates})
        if "stock_item_name" in updates:
            db.update_rows_where("items", {"factory_id": fid, "item_code": before.get("stock_item_code")},
                                 {"name": before.get("stock_item_name")})
    _guard(fid, was_ok, undo)
    return _settings_view(_factory_row(fid), actor.memberships[fid])


# ─── Production lines ────────────────────────────────────────────────────────

def _line_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"line_id": row["line_id"], "name": row.get("name"),
            "rated_units_per_hour": row.get("rated_units_per_hour"),
            "ot_units_per_hour": row.get("extra_units_per_ot_hour"),
            "ot_cost_per_hour": row.get("overtime_cost_per_hour_inr"),
            "max_ot_hours": row.get("max_ot_hours"),
            "status": row.get("status"), "speed_pct": row.get("speed_pct")}


def _line_columns(data: Dict[str, Any]) -> Dict[str, Any]:
    names = {"name": "name", "rated_units_per_hour": "rated_units_per_hour",
             "ot_units_per_hour": "extra_units_per_ot_hour", "ot_cost_per_hour": "overtime_cost_per_hour_inr",
             "max_ot_hours": "max_ot_hours"}
    return {names[k]: v for k, v in data.items() if k in names}


def _validate_line(row: Dict[str, Any]) -> None:
    p = _Problems()
    _load_line(row, p)
    if p.items:
        raise _422("; ".join(p.items))


def _create_line(fid: str, data: Dict[str, Any]) -> Dict[str, Any]:
    window = _factory_row(fid).get("production_hours_in_window") or 0
    row = {"line_id": f"LINE-{secrets.token_hex(4).upper()}", "factory_id": fid, "status": "NORMAL",
           "speed_pct": 100, "temp_celsius": 25.0, "updated_at": _now().isoformat(),
           **_line_columns(data)}
    row["daily_capacity_units"] = int(round(row["rated_units_per_hour"] * window))
    _validate_line(row)
    was_ok = _model_ok(fid)
    created = db.upsert_owned("production_lines", row, ("line_id",))
    _guard(fid, was_ok, lambda: db.delete_rows_where("production_lines", {"line_id": row["line_id"], "factory_id": fid}))
    return created


def _update_line(fid: str, current: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    updates = {**_line_columns(data), "updated_at": _now().isoformat()}
    _validate_line({**current, **updates})
    was_ok = _model_ok(fid)
    db.update_rows_where("production_lines", {"line_id": current["line_id"], "factory_id": fid}, updates)
    _guard(fid, was_ok, lambda: db.update_rows_where(
        "production_lines", {"line_id": current["line_id"], "factory_id": fid}, {k: current.get(k) for k in updates}))
    return db.get_production_line(current["line_id"]) or current


@router.get("/lines")
def list_lines(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *ANY_ROLE)
    rows = sorted(db.fetch_where("production_lines", {"factory_id": fid}), key=lambda r: r["line_id"])
    return {"factory_id": fid, "lines": [_line_view(r) for r in rows]}


@router.post("/lines", status_code=201)
def create_line(body: LineIn, factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *WRITE_ROLES)
    return _line_view(_create_line(fid, body.model_dump()))


@router.patch("/lines/{line_id}")
def patch_line(line_id: str, body: LinePatch, actor: Actor = Depends(user_actor)):
    row = _owned(db.get_production_line(line_id), actor, WRITE_ROLES, "line")
    data = body.model_dump(exclude_unset=True)
    if not data or any(v is None for v in data.values()):
        raise _422("give at least one value to change (none may be null)")
    return _line_view(_update_line(row["factory_id"], row, data))


def _runs_using_line(fid: str, line_id: str) -> List[str]:
    """Open runs (no execution receipt yet) of the factory whose model contains the line."""
    active = []
    for run in db.fetch_where("analysis_runs", {"factory_id": fid}):
        payload = run.get("payload") or {}
        lines = (payload.get("factory_model") or {}).get("lines") or []
        if any(l.get("line_id") == line_id for l in lines) and db.get_receipt(run["run_id"]) is None:
            active.append(run["run_id"])
    return active


@router.delete("/lines/{line_id}")
def delete_line(line_id: str, actor: Actor = Depends(user_actor)):
    row = _owned(db.get_production_line(line_id), actor, WRITE_ROLES, "line")
    runs = _runs_using_line(row["factory_id"], line_id)
    if runs:
        raise HTTPException(status_code=409, detail=f"Line {line_id} is used by an open run "
                            f"({', '.join(runs[:3])}); approve or abandon it first")
    fid = row["factory_id"]
    if len(db.fetch_where("production_lines", {"factory_id": fid})) <= 1:
        raise HTTPException(status_code=409, detail="Cannot delete the last production line: "
                            "the factory needs at least one")
    _delete_guarded(fid, "line",
                    lambda: db.delete_rows_where("production_lines", {"line_id": line_id, "factory_id": fid}),
                    lambda: db.upsert_row("production_lines", row, key_columns=("line_id",)))
    return {"deleted": line_id}


# ─── Suppliers ───────────────────────────────────────────────────────────────

def _history(supplier_id: str) -> Optional[Dict[str, Any]]:
    return db.get_vendor_history(supplier_id)


def _reliability(supplier_id: str) -> Dict[str, Any]:
    """The learned reliability: stated history plus DELIVERED outcomes, or 'no history yet'."""
    hist = _history(supplier_id)
    past = int((hist or {}).get("past_orders_count") or 0)
    ontime = int((hist or {}).get("on_time_deliveries") or 0)
    done = [o for o in db.get_delivery_outcomes(status="DELIVERED", supplier_id=supplier_id)
            if o.get("delivered_at") and o.get("promised_at")]
    n_on_time = sum(1 for o in done if _on_time(o["promised_at"], o["delivered_at"]))
    ontime = min(ontime, past)
    pct = beta_reliability(ontime, past, n_on_time, len(done))
    has_history = (past + len(done)) > 0
    return {"reliability_pct": pct, "past_orders": past, "on_time": ontime, "recorded_deliveries": len(done),
            "has_history": has_history, "reliability_note": None if has_history else "no history yet"}


def _supplier_view(row: Dict[str, Any]) -> Dict[str, Any]:
    chat = row.get("telegram_chat_id")
    return {
        "id": row["id"], "name": row.get("name"), "sourcing_role": row.get("sourcing_role"),
        "unit_cost": row.get("extra_cost_per_unit_inr"), "flat_cost": row.get("flat_charter_cost_inr"),
        "max_units": row.get("max_available_qty"), "lead_hours": row.get("lead_time_hours"),
        "min_lead_hours": row.get("min_lead_hours"), "route": row.get("route"),
        "risk_profile": row.get("risk_profile"),
        "derived": {
            "lead_sigma_hours": row.get("lead_time_sigma_hours"),
            "shock_pct": (row.get("traffic_risk_pct") or 0) + (row.get("weather_risk_pct") or 0),
            "shock_range_hours": [row.get("delay_shock_min_hours"), row.get("delay_shock_max_hours")],
            "unreliable_delay_range_hours": [row.get("unreliable_delay_min_hours"),
                                             row.get("unreliable_delay_max_hours")],
        },
        "reliability": _reliability(row["id"]),
        "telegram_chat_id": chat or None, "telegram_connected": bool(chat),
    }


def _profile_columns(profile: str) -> Dict[str, Any]:
    p = RISK_PROFILES[profile]
    return {"risk_profile": profile, "lead_time_sigma_hours": p["lead_sigma_hours"],
            "traffic_risk_pct": p["shock_pct"], "weather_risk_pct": 0.0,
            "delay_shock_min_hours": p["shock_range_hours"][0], "delay_shock_max_hours": p["shock_range_hours"][1],
            "unreliable_delay_min_hours": p["unreliable_delay_range_hours"][0],
            "unreliable_delay_max_hours": p["unreliable_delay_range_hours"][1]}


def _validate_supplier(row: Dict[str, Any], history: Optional[Dict[str, Any]]) -> None:
    """The same checks the factory model applies, run BEFORE anything is written."""
    p = _Problems()
    if not row.get("route"):
        p.missing("suppliers", "route")
    if row.get("sourcing_role") != "PRIMARY":
        _load_vendor(row, history, p)
    if p.items:
        raise _422("; ".join(p.items))


def _history_row(supplier_id: str, fid: str, past: Optional[int], ontime: Optional[int]) -> Dict[str, Any]:
    return {"supplier_id": supplier_id, "factory_id": fid, "past_orders_count": past or 0,
            "on_time_deliveries": ontime or 0, "reliability_score_pct": 0.0,
            "quality_rejection_rate_pct": 0.0, "last_incident_note": ""}


def _supplier_columns(data: Dict[str, Any]) -> Dict[str, Any]:
    names = {"name": "name", "sourcing_role": "sourcing_role", "unit_cost": "extra_cost_per_unit_inr",
             "flat_cost": "flat_charter_cost_inr", "max_units": "max_available_qty",
             "lead_hours": "lead_time_hours", "min_lead_hours": "min_lead_hours", "route": "route",
             "telegram_chat_id": "telegram_chat_id"}
    return {names[k]: v for k, v in data.items() if k in names}


def _write_history(supplier_id: str, fid: str, past: Optional[int], ontime: Optional[int]) -> None:
    hist = _history(supplier_id)
    row = _history_row(supplier_id, fid, past, ontime)
    if hist is None:
        db.insert_row("vendor_history", row)
    else:
        db.update_rows_where("vendor_history", {"supplier_id": supplier_id},
                             {"past_orders_count": row["past_orders_count"],
                              "on_time_deliveries": row["on_time_deliveries"]})


def _create_supplier(fid: str, data: Dict[str, Any]) -> Dict[str, Any]:
    role = data["sourcing_role"]
    row = {
        "id": f"SUP-{secrets.token_hex(4).upper()}", "factory_id": fid, "tier": _TIER[role],
        "part_name": _factory_row(fid).get("stock_item_name") or "", "status": "ON_TIME" if role == "PRIMARY" else "STANDBY",
        "delay_hours": 0, "whatsapp_number": "", "inbound_qty": data["max_units"] if role == "PRIMARY" else 0,
        "updated_at": _now().isoformat(),
        **_supplier_columns(data), **_profile_columns(data["risk_profile"]),
    }
    # "min_lead_hours = the supplier's stated minimum, else = lead hours".
    row["min_lead_hours"] = float(data["min_lead_hours"] if data.get("min_lead_hours") is not None
                                  else data["lead_hours"])
    history = _history_row(row["id"], fid, data.get("past_orders"), data.get("on_time"))
    _validate_supplier(row, history)
    was_ok = _model_ok(fid)
    created = db.upsert_owned("suppliers", row, ("id",))
    _write_history(row["id"], fid, data.get("past_orders"), data.get("on_time"))

    def undo():
        db.delete_rows_where("vendor_history", {"supplier_id": row["id"]})
        db.delete_rows_where("suppliers", {"id": row["id"], "factory_id": fid})
    _guard(fid, was_ok, undo)
    return created


def _update_supplier(fid: str, current: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    updates = _supplier_columns(data)
    if "risk_profile" in data:
        updates.update(_profile_columns(data["risk_profile"]))
    lead = updates.get("lead_time_hours", current.get("lead_time_hours"))
    min_lead = current.get("min_lead_hours")
    if "min_lead_hours" in data:
        min_lead = data["min_lead_hours"]
    if "lead_time_hours" in updates and "min_lead_hours" not in data:
        old_lead = current.get("lead_time_hours")
        if min_lead is None or min_lead == old_lead or min_lead > lead:
            min_lead = lead   # a derived minimum follows the lead time; a stated one is kept
    updates["min_lead_hours"] = float(lead if min_lead is None else min_lead)
    if updates["min_lead_hours"] > lead:
        raise _422("min_lead_hours cannot exceed lead_hours")
    role = updates.get("sourcing_role", current.get("sourcing_role"))
    if "sourcing_role" in updates:
        updates["tier"] = _TIER[role]
    if "past_orders" in data or "on_time" in data:
        hist = _history(current["id"]) or {}
        past = data.get("past_orders", hist.get("past_orders_count"))
        ontime = data.get("on_time", hist.get("on_time_deliveries"))
        try:
            _check_history(past, ontime)
        except ValueError as exc:
            raise _422(str(exc)) from None
    merged = {**current, **updates}
    new_history = _history(current["id"])
    if "past_orders" in data or "on_time" in data:
        new_history = {**(new_history or {}), "past_orders_count": past, "on_time_deliveries": ontime}
    _validate_supplier(merged, new_history)
    updates["updated_at"] = _now().isoformat()
    was_ok = _model_ok(fid)
    old_history = _history(current["id"])
    db.update_rows_where("suppliers", {"id": current["id"], "factory_id": fid}, updates)
    if "past_orders" in data or "on_time" in data:
        _write_history(current["id"], fid, past, ontime)

    def undo():
        db.update_rows_where("suppliers", {"id": current["id"], "factory_id": fid},
                             {k: current.get(k) for k in updates})
        if old_history is None and ("past_orders" in data or "on_time" in data):
            db.delete_rows_where("vendor_history", {"supplier_id": current["id"]})
        if old_history is not None:
            db.update_rows_where("vendor_history", {"supplier_id": current["id"]},
                                 {"past_orders_count": old_history.get("past_orders_count"),
                                  "on_time_deliveries": old_history.get("on_time_deliveries")})
    _guard(fid, was_ok, undo)
    return db.get_supplier(current["id"]) or merged


@router.get("/suppliers")
def list_suppliers(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *ANY_ROLE)
    rows = sorted(db.fetch_where("suppliers", {"factory_id": fid}), key=lambda r: r["id"])
    return {"factory_id": fid, "risk_profiles": _profiles_view(), "suppliers": [_supplier_view(r) for r in rows]}


def _profiles_view() -> Dict[str, Any]:
    return {k: {"lead_sigma_hours": v["lead_sigma_hours"], "shock_pct": v["shock_pct"],
                "shock_range_hours": list(v["shock_range_hours"]),
                "unreliable_delay_range_hours": list(v["unreliable_delay_range_hours"])}
            for k, v in RISK_PROFILES.items()}


@router.post("/suppliers", status_code=201)
def create_supplier(body: SupplierIn, factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *WRITE_ROLES)
    return _supplier_view(_create_supplier(fid, body.model_dump()))


@router.patch("/suppliers/{supplier_id}")
def patch_supplier(supplier_id: str, body: SupplierPatch, actor: Actor = Depends(user_actor)):
    row = _owned(db.get_supplier(supplier_id), actor, WRITE_ROLES, "supplier")
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise _422("nothing to change")
    nullable = {"telegram_chat_id", "min_lead_hours"}
    if any(v is None and k not in nullable for k, v in data.items()):
        raise _422("a value cannot be null")
    return _supplier_view(_update_supplier(row["factory_id"], row, data))


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(supplier_id: str, actor: Actor = Depends(user_actor)):
    row = _owned(db.get_supplier(supplier_id), actor, WRITE_ROLES, "supplier")
    fid = row["factory_id"]
    if any(s.get("supplier_id") == supplier_id for s in db.get_inbound_shipments(fid)):
        raise HTTPException(status_code=409, detail="This supplier has open inbound shipments; close them first")
    mine = db.fetch_where("suppliers", {"factory_id": fid})
    if len(mine) <= 1 or (row.get("sourcing_role") == "PRIMARY"
                          and sum(1 for r in mine if r.get("sourcing_role") == "PRIMARY") <= 1):
        raise HTTPException(status_code=409, detail="Cannot delete the primary (or only) supplier: "
                            "the factory needs one to plan around")
    hist = _history(supplier_id)

    def delete():
        db.delete_rows_where("vendor_history", {"supplier_id": supplier_id})
        db.delete_rows_where("suppliers", {"id": supplier_id, "factory_id": fid})

    def restore():
        db.upsert_row("suppliers", row, key_columns=("id",))
        if hist is not None:
            db.upsert_row("vendor_history", hist, key_columns=("supplier_id",))
    _delete_guarded(fid, "supplier", delete, restore)
    return {"deleted": supplier_id}


# ─── Orders ──────────────────────────────────────────────────────────────────

def _order_view(row: Dict[str, Any]) -> Dict[str, Any]:
    contact = row.get("client_contact") or ""
    return {k: row.get(k) for k in ("order_id", "client", "required_qty", "due_at", "hours_remaining",
                                    "sla_penalty_inr", "partial_delay_penalty_inr", "priority", "status",
                                    "shortfall_units")} | {"telegram_connected": contact.startswith("telegram:")}


def _deadline(due_at: Optional[str], hours: Optional[float]) -> datetime:
    if due_at is not None:
        try:
            due = parse_timestamp(due_at)
        except (ValueError, TypeError):
            raise _422("due_at: not an ISO date-time (e.g. 2026-12-01T17:00:00+05:30)") from None
    else:
        due = _now() + timedelta(hours=hours or 0)
    if due <= _now():
        raise _422("due_at must be in the future")
    return due.astimezone(timezone.utc)


def _deadline_columns(due: datetime) -> Dict[str, Any]:
    return {"due_at": due.isoformat(), "hours_remaining": int(round((due - _now()).total_seconds() / 3600)),
            "deadline_label": f"Due {due.strftime('%Y-%m-%d %H:%M')} UTC"}


@router.get("/orders")
def list_orders(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *ANY_ROLE)
    now = _now()
    rows = db.fetch_where("orders", {"factory_id": fid})
    rows = [db._live_hours(r, now) for r in rows]
    rows.sort(key=lambda r: (r.get("priority") or 0, r["order_id"]))
    return {"factory_id": fid, "orders": [_order_view(r) for r in rows]}


@router.post("/orders", status_code=201)
def create_order(body: OrderIn, factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *WRITE_ROLES)
    due = _deadline(body.due_at, body.hours_remaining)
    order_id = body.order_id or f"ORD-{secrets.token_hex(3).upper()}"
    existing = db.get_order(order_id)
    if existing is not None:
        if existing.get("factory_id") != fid:      # no existence leak across factories
            raise _422("order id not available")
        raise HTTPException(status_code=409, detail=f"Order id {order_id!r} is already used")
    code = _factory_row(fid).get("stock_item_code")
    row = {"order_id": order_id, "factory_id": fid, "client": body.client, "required_qty": body.required_qty,
           "sla_penalty_inr": body.sla_penalty_inr, "partial_delay_penalty_inr": body.partial_delay_penalty_inr,
           "priority": body.priority, "status": "ON_TRACK", "shortfall_units": 0,
           "updated_at": _now().isoformat(), **_deadline_columns(due)}
    try:
        db.upsert_owned("orders", row, ("order_id",))
    except db.OwnershipConflict:
        raise _422("order id not available") from None
    db.upsert_row("order_lines", {"order_id": order_id, "item_code": code, "qty": body.required_qty,
                                  "factory_id": fid}, key_columns=("order_id", "item_code"))
    return _order_view(db.get_order(order_id) or row)


@router.patch("/orders/{order_id}")
def patch_order(order_id: str, body: OrderPatch, actor: Actor = Depends(user_actor)):
    row = _owned(db.get_order(order_id), actor, WRITE_ROLES, "order")
    data = body.model_dump(exclude_unset=True)
    if not data or any(v is None for v in data.values()):
        raise _422("give at least one value to change (none may be null)")
    updates = {k: v for k, v in data.items()
               if k in ("client", "required_qty", "sla_penalty_inr", "partial_delay_penalty_inr", "priority")}
    if "due_at" in data or "hours_remaining" in data:
        updates.update(_deadline_columns(_deadline(data.get("due_at"), data.get("hours_remaining"))))
    updates["updated_at"] = _now().isoformat()
    fid = row["factory_id"]
    db.update_rows_where("orders", {"order_id": order_id, "factory_id": fid}, updates)
    if "required_qty" in data:
        code = _factory_row(fid).get("stock_item_code")
        db.upsert_row("order_lines", {"order_id": order_id, "item_code": code, "qty": data["required_qty"],
                                      "factory_id": fid}, key_columns=("order_id", "item_code"))
    return _order_view(db.get_order(order_id) or row)


# ─── Stock and shipments (read-only) ─────────────────────────────────────────

def _shipment_views(fid: str) -> List[Dict[str, Any]]:
    now = _now()
    names = {s["id"]: s.get("name") for s in db.fetch_where("suppliers", {"factory_id": fid})}
    out = []
    for s in db.get_inbound_shipments(fid):
        try:
            eta_hours = round((parse_timestamp(s["eta"]) - now).total_seconds() / 3600, 1)
        except (ValueError, TypeError):
            eta_hours = None
        out.append({"shipment_id": s["shipment_id"], "item_code": s.get("item_code"),
                    "supplier_id": s.get("supplier_id"), "supplier_name": names.get(s.get("supplier_id")),
                    "qty": s.get("qty"), "eta": s.get("eta"), "eta_hours": eta_hours, "status": s.get("status")})
    return out


@router.get("/stock")
def get_stock(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *ANY_ROLE)
    levels = db.get_stock_levels(fid)
    items = [{"item_code": i["item_code"], "name": i.get("name"), "unit": i.get("unit"),
              "on_hand_qty": levels.get(i["item_code"], 0)} for i in db.get_items(fid)]
    return {"factory_id": fid, "items": items, "shipments": _shipment_views(fid)}


@router.get("/shipments")
def get_shipments(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _factory_of(actor, factory_id, *ANY_ROLE)
    return {"factory_id": fid, "shipments": _shipment_views(fid)}


# ─── Telegram contact invites ────────────────────────────────────────────────

def _invite_link(factory_id: str, kind: str, target_id: str) -> Dict[str, Any]:
    username = settings.TELEGRAM_BOT_USERNAME
    if not username:
        raise HTTPException(status_code=409, detail="TELEGRAM_BOT_USERNAME is not set: the bot's @username is "
                            "needed to build the invite link")
    invite = inbound.create_contact_invite(factory_id, kind, target_id)
    return {"link": f"https://t.me/{username}?start={invite['token']}", "expires_at": invite["expires_at"]}


@router.post("/suppliers/{supplier_id}/telegram-invite")
def supplier_telegram_invite(supplier_id: str, actor: Actor = Depends(user_actor)):
    row = _owned(db.get_supplier(supplier_id), actor, WRITE_ROLES, "supplier")
    return _invite_link(row["factory_id"], "supplier", supplier_id)


@router.post("/orders/{order_id}/telegram-invite")
def order_telegram_invite(order_id: str, actor: Actor = Depends(user_actor)):
    row = _owned(db.get_order(order_id), actor, WRITE_ROLES, "order")
    return _invite_link(row["factory_id"], "client", order_id)


# ─── CSV import ──────────────────────────────────────────────────────────────

def _csv_import(payload: ErpCsvSyncRequest, actor: Actor, parse, list_existing, upsert, model) -> Dict[str, Any]:
    fid = actor.authorize(payload.factory_id, *WRITE_ROLES)
    if not payload.csv_content.strip():
        raise HTTPException(status_code=400, detail="Empty CSV content")
    result = parse(payload.csv_content)
    errors = list(result.errors)
    imported = 0
    existing = {(r.get("name") or "").strip().lower(): r for r in list_existing(fid)}
    for raw in result.rows:
        line = raw.pop("_line")
        try:
            data = model(**raw).model_dump(exclude_unset=True)   # only what the row stated
            saved = upsert(fid, data, existing.get(data["name"].strip().lower()))
            existing[data["name"].strip().lower()] = saved
            imported += 1
        except ValidationError as exc:
            errors.append({"line": line, "error": _fields(exc)})
        except HTTPException as exc:
            errors.append({"line": line, "error": exc.detail})
    return {"success": not errors, "filename": payload.filename, "imported_count": imported,
            "errors": errors, "warnings": []}


def _supplier_upsert(fid, data, existing):
    if existing is None:
        return _create_supplier(fid, SupplierIn(**data).model_dump())
    return _update_supplier(fid, existing, data)


def _line_upsert(fid, data, existing):
    if existing is None:
        return _create_line(fid, LineIn(**data).model_dump())
    return _update_line(fid, existing, data)


@router.post("/ingest/suppliers-csv")
def ingest_suppliers_csv(payload: ErpCsvSyncRequest, actor: Actor = Depends(machine_actor)):
    """Suppliers from a CSV (columns: name, sourcing_role, max_units, lead_hours, route, risk_profile;
    optional unit_cost, flat_cost, min_lead_hours, past_orders, on_time, telegram_chat_id). A row whose
    name matches a supplier of the factory updates it; otherwise a supplier is created. Row-level errors."""
    return _csv_import(payload, actor, importers.parse_suppliers_csv,
                       lambda f: db.fetch_where("suppliers", {"factory_id": f}), _supplier_upsert, SupplierIn)


@router.post("/ingest/lines-csv")
def ingest_lines_csv(payload: ErpCsvSyncRequest, actor: Actor = Depends(machine_actor)):
    """Production lines from a CSV (columns: name, rated_units_per_hour; optional ot_units_per_hour,
    ot_cost_per_hour, max_ot_hours). A row whose name matches a line of the factory updates it."""
    return _csv_import(payload, actor, importers.parse_lines_csv,
                       lambda f: db.fetch_where("production_lines", {"factory_id": f}), _line_upsert, LineIn)


# ─── Team (owner only) ───────────────────────────────────────────────────────

def _team_owner(actor: Actor, factory_id: Optional[str]) -> str:
    return actor.authorize(factory_id, *OWNER_ONLY)


def _member_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"user_id": str(row["user_id"]), "email": row.get("email"), "role": row["role"]}


def _lookup_user_id(email: str) -> Optional[str]:
    """The id of an existing signed-up user: Supabase Auth (admin lookup) live, the dev users
    seeded in the offline mirror otherwise."""
    if settings.storage_mode == "offline":
        found = db.get_dev_user(email)
        return found[0] if found else None
    user = admin.find_user(email)
    return str(user.id) if user is not None else None


def _members(fid: str) -> List[Dict[str, Any]]:
    return db.get_factory_members(fid)


def _is_last_owner(fid: str, user_id: str) -> bool:
    owners = [str(m["user_id"]) for m in _members(fid) if m["role"] == "owner"]
    return owners == [user_id]


@router.get("/team")
def get_team(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _team_owner(actor, factory_id)
    members = _members(fid)
    emails = {str(m["user_id"]): m.get("email") for m in members}
    chats = [{"channel": c["channel"], "address": c["address"], "user_id": str(c["user_id"]),
              "email": emails.get(str(c["user_id"]))}
             for c in db.fetch_where("user_channels", {"factory_id": fid})]
    return {"factory_id": fid, "roles": list(ROLES), "members": [_member_view(m) for m in members],
            "linked_chats": sorted(chats, key=lambda c: (c["channel"], c["address"]))}


@router.post("/team", status_code=201)
def add_team_member(body: MemberIn, factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _team_owner(actor, factory_id)
    try:
        user_id = _lookup_user_id(body.email)
    except admin.AdminError as exc:
        logger.error("Team lookup failed: %s", exc)
        raise HTTPException(status_code=503, detail="User lookup is unavailable right now") from None
    if user_id is None:
        raise HTTPException(status_code=404, detail="No user with that email: ask them to sign up first")
    if db.get_member(user_id, fid) is not None:
        raise HTTPException(status_code=409, detail="That user is already a member; change their role instead")
    row = db.upsert_row("factory_members", {"user_id": user_id, "factory_id": fid, "role": body.role,
                                            "email": body.email}, key_columns=("user_id", "factory_id"))
    return _member_view({"user_id": user_id, "role": body.role, "email": body.email, **(row or {})})


@router.patch("/team/{user_id}")
def patch_team_member(user_id: str, body: MemberPatch, factory_id: Optional[str] = None,
                      actor: Actor = Depends(user_actor)):
    fid = _team_owner(actor, factory_id)
    member = db.get_member(user_id, fid)
    if member is None:
        raise _not_found("member")
    if body.role != "owner" and _is_last_owner(fid, user_id):
        raise HTTPException(status_code=409, detail="A factory needs at least one owner; make someone else an owner first")
    db.update_rows_where("factory_members", {"user_id": user_id, "factory_id": fid}, {"role": body.role})
    return _member_view({"user_id": user_id, "email": member.get("email"), "role": body.role})


@router.delete("/team/{user_id}")
def remove_team_member(user_id: str, factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    fid = _team_owner(actor, factory_id)
    if db.get_member(user_id, fid) is None:
        raise _not_found("member")
    if _is_last_owner(fid, user_id):
        raise HTTPException(status_code=409, detail="A factory needs at least one owner; make someone else an owner first")
    db.delete_rows_where("factory_members", {"user_id": user_id, "factory_id": fid})
    db.delete_rows_where("user_channels", {"user_id": user_id, "factory_id": fid})
    return {"removed": user_id}
