"""Inventory-based shortfall: stock + inbound shipments (shifted by supplier delay) - higher-priority demand."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from app import deadlines
from app.disruption import DisruptionResolutionError

# Orders that no longer consume stock. RISK_ACCEPTED (a NO_ACTION plan was approved) is NOT
# finished: the order still ships and still needs its stock.
FINISHED_STATUSES = frozenset({"DELIVERED", "CANCELLED"})


class InventoryDataError(DisruptionResolutionError):
    """Inventory data needed to compute a shortfall is missing or malformed."""


def _hours(x: float) -> str:
    x = round(float(x), 1)
    return str(int(x)) if x == int(x) else f"{x:.1f}"


def _as_utc(value: Any) -> datetime:
    """Parse an ISO string / datetime. Naive values are treated as UTC."""
    try:
        return deadlines.parse_timestamp(value)
    except ValueError as exc:
        raise InventoryDataError(f"unparseable timestamp: {value!r}") from exc


def deadline_hours(order: Mapping[str, Any], now: datetime) -> float:
    """Hours until the order is due (from its absolute due_at); InventoryDataError when unknown."""
    try:
        return deadlines.deadline_hours(order, now)
    except ValueError as exc:
        raise InventoryDataError(str(exc)) from exc


@dataclass(frozen=True)
class ShipmentView:
    shipment_id: str
    supplier_id: str
    qty: int
    eta_hours: float
    delayed_by_hours: float
    counted: bool
    overdue: bool = False


@dataclass(frozen=True)
class ShortfallBreakdown:
    order_id: str
    item_code: str
    demand: int
    on_hand: int
    inbound_before_deadline: int
    reserved_for_higher_priority: int
    available: int
    shortfall: int
    deadline_hours: float
    shipments: tuple
    overdue_qty: int = 0

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "item_code": self.item_code,
            "demand": self.demand,
            "on_hand": self.on_hand,
            "inbound_before_deadline": self.inbound_before_deadline,
            "reserved_for_higher_priority": self.reserved_for_higher_priority,
            "available": self.available,
            "shortfall": self.shortfall,
            "deadline_hours": self.deadline_hours,
            "overdue_qty": self.overdue_qty,
            "shipments": [
                {
                    "shipment_id": s.shipment_id,
                    "supplier_id": s.supplier_id,
                    "qty": s.qty,
                    "eta_hours": s.eta_hours,
                    "delayed_by_hours": s.delayed_by_hours,
                    "counted": s.counted,
                    "overdue": s.overdue,
                }
                for s in self.shipments
            ],
            "explanation": self.explanation(),
        }

    def explanation(self) -> str:
        text = (
            f"{self.demand} needed − ({self.on_hand} on hand + "
            f"{self.inbound_before_deadline} inbound before the "
            f"{_hours(self.deadline_hours)}h deadline − "
            f"{self.reserved_for_higher_priority} reserved for higher-priority orders) "
            f"= {self.shortfall} short"
        )
        if self.overdue_qty > 0:
            text += f" ({self.overdue_qty} overdue on open POs not counted)"
        if self.available < 0:
            text += (f"; higher-priority orders take all {self.on_hand + self.inbound_before_deadline} "
                     f"available and are {-self.available} short themselves, so this order's whole "
                     f"demand is short")
        return text


def compute_shortfall(
    order_id: str,
    item_code: str,
    orders: Sequence[dict],
    order_lines: Sequence[dict],
    stock: Mapping[str, int],
    shipments: Sequence[dict],
    now: datetime,
    delayed_supplier_id: Optional[str] = None,
    delay_hours: float = 0,
) -> ShortfallBreakdown:
    now = _as_utc(now)
    by_id = {o["order_id"]: o for o in orders}
    order = by_id.get(order_id)
    if order is None:
        raise InventoryDataError(f"order {order_id} not found")

    def line_qty(oid: str) -> Optional[int]:
        return next((int(l["qty"]) for l in order_lines
                     if l["order_id"] == oid and l["item_code"] == item_code), None)

    demand = line_qty(order_id)
    if demand is None:
        raise InventoryDataError(f"order {order_id} has no line for item {item_code}")
    if item_code not in stock:
        raise InventoryDataError(f"no stock record for item {item_code}")
    on_hand = int(stock[item_code])
    deadline = deadline_hours(order, now)

    views = []
    inbound = 0
    overdue_qty = 0
    for s in shipments:
        if s.get("item_code") != item_code or s.get("status") != "OPEN":
            continue
        delayed = float(delay_hours) if (delayed_supplier_id is not None
                                         and s.get("supplier_id") == delayed_supplier_id) else 0.0
        eta_hours = (_as_utc(s["eta"]) - now).total_seconds() / 3600.0 + delayed
        qty = int(s["qty"])
        # An OPEN shipment whose original ETA has already passed is overdue: it has not
        # arrived (else it would be booked into stock), so it is not counted as inbound.
        overdue = eta_hours - delayed <= 0
        counted = (not overdue) and eta_hours <= deadline
        if counted:
            inbound += qty
        if overdue:
            overdue_qty += qty
        views.append(ShipmentView(str(s["shipment_id"]), str(s["supplier_id"]), qty,
                                  eta_hours, delayed, counted, overdue))

    my_rank = order_rank(order, now)
    reserved = 0
    for o in orders:
        if o["order_id"] == order_id or o.get("status") in FINISHED_STATUSES:
            continue
        if order_rank(o, now) < my_rank:
            reserved += line_qty(o["order_id"]) or 0

    available = on_hand + inbound - reserved
    # Never more than the order's own demand: a negative `available` is the higher-priority
    # orders' deficit, not this order's.
    shortfall = min(demand, max(0, demand - available))
    return ShortfallBreakdown(order_id, item_code, demand, on_hand, inbound, reserved,
                              available, shortfall, deadline, tuple(views), overdue_qty)


def order_rank(order: Mapping[str, Any], now: datetime) -> tuple:
    """Reservation order: lower priority number first, then the earlier due time, then the id."""
    priority = order.get("priority")
    if priority is None or isinstance(priority, bool):
        raise InventoryDataError(f"order {order.get('order_id', '?')} has no priority")
    return (int(priority), deadline_hours(order, now), str(order["order_id"]))
