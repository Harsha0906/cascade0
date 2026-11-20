"""Order deadlines. An order's deadline is the absolute `due_at`; hours are always derived from it.

No app imports here, so the database layer can use it to recompute `hours_remaining` on read.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def parse_timestamp(value: Any) -> datetime:
    """ISO string or datetime -> aware datetime (naive values are treated as UTC). ValueError otherwise."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError(f"unparseable timestamp: {value!r}")
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def deadline_hours(order_row: Mapping[str, Any], now: datetime) -> float:
    """Hours from `now` until the order is due (negative once the due time has passed).

    Uses the absolute `due_at`. A legacy order with no `due_at` (imported before migration 006
    added the column, and not re-imported since) falls back to its stored `hours_remaining`,
    which is a static number from import time and does not count down. Neither present -> ValueError;
    a deadline is never invented.
    """
    due_at = order_row.get("due_at")
    if due_at not in (None, ""):
        return (parse_timestamp(due_at) - parse_timestamp(now)).total_seconds() / 3600.0
    hours = order_row.get("hours_remaining")
    if hours is None:
        raise ValueError(f"order {order_row.get('order_id', '?')} has no due_at or hours_remaining")
    return float(hours)
