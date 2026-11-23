"""
Vendor reliability learned from recorded deliveries (Beta posterior).

Prior: a vendor's seed history (vendor_history.past_orders_count / on_time_deliveries) counts as
past deliveries. Each DELIVERED outcome recorded through POST /api/v1/deliveries adds one more
observation. The reliability is the posterior mean of a Beta(1, 1)-initialised success rate:

    alpha = on_time_total + 1
    beta  = (total - on_time_total) + 1
    reliability = alpha / (alpha + beta)

so 48 on-time of 50 gives 49 / 52 = 94.2 %. The result is always inside [0, 100].
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Union

DEFAULT_GRACE_HOURS = 2.0
# A delivery recorded as arriving more than this long before it was promised is a data-entry error.
MAX_EARLY_DAYS = 30


def beta_reliability(prior_on_time: int, prior_total: int,
                     outcomes_on_time: int, outcomes_total: int) -> float:
    """Posterior mean reliability in percent (1 decimal) of prior history plus recorded outcomes."""
    if min(prior_on_time, prior_total, outcomes_on_time, outcomes_total) < 0:
        raise ValueError("delivery counts must be non-negative")
    if prior_on_time > prior_total or outcomes_on_time > outcomes_total:
        raise ValueError("on-time deliveries cannot exceed total deliveries")
    alpha = prior_on_time + outcomes_on_time + 1
    beta = (prior_total - prior_on_time) + (outcomes_total - outcomes_on_time) + 1
    return round(100.0 * alpha / (alpha + beta), 1)


def parse_timestamp(value: Union[str, datetime]) -> datetime:
    """ISO-8601 string or datetime to an aware datetime (a naive one is taken as UTC)."""
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def on_time(promised_at: Union[str, datetime], delivered_at: Union[str, datetime],
            grace_hours: float = DEFAULT_GRACE_HOURS) -> bool:
    """True when the delivery arrived no later than `grace_hours` after the promised time."""
    return parse_timestamp(delivered_at) <= parse_timestamp(promised_at) + timedelta(hours=grace_hours)


def implausibly_early(promised_at: Union[str, datetime], delivered_at: Union[str, datetime]) -> bool:
    """True when delivered_at is more than MAX_EARLY_DAYS before promised_at."""
    return parse_timestamp(delivered_at) < parse_timestamp(promised_at) - timedelta(days=MAX_EARLY_DAYS)
