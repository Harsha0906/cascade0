"""
CascadeZero — Supabase Database Client & CRUD Helpers
Features:
  - Live Supabase PostgreSQL connection via supabase-py
  - Automatic in-memory fallback mirror so the app never crashes if
    venue internet or Supabase drops mid-pitch
  - CRUD helpers for all 7 tables
"""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from app.config import settings
from app.deadlines import deadline_hours

logger = logging.getLogger("cascadezero.db")

# ─── In-Memory Fallback Mirror ─────────────────────────────────────────────
# Pre-seeded with the exact same data as schema.sql so the system works
# even without a database connection (zero-crash resilient architecture).
_SEED_SUPPLIERS: list[dict[str, Any]] = [
    {
        "id": "SUP-CHN-01",
        "name": "Chennai Precision Casings Ltd",
        "tier": "TIER-1",
        "route": "NH48 Chennai-Bengaluru Highway",
        "part_name": "Aluminum Battery Casings",
        "inbound_qty": 500,
        "max_available_qty": 500,
        "extra_cost_per_unit_inr": 0,
        "flat_charter_cost_inr": 0,
        "lead_time_hours": 12,
        "traffic_risk_pct": 5.0,
        "weather_risk_pct": 0.0,
        "status": "ON_TIME",
        "delay_hours": 0,
        "whatsapp_number": "",
        "factory_id": "apex-volt-blr2",
        "sourcing_role": "PRIMARY",
        "lead_time_sigma_hours": 1.0,
        "delay_shock_min_hours": 1.0,
        "delay_shock_max_hours": 3.0,
        "unreliable_delay_min_hours": 2.0,
        "unreliable_delay_max_hours": 4.0,
        "min_lead_hours": 8.0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
    {
        "id": "SUP-PNY-02",
        "name": "Peenya Rapid Metals (Local SME Vendor)",
        "tier": "TIER-2",
        "route": "Peenya Industrial Area (14 km)",
        "part_name": "Aluminum Battery Casings",
        "inbound_qty": 0,
        "max_available_qty": 200,
        "extra_cost_per_unit_inr": 600,
        "flat_charter_cost_inr": 0,
        "lead_time_hours": 4,
        "traffic_risk_pct": 6.0,
        "weather_risk_pct": 0.0,
        "status": "STANDBY",
        "delay_hours": 0,
        "whatsapp_number": "",
        "factory_id": "apex-volt-blr2",
        "sourcing_role": "BACKUP",
        "lead_time_sigma_hours": 0.45,
        "delay_shock_min_hours": 1.0,
        "delay_shock_max_hours": 2.5,
        "unreliable_delay_min_hours": 1.5,
        "unreliable_delay_max_hours": 3.0,
        "min_lead_hours": 2.0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
    {
        "id": "SUP-HSR-03",
        "name": "Hosur Precision Castings",
        "tier": "TIER-3",
        "route": "Hosur Industrial Corridor (42 km)",
        "part_name": "Aluminum Battery Casings",
        "inbound_qty": 0,
        "max_available_qty": 180,
        "extra_cost_per_unit_inr": 850,
        "flat_charter_cost_inr": 0,
        "lead_time_hours": 8,
        "traffic_risk_pct": 8.0,
        "weather_risk_pct": 0.0,
        "status": "STANDBY",
        "delay_hours": 0,
        "whatsapp_number": "",
        "factory_id": "apex-volt-blr2",
        "sourcing_role": "BACKUP",
        "lead_time_sigma_hours": 1.1,
        "delay_shock_min_hours": 2.0,
        "delay_shock_max_hours": 4.0,
        "unreliable_delay_min_hours": 2.5,
        "unreliable_delay_max_hours": 5.0,
        "min_lead_hours": 4.0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
    {
        "id": "SUP-AIR-04",
        "name": "BlueDart Aviation Charter",
        "tier": "EMERGENCY-AIR",
        "route": "HAL/KEMPEGOWDA Air Cargo Corridor",
        "part_name": "Aluminum Battery Casings",
        "inbound_qty": 0,
        "max_available_qty": 500,
        "extra_cost_per_unit_inr": 0,
        "flat_charter_cost_inr": 600000,
        "lead_time_hours": 6,
        "traffic_risk_pct": 0.0,
        "weather_risk_pct": 2.0,
        "status": "STANDBY",
        "delay_hours": 0,
        "whatsapp_number": "",
        "factory_id": "apex-volt-blr2",
        "sourcing_role": "EXPEDITE",
        "lead_time_sigma_hours": 0.25,
        "delay_shock_min_hours": 1.0,
        "delay_shock_max_hours": 2.0,
        "unreliable_delay_min_hours": 1.0,
        "unreliable_delay_max_hours": 2.0,
        "min_lead_hours": 4.5,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
]

_SEED_VENDOR_HISTORY: list[dict[str, Any]] = [
    {
        "id": 1,
        "supplier_id": "SUP-CHN-01",
        "past_orders_count": 50,
        "on_time_deliveries": 48,
        "reliability_score_pct": 96.0,
        "quality_rejection_rate_pct": 0.5,
        "last_incident_note": "Vulnerable to NE Monsoon flooding near Vellore/Ambur.",
        "factory_id": "apex-volt-blr2",
    },
    {
        "id": 2,
        "supplier_id": "SUP-PNY-02",
        "past_orders_count": 15,
        "on_time_deliveries": 14,
        "reliability_score_pct": 93.3,
        "quality_rejection_rate_pct": 0.8,
        "last_incident_note": "Consistent 4h delivery via Tumkur Road; max batch 200 units.",
        "factory_id": "apex-volt-blr2",
    },
    {
        "id": 3,
        "supplier_id": "SUP-HSR-03",
        "past_orders_count": 11,
        "on_time_deliveries": 9,
        "reliability_score_pct": 81.8,
        "quality_rejection_rate_pct": 2.1,
        "last_incident_note": "Border toll bottleneck at Attibele during peak hours.",
        "factory_id": "apex-volt-blr2",
    },
    {
        "id": 4,
        "supplier_id": "SUP-AIR-04",
        "past_orders_count": 5,
        "on_time_deliveries": 5,
        "reliability_score_pct": 98.5,
        "quality_rejection_rate_pct": 0.0,
        "last_incident_note": "Guaranteed priority airfreight slot; high flat charter fee.",
        "factory_id": "apex-volt-blr2",
    },
]

_SEED_PRODUCTION_LINES: list[dict[str, Any]] = [
    {
        "line_id": "LINE-1",
        "name": "Robotic Welding Line 1",
        "status": "NORMAL",
        "speed_pct": 100,
        "temp_celsius": 61.0,
        "daily_capacity_units": 200,
        "overtime_cost_per_hour_inr": 11250,
        "extra_units_per_ot_hour": 19,
        "max_ot_hours": 8,
        "factory_id": "apex-volt-blr2",
        "rated_units_per_hour": 19,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
    {
        "line_id": "LINE-2",
        "name": "Robotic Welding Line 2",
        "status": "NORMAL",
        "speed_pct": 100,
        "temp_celsius": 62.0,
        "daily_capacity_units": 200,
        "overtime_cost_per_hour_inr": 0,
        "extra_units_per_ot_hour": 0,
        "max_ot_hours": 0,
        "factory_id": "apex-volt-blr2",
        "rated_units_per_hour": 19,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
    {
        "line_id": "LINE-3",
        "name": "Robotic Welding Line 3",
        "status": "NORMAL",
        "speed_pct": 100,
        "temp_celsius": 60.0,
        "daily_capacity_units": 150,
        "overtime_cost_per_hour_inr": 11250,
        "extra_units_per_ot_hour": 19,
        "max_ot_hours": 8,
        "factory_id": "apex-volt-blr2",
        "rated_units_per_hour": 14,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
]

_SEED_ORDERS: list[dict[str, Any]] = [
    {
        "order_id": "EV-402",
        "client": "Ather-Grid Mobility Corp",
        "required_qty": 500,
        "deadline_label": "Friday 17:00 IST (38 Hours Remaining)",
        "hours_remaining": 38,
        "sla_penalty_inr": 2500000,
        "partial_delay_penalty_inr": 500000,
        "status": "ON_TRACK",
        "shortfall_units": 0,
        "priority": 10,
        "factory_id": "apex-volt-blr2",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
    {
        "order_id": "EV-405",
        "client": "Deccan E-Fleet Logistics",
        "required_qty": 300,
        "deadline_label": "Monday 12:00 IST (110 Hours Remaining)",
        "hours_remaining": 110,
        "sla_penalty_inr": 1000000,
        "partial_delay_penalty_inr": 200000,
        "status": "ON_TRACK",
        "shortfall_units": 0,
        "priority": 20,
        "factory_id": "apex-volt-blr2",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
]

_SEED_FACTORIES: list[dict[str, Any]] = [
    {
        "id": "apex-volt-blr2",
        "name": "Apex Volt EV Battery Plant (Bengaluru Unit-2)",
        "stock_item_name": "Aluminium Battery Casing",
        "stock_item_code": "CASING",
        "qa_dispatch_hours": 2.5,
        "safety_stock_units": 50,
        "production_hours_in_window": 16,
    },
]

_SEED_SCENARIOS: list[dict[str, Any]] = [
    {
        "factory_id": "apex-volt-blr2",
        "scenario_id": 1,
        "title": "NH48 flood + Line 2 overheat",
        "summary": "48h delay, Line 2 at 50%, 150 casings short",
        "raw_message": (
            "NH48 Chennai-Bengaluru highway flooding near Vellore delayed shipment of 500 aluminum battery "
            "casings from Chennai Precision by 48 hours. Simultaneously, Robotic Welding Line 2 overheated "
            "to 89.0°C and throttled to 50% speed. Current unit shortfall is 150 casings on Order #EV-402."
        ),
        "delay_hours": 48,
        "shortfall_units": None,  # computed from inventory (Phase 4)
        "line_speeds": {"LINE-2": 50},
        "order_id": "EV-402",
    },
    {
        "factory_id": "apex-volt-blr2",
        "scenario_id": 2,
        "title": "Minor toll delay",
        "summary": "6h delay, Line 2 at 85%, 25 casings short",
        "raw_message": (
            "Minor toll transit delay on NH48 corridor causing 6 hours shipment delay for 25 units. "
            "Welding Line 2 slightly throttled to 85% speed (74°C). Shortfall is 25 battery casings on Order #EV-402."
        ),
        "delay_hours": 6,
        "shortfall_units": 25,
        "line_speeds": {"LINE-2": 85},
        "order_id": "EV-402",
    },
    {
        "factory_id": "apex-volt-blr2",
        "scenario_id": 3,
        "title": "Supplier collapse",
        "summary": "72h delay, Line 2 at 25%, 350 casings short",
        "raw_message": (
            "Severe supplier collapse: Chennai Precision Casings shipment blocked by 72 hours due to "
            "bridge damage near Ranipet. Robotic Welding Line 2 overheated to 92°C and dropped "
            "to 25% speed. Compound shortfall of 350 battery casings on Order #EV-402."
        ),
        "delay_hours": 72,
        "shortfall_units": 350,
        "line_speeds": {"LINE-2": 25},
        "order_id": "EV-402",
    },
]

_SEED_ITEMS: list[dict[str, Any]] = [
    {"factory_id": "apex-volt-blr2", "item_code": "CASING", "name": "Aluminium Battery Casing", "unit": "pcs"},
]

_SEED_STOCK_LEVELS: list[dict[str, Any]] = [
    {"factory_id": "apex-volt-blr2", "item_code": "CASING", "on_hand_qty": 350},
]

_SEED_ORDER_LINES: list[dict[str, Any]] = [
    {"order_id": "EV-402", "item_code": "CASING", "qty": 500, "factory_id": "apex-volt-blr2"},
    {"order_id": "EV-405", "item_code": "CASING", "qty": 300, "factory_id": "apex-volt-blr2"},
]

_SEED_SHIPMENT_ETA_HOURS = 20


def _seed_orders(now: datetime | None = None) -> list[dict[str, Any]]:
    """Demo orders; each is due `hours_remaining` hours after the reset/startup time."""
    now = now or datetime.now(timezone.utc)
    return [{**o, "due_at": (now + timedelta(hours=o["hours_remaining"])).isoformat()}
            for o in copy.deepcopy(_SEED_ORDERS)]


def _seed_inbound_shipments(now: datetime | None = None) -> list[dict[str, Any]]:
    """Demo inbound shipment; its eta is relative to the reset/startup time."""
    now = now or datetime.now(timezone.utc)
    return [{
        "shipment_id": "SHP-CHN-0001", "factory_id": "apex-volt-blr2", "item_code": "CASING",
        "supplier_id": "SUP-CHN-01", "qty": 500,
        "eta": (now + timedelta(hours=_SEED_SHIPMENT_ETA_HOURS)).isoformat(), "status": "OPEN",
    }]


REQUIRED_MIGRATION_LEVEL = 8

# The only factory with demo seed data (POST /api/v1/reset restores it; other factories -> 409).
DEMO_FACTORY_ID = "apex-volt-blr2"

# Dev/test identities (offline mirror only, AUTH_MODE=dev). Live memberships live in Supabase
# `factory_members` and are managed with `python -m app.admin add-member`.
_SEED_FACTORY_MEMBERS: list[dict[str, Any]] = [
    {"user_id": "00000000-0000-4000-8000-000000000001", "factory_id": "apex-volt-blr2",
     "role": "owner", "email": "dev-owner@example.test"},
    {"user_id": "00000000-0000-4000-8000-000000000002", "factory_id": "apex-volt-blr2",
     "role": "viewer", "email": "dev-viewer@example.test"},
    {"user_id": "00000000-0000-4000-8000-000000000003", "factory_id": "test-plant",
     "role": "owner", "email": "other@example.test"},
]

# Durable-state tables cleared on reset, with their primary-key column.
_DURABLE_TABLES: tuple[tuple[str, str], ...] = (
    ("analysis_runs", "run_id"),
    ("sourcing_sessions", "run_id"),
    ("order_coordination", "root_run_id"),
    ("execution_receipts", "root_run_id"),
    ("webhook_events", "message_id"),
)


class InMemoryMirror:
    """
    Thread-safe in-memory data store that mirrors the Supabase schema.
    Activated automatically when Supabase is unreachable.
    """

    def __init__(self) -> None:
        self.factories: list[dict[str, Any]] = copy.deepcopy(_SEED_FACTORIES)
        self.suppliers: list[dict[str, Any]] = copy.deepcopy(_SEED_SUPPLIERS)
        self.vendor_history: list[dict[str, Any]] = copy.deepcopy(_SEED_VENDOR_HISTORY)
        self.production_lines: list[dict[str, Any]] = copy.deepcopy(_SEED_PRODUCTION_LINES)
        now = datetime.now(timezone.utc)
        self.orders: list[dict[str, Any]] = _seed_orders(now)
        self.scenarios: list[dict[str, Any]] = copy.deepcopy(_SEED_SCENARIOS)
        self.items: list[dict[str, Any]] = copy.deepcopy(_SEED_ITEMS)
        self.stock_levels: list[dict[str, Any]] = [
            {**r, "as_of": now.isoformat()} for r in copy.deepcopy(_SEED_STOCK_LEVELS)
        ]
        self.inbound_shipments: list[dict[str, Any]] = _seed_inbound_shipments(now)
        self.order_lines: list[dict[str, Any]] = copy.deepcopy(_SEED_ORDER_LINES)
        self.delivery_outcomes: list[dict[str, Any]] = []
        self.disruption_events: list[dict[str, Any]] = []
        self.agent_logs: list[dict[str, Any]] = []
        self.purchase_orders: list[dict[str, Any]] = []
        self.sourcing_rfqs: list[dict[str, Any]] = []
        self.analysis_runs: list[dict[str, Any]] = []
        self.sourcing_sessions: list[dict[str, Any]] = []
        self.order_coordination: list[dict[str, Any]] = []   # Client Agent records (Round A)
        self.execution_receipts: list[dict[str, Any]] = []
        self.webhook_events: list[dict[str, Any]] = []
        self.factory_members: list[dict[str, Any]] = copy.deepcopy(_SEED_FACTORY_MEMBERS)
        self.schema_migrations: list[dict[str, Any]] = [
            {"version": v} for v in range(1, REQUIRED_MIGRATION_LEVEL + 1)
        ]

    def get_table(self, table_name: str) -> list[dict[str, Any]]:
        """Return reference to an in-memory table by name."""
        return getattr(self, table_name, [])


# ─── Singleton Mirror ──────────────────────────────────────────────────────
_mirror = InMemoryMirror()

# ─── Supabase Client ───────────────────────────────────────────────────────
_supabase_client = None
_warned_offline = False


class DatabaseError(RuntimeError):
    """A live-database operation failed. The driver message is logged, never exposed."""

    def __init__(self, operation: str, table: str) -> None:
        self.operation = operation
        self.table = table
        super().__init__(f"{operation} {table} failed")


def _fail(operation: str, table: str, exc: Exception) -> DatabaseError:
    logger.error("Database %s on %s failed: %s", operation, table, exc)
    return DatabaseError(operation, table)


def _get_supabase():
    """Lazy-initialize the Supabase client.

    Returns None only in offline mode (no credentials). When credentials are
    configured but the client cannot be created, raises DatabaseError.
    """
    global _supabase_client, _warned_offline
    if _supabase_client is not None:
        return _supabase_client
    if not settings.has_supabase:
        if not _warned_offline:
            _warned_offline = True
            logger.warning("⚠ Supabase credentials not configured — using in-memory mirror")
        return None
    try:
        from supabase import create_client

        _supabase_client = create_client(settings.SUPABASE_URL, settings.supabase_server_key)
        logger.info("✅ Supabase client connected to %s", settings.SUPABASE_URL)
        return _supabase_client
    except Exception as exc:
        raise _fail("connect", "supabase", exc) from exc


# ─── Generic CRUD Helpers ──────────────────────────────────────────────────


def fetch_all(table_name: str) -> list[dict[str, Any]]:
    """Fetch all rows from a table. Offline mode reads the in-memory mirror."""
    client = _get_supabase()
    if client is not None:
        try:
            response = client.table(table_name).select("*").execute()
            return response.data or []
        except Exception as exc:
            raise _fail("fetch_all", table_name, exc) from exc
    return copy.deepcopy(_mirror.get_table(table_name))


def fetch_by_id(table_name: str, pk_column: str, pk_value: str) -> dict[str, Any] | None:
    """Fetch a single row by primary key. Offline mode reads the in-memory mirror."""
    client = _get_supabase()
    if client is not None:
        try:
            response = (
                client.table(table_name).select("*").eq(pk_column, pk_value).execute()
            )
            rows = response.data or []
            return rows[0] if rows else None
        except Exception as exc:
            raise _fail("fetch_by_id", table_name, exc) from exc
    # Offline mirror
    for row in _mirror.get_table(table_name):
        if row.get(pk_column) == pk_value:
            return copy.deepcopy(row)
    return None


def fetch_where(table_name: str, match: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows matching ALL `match` equalities (the tenant filter: {"factory_id": ...})."""
    if not match:
        raise ValueError("fetch_where needs at least one column to match")
    client = _get_supabase()
    if client is not None:
        try:
            query = client.table(table_name).select("*")
            for column, value in match.items():
                query = query.eq(column, value)
            return query.execute().data or []
        except Exception as exc:
            raise _fail("fetch_where", table_name, exc) from exc
    return copy.deepcopy([r for r in _mirror.get_table(table_name)
                          if all(r.get(c) == v for c, v in match.items())])


def fetch_in(table_name: str, column: str, values: Sequence[Any]) -> list[dict[str, Any]]:
    """Rows whose `column` is one of `values` (none for an empty list)."""
    wanted = list(values)
    if not wanted:
        return []
    client = _get_supabase()
    if client is not None:
        try:
            return client.table(table_name).select("*").in_(column, wanted).execute().data or []
        except Exception as exc:
            raise _fail("fetch_in", table_name, exc) from exc
    return copy.deepcopy([r for r in _mirror.get_table(table_name) if r.get(column) in wanted])


def fetch_ordered(
    table_name: str, order_column: str, *, desc: bool = True, limit: int = 1, tiebreak: str | None = None,
    match: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch up to `limit` rows (matching ALL `match` equalities) ordered by a column. Offline
    mode orders the mirror (ties keep insertion order, so the last inserted row is newest)."""
    match = match or {}
    client = _get_supabase()
    if client is not None:
        try:
            query = client.table(table_name).select("*")
            for column, value in match.items():
                query = query.eq(column, value)
            query = query.order(order_column, desc=desc)
            if tiebreak:
                query = query.order(tiebreak, desc=desc)
            response = query.limit(limit).execute()
            return response.data or []
        except Exception as exc:
            raise _fail("fetch_ordered", table_name, exc) from exc
    rows = [r for r in _mirror.get_table(table_name) if all(r.get(c) == v for c, v in match.items())]
    rows = sorted(rows, key=lambda r: r.get(order_column) or "")
    if desc:
        rows.reverse()
    return copy.deepcopy(rows[:limit])


def upsert_row(
    table_name: str,
    row: dict[str, Any],
    key_columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Insert or update a row. Offline mode writes the in-memory mirror.

    `key_columns` names the conflict key for tables with a composite primary key (for
    example stock_levels(factory_id, item_code)). Without it the table's single primary
    key is assumed: PostgREST resolves it, and the offline mirror uses the row's first key.
    """
    client = _get_supabase()
    if client is not None:
        try:
            if key_columns:
                query = client.table(table_name).upsert(row, on_conflict=",".join(key_columns))
            else:
                query = client.table(table_name).upsert(row)
            response = query.execute()
        except Exception as exc:
            raise _fail("upsert", table_name, exc) from exc
        data = response.data or []
        return data[0] if data else row
    # Offline: upsert into mirror
    table = _mirror.get_table(table_name)
    # Detect PK columns: explicit composite key, else the row's first key
    pk_cols = list(key_columns) if key_columns else [next(iter(row))]
    for i, existing in enumerate(table):
        if all(existing.get(c) == row.get(c) for c in pk_cols):
            table[i] = {**existing, **row}
            return table[i]
    table.append(row)
    return row


def insert_row(table_name: str, row: dict[str, Any]) -> dict[str, Any]:
    """Insert a new row. Offline mode writes the in-memory mirror."""
    client = _get_supabase()
    if client is not None:
        try:
            response = client.table(table_name).insert(row).execute()
        except Exception as exc:
            raise _fail("insert", table_name, exc) from exc
        data = response.data or []
        return data[0] if data else row
    # Offline
    table = _mirror.get_table(table_name)
    table.append(row)
    return row


class OwnershipConflict(ValueError):
    """The row's key already belongs to another factory; nothing was written."""

    def __init__(self, table: str, key: dict[str, Any]) -> None:
        self.table, self.key = table, dict(key)
        super().__init__(f"{table} {key} belongs to another factory")


def _is_unique_violation(exc: BaseException | None) -> bool:
    code = str(getattr(exc, "code", "") or "")
    return code == "23505" or (not code and bool(re.search(r"\b23505\b", _error_text(exc))))


def upsert_owned(
    table_name: str, row: dict[str, Any], key_columns: Sequence[str], owner_column: str = "factory_id",
) -> dict[str, Any]:
    """Insert `row`, or update the existing row with the same key ONLY when it has the same owner.

    For tables keyed by a global id (orders.order_id, suppliers.id, inbound_shipments.shipment_id,
    ...): a plain upsert would overwrite another factory's row that happens to use the same key.
    Here the write itself is conditional: an UPDATE filtered by key AND owner, else an INSERT (which
    never overwrites). A key held by another owner raises OwnershipConflict and writes nothing, even
    when a concurrent writer created it after the caller's own ownership check.
    """
    owner = row.get(owner_column)
    if not owner:
        raise ValueError(f"upsert_owned needs {owner_column} on the row")
    key = {c: row[c] for c in key_columns}
    client = _get_supabase()
    if client is None:
        with _conditional_lock:
            table = _mirror.get_table(table_name)
            for existing in table:
                if all(existing.get(c) == v for c, v in key.items()):
                    if existing.get(owner_column) != owner:
                        raise OwnershipConflict(table_name, key)
                    existing.update(row)
                    return copy.deepcopy(existing)
            table.append(dict(row))
            return copy.deepcopy(row)
    updates = {k: v for k, v in row.items() if k not in key}
    for _ in range(2):   # second pass: a same-owner row inserted concurrently is then updated
        updated = update_rows_where(table_name, {**key, owner_column: owner}, updates)
        if updated:
            return updated[0]
        try:
            return insert_row(table_name, row)
        except DatabaseError as exc:
            if not _is_unique_violation(exc.__cause__):
                raise
    raise OwnershipConflict(table_name, key)


def update_rows(
    table_name: str,
    pk_column: str,
    pk_value: str,
    updates: dict[str, Any],
) -> list[dict[str, Any]]:
    """Update matching rows. Offline mode updates the in-memory mirror."""
    client = _get_supabase()
    if client is not None:
        try:
            response = (
                client.table(table_name)
                .update(updates)
                .eq(pk_column, pk_value)
                .execute()
            )
            return response.data or []
        except Exception as exc:
            raise _fail("update", table_name, exc) from exc
    # Offline
    updated = []
    for row in _mirror.get_table(table_name):
        if row.get(pk_column) == pk_value:
            row.update(updates)
            updated.append(copy.deepcopy(row))
    return updated


_conditional_lock = threading.Lock()


def update_rows_where(
    table_name: str, match: dict[str, Any], updates: dict[str, Any]
) -> list[dict[str, Any]]:
    """Update rows matching ALL `match` equalities and return the updated rows
    (empty list when nothing matched): the compare-and-set primitive behind optimistic
    concurrency. Offline mode does it under a lock on the mirror."""
    client = _get_supabase()
    if client is not None:
        try:
            query = client.table(table_name).update(updates)
            for column, value in match.items():
                query = query.eq(column, value)
            return query.execute().data or []
        except Exception as exc:
            raise _fail("update", table_name, exc) from exc
    with _conditional_lock:
        updated = []
        for row in _mirror.get_table(table_name):
            if all(row.get(c) == v for c, v in match.items()):
                row.update(updates)
                updated.append(copy.deepcopy(row))
        return updated


def delete_rows_where(table_name: str, match: dict[str, Any]) -> int:
    """Delete the rows matching ALL `match` equalities; returns how many were deleted (offline)
    or how many the database reported. Used by the snapshot imports."""
    if not match:
        raise ValueError("delete_rows_where needs at least one column to match")
    client = _get_supabase()
    if client is not None:
        try:
            query = client.table(table_name).delete()
            for column, value in match.items():
                query = query.eq(column, value)
            return len(query.execute().data or [])
        except Exception as exc:
            raise _fail("delete", table_name, exc) from exc
    with _conditional_lock:
        table = _mirror.get_table(table_name)
        keep = [r for r in table if not all(r.get(c) == v for c, v in match.items())]
        deleted = len(table) - len(keep)
        table[:] = keep
        return deleted


def delete_all(table_name: str) -> bool:
    """Delete all rows from a table. Used for reset. Offline mode clears the mirror."""
    client = _get_supabase()
    if client is not None:
        try:
            # Supabase delete requires a filter; use neq on a column that always exists
            client.table(table_name).delete().neq("id", "___impossible___").execute()
            return True
        except Exception as exc:
            raise _fail("delete_all", table_name, exc) from exc
    # Offline: clear mirror table
    table = _mirror.get_table(table_name)
    table.clear()
    return True


def _is_missing_table(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "")
    text = str(exc).lower()
    return (
        code in ("PGRST205", "42P01")
        or "could not find the table" in text
        or ("relation" in text and "does not exist" in text)
    )


def migration_level() -> int:
    """Highest applied migration version (0 if schema_migrations is missing)."""
    client = _get_supabase()
    if client is not None:
        try:
            response = (
                client.table("schema_migrations")
                .select("version")
                .order("version", desc=True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            if _is_missing_table(exc):
                return 0
            raise _fail("migration_level", "schema_migrations", exc) from exc
        rows = response.data or []
        return int(rows[0]["version"]) if rows else 0
    return max((r["version"] for r in _mirror.schema_migrations), default=0)


def record_webhook_event(message_id: str) -> bool:
    """Record a Meta webhook message id. True when newly recorded, False when already seen
    (a duplicate delivery). Other database failures raise DatabaseError."""
    row = {"message_id": message_id, "received_at": datetime.now(timezone.utc).isoformat()}
    client = _get_supabase()
    if client is not None:
        try:
            client.table("webhook_events").insert(row).execute()
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "")
            text = _error_text(exc)
            if code == "23505" or (not code and re.search(r"\b23505\b", text)):
                return False
            raise _fail("insert", "webhook_events", exc) from exc
        return True
    with _conditional_lock:
        if any(r["message_id"] == message_id for r in _mirror.webhook_events):
            return False
        _mirror.webhook_events.append(row)
        return True


def release_webhook_event(message_id: str) -> None:
    """Forget a recorded Meta message id so that Meta's retry is processed again.
    Used when processing failed after record_webhook_event. Failures raise DatabaseError."""
    client = _get_supabase()
    if client is not None:
        try:
            client.table("webhook_events").delete().eq("message_id", message_id).execute()
        except Exception as exc:
            raise _fail("delete", "webhook_events", exc) from exc
        return
    with _conditional_lock:
        _mirror.webhook_events[:] = [r for r in _mirror.webhook_events if r["message_id"] != message_id]


def call_function(name: str, params: dict[str, Any]) -> Any:
    """Call a Postgres function via supabase rpc. Not available offline."""
    client = _get_supabase()
    if client is None:
        raise DatabaseError("rpc", name)
    try:
        return client.rpc(name, params).execute().data
    except Exception as exc:
        raise _fail("rpc", name, exc) from exc


class AlreadyExecutedError(RuntimeError):
    """A plan for this root run was already executed (idempotency guard tripped)."""

    def __init__(self, root_run_id: str) -> None:
        self.root_run_id = root_run_id
        super().__init__(f"root run {root_run_id} already executed")


_EXECUTION_TABLES = (
    "execution_receipts", "purchase_orders", "orders", "suppliers", "production_lines", "agent_logs",
    "delivery_outcomes",
)
_execute_lock = threading.Lock()
_RECEIPTS_CONSTRAINT = "execution_receipts_pkey"


def _error_text(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    return f"{getattr(exc, 'code', '')} {exc!s} {getattr(exc, 'args', '')!r}"


def _execute_plan_tx_live(params: dict[str, Any], root_run_id: str) -> dict[str, Any]:
    try:
        result = call_function("execute_plan_tx", params)
    except DatabaseError as exc:
        cause = exc.__cause__
        code = str(getattr(cause, "code", "") or "")
        text = _error_text(cause)
        if code == "23505" or (not code and re.search(r"\b23505\b", text)):
            if _RECEIPTS_CONSTRAINT in text:
                raise AlreadyExecutedError(root_run_id) from exc
        elif (code == "PGRST202" or (not code and re.search(r"\bPGRST202\b", text))
                or "Could not find the function" in text):
            logger.error("execute_plan_tx is missing: apply supabase/migrations/004_durable_state.sql")
        raise
    return result if isinstance(result, dict) else params["p_receipt"]


def execute_plan_tx(
    po: dict[str, Any],
    order_id: str,
    order_status: str,
    supplier_updates: list[dict[str, Any]],
    overtime_line_ids: list[str],
    agent_log: dict[str, Any],
    root_run_id: str,
    receipt: dict[str, Any],
    outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute an approved plan atomically; a repeated root_run_id raises AlreadyExecutedError.
    `outcomes` are the PENDING delivery_outcomes rows written in the same transaction."""
    outcomes = outcomes or []
    client = _get_supabase()
    if client is not None:
        return _execute_plan_tx_live({
            "p_po": po,
            "p_order_id": order_id,
            "p_order_status": order_status,
            "p_supplier_updates": supplier_updates,
            "p_overtime_line_ids": overtime_line_ids,
            "p_agent_log": agent_log,
            "p_root_run_id": root_run_id,
            "p_receipt": receipt,
            "p_outcomes": outcomes,
        }, root_run_id)

    # Offline: all-or-nothing on the mirror, same write order as the SQL function.
    # NOTE (offline/demo only): rollback restores snapshots of whole _EXECUTION_TABLES, so a
    # concurrent writer that does not hold _execute_lock (e.g. Sourcing's agent_logs) can have
    # its rows erased by a rollback. The live path is a real transaction and has no such issue.
    factory = po.get("factory_id") or receipt.get("factory_id")
    with _execute_lock:
        mirror = _mirror
        snapshot = {t: copy.deepcopy(mirror.get_table(t)) for t in _EXECUTION_TABLES}
        try:
            if any(r.get("root_run_id") == root_run_id for r in mirror.execution_receipts):
                raise AlreadyExecutedError(root_run_id)
            insert_row("execution_receipts", {
                "root_run_id": root_run_id,
                "run_id": receipt.get("run_id", root_run_id),
                "playbook_id": receipt.get("playbook_id", ""),
                "factory_id": factory,
                "payload": copy.deepcopy(receipt),
            })
            insert_row("purchase_orders", {**po, "factory_id": factory} if factory else dict(po))
            now = datetime.now(timezone.utc).isoformat()
            # Like the SQL function: updates touch only the executing factory's rows.
            scope = {"factory_id": factory} if factory else {}
            if not update_rows_where("orders", {"order_id": order_id, **scope},
                                     {"status": order_status, "updated_at": now}):
                raise DatabaseError("update", "orders")  # mirrors the SQL IF NOT FOUND; rolls back below
            for upd in supplier_updates:
                update_rows_where("suppliers", {"id": upd["supplier_id"], **scope}, {
                    "status": "PO_DRAFTED", "inbound_qty": upd["inbound_qty"], "updated_at": now,
                })
            for lid in overtime_line_ids:
                update_rows_where("production_lines", {"line_id": lid, **scope},
                                  {"status": "OVERTIME_SCHEDULED", "updated_at": now})
            entries = agent_log if isinstance(agent_log, list) else [agent_log] if agent_log else []
            for entry in entries:
                insert_row("agent_logs", {"created_at": now, **entry, "factory_id": factory or entry.get("factory_id")})
            for o in outcomes:   # like the SQL function: always the executing factory's
                _insert_pending_outcome({**o, "factory_id": factory} if factory else o, now)
        except BaseException:
            for t, rows in snapshot.items():
                setattr(mirror, t, rows)
            raise
    return receipt


def _insert_pending_outcome(o: dict[str, Any], now: str) -> None:
    """Offline twin of step 7 of execute_plan_tx; raises like the table's UNIQUE (po_number, supplier_id)."""
    table = _mirror.delivery_outcomes
    if any(r["po_number"] == o["po_number"] and r["supplier_id"] == o["supplier_id"] for r in table):
        raise DatabaseError("insert", "delivery_outcomes")
    table.append({
        "id": max((r["id"] for r in table), default=0) + 1,
        "factory_id": o["factory_id"], "supplier_id": o["supplier_id"], "po_number": o["po_number"],
        "units": int(o["units"]), "promised_at": o["promised_at"], "delivered_at": None,
        "status": "PENDING", "recorded_at": now,
    })


def get_memberships(user_id: str) -> dict[str, str]:
    """factory_id -> role for a verified user id (live `factory_members`, else the mirror)."""
    client = _get_supabase()
    if client is not None:
        try:
            response = (client.table("factory_members").select("factory_id,role")
                        .eq("user_id", user_id).execute())
        except Exception as exc:
            raise _fail("get_memberships", "factory_members", exc) from exc
        rows = response.data or []
    else:
        rows = [r for r in _mirror.factory_members if r.get("user_id") == user_id]
    return {r["factory_id"]: r["role"] for r in rows}


def get_dev_user(email: str) -> tuple[str, dict[str, str]] | None:
    """(user_id, factory_id -> role) of a dev user seeded in the offline mirror (AUTH_MODE=dev
    only); None for an unknown email. Never reads the live database."""
    wanted = email.strip().lower()
    rows = [r for r in _mirror.factory_members if (r.get("email") or "").lower() == wanted]
    if not rows:
        return None
    return rows[0]["user_id"], {r["factory_id"]: r["role"] for r in rows}


def get_receipt(root_run_id: str) -> dict[str, Any] | None:
    """Stored execution receipt payload for a root run, or None."""
    row = fetch_by_id("execution_receipts", "root_run_id", root_run_id)
    return copy.deepcopy(row["payload"]) if row else None


# ─── Table-Specific Helpers ────────────────────────────────────────────────


def get_factory_row(factory_id: str) -> dict[str, Any] | None:
    """Fetch one factory (plant constants) by id."""
    return fetch_by_id("factories", "id", factory_id)


def default_factory_name() -> str:
    """Display name of the default factory, falling back to its id if the row is missing."""
    row = get_factory_row(settings.DEFAULT_FACTORY_ID)
    return (row or {}).get("name") or settings.DEFAULT_FACTORY_ID


def get_scenarios(factory_id: str) -> list[dict[str, Any]]:
    """Preset disruption scenarios of one factory, ordered by scenario_id."""
    client = _get_supabase()
    if client is not None:
        try:
            response = (
                client.table("scenarios").select("*").eq("factory_id", factory_id)
                .order("scenario_id").execute()
            )
            return response.data or []
        except Exception as exc:
            raise _fail("get_scenarios", "scenarios", exc) from exc
    rows = [r for r in _mirror.scenarios if r.get("factory_id") == factory_id]
    return copy.deepcopy(sorted(rows, key=lambda r: r["scenario_id"]))


def get_items(factory_id: str) -> list[dict[str, Any]]:
    """Stock items of one factory, ordered by item_code."""
    client = _get_supabase()
    if client is not None:
        try:
            response = (
                client.table("items").select("*").eq("factory_id", factory_id)
                .order("item_code").execute()
            )
            return response.data or []
        except Exception as exc:
            raise _fail("get_items", "items", exc) from exc
    rows = [r for r in _mirror.items if r.get("factory_id") == factory_id]
    return copy.deepcopy(sorted(rows, key=lambda r: r["item_code"]))


def get_stock_levels(factory_id: str) -> dict[str, int]:
    """On-hand quantity per item_code for one factory."""
    client = _get_supabase()
    if client is not None:
        try:
            response = client.table("stock_levels").select("*").eq("factory_id", factory_id).execute()
            rows = response.data or []
        except Exception as exc:
            raise _fail("get_stock_levels", "stock_levels", exc) from exc
    else:
        rows = [r for r in _mirror.stock_levels if r.get("factory_id") == factory_id]
    return {r["item_code"]: int(r["on_hand_qty"]) for r in rows}


def get_inbound_shipments(factory_id: str, status: str = "OPEN") -> list[dict[str, Any]]:
    """Inbound shipments of one factory with the given status, ordered by eta then id."""
    client = _get_supabase()
    if client is not None:
        try:
            response = (
                client.table("inbound_shipments").select("*").eq("factory_id", factory_id)
                .eq("status", status).order("eta").order("shipment_id").execute()
            )
            return response.data or []
        except Exception as exc:
            raise _fail("get_inbound_shipments", "inbound_shipments", exc) from exc
    rows = [r for r in _mirror.inbound_shipments
            if r.get("factory_id") == factory_id and r.get("status") == status]
    return copy.deepcopy(sorted(rows, key=lambda r: (str(r["eta"]), r["shipment_id"])))


def get_order_lines(order_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Order lines (order_id, item_code, qty) of the given orders."""
    ids = list(order_ids)
    if not ids:
        return []
    client = _get_supabase()
    if client is not None:
        try:
            response = (
                client.table("order_lines").select("*").in_("order_id", ids)
                .order("order_id").order("item_code").execute()
            )
            return response.data or []
        except Exception as exc:
            raise _fail("get_order_lines", "order_lines", exc) from exc
    rows = [r for r in _mirror.order_lines if r.get("order_id") in ids]
    return copy.deepcopy(sorted(rows, key=lambda r: (r["order_id"], r["item_code"])))


def get_all_suppliers() -> list[dict[str, Any]]:
    """Fetch all suppliers."""
    return fetch_all("suppliers")


def get_supplier(supplier_id: str) -> dict[str, Any] | None:
    """Fetch a single supplier by ID."""
    return fetch_by_id("suppliers", "id", supplier_id)


def get_vendor_history(supplier_id: str) -> dict[str, Any] | None:
    """Fetch vendor reliability history for a supplier."""
    client = _get_supabase()
    if client is not None:
        try:
            response = (
                client.table("vendor_history")
                .select("*")
                .eq("supplier_id", supplier_id)
                .execute()
            )
            rows = response.data or []
            return rows[0] if rows else None
        except Exception as exc:
            raise _fail("get_vendor_history", "vendor_history", exc) from exc
    # Offline
    for row in _mirror.vendor_history:
        if row.get("supplier_id") == supplier_id:
            return copy.deepcopy(row)
    return None


def get_delivery_outcomes(status: str | None = None, supplier_id: str | None = None,
                          factory_id: str | None = None) -> list[dict[str, Any]]:
    """Delivery outcomes (optionally one status / one supplier / one factory), oldest first."""
    client = _get_supabase()
    if client is not None:
        try:
            query = client.table("delivery_outcomes").select("*")
            if factory_id is not None:
                query = query.eq("factory_id", factory_id)
            if status is not None:
                query = query.eq("status", status)
            if supplier_id is not None:
                query = query.eq("supplier_id", supplier_id)
            return query.order("id").execute().data or []
        except Exception as exc:
            raise _fail("get_delivery_outcomes", "delivery_outcomes", exc) from exc
    rows = [r for r in _mirror.delivery_outcomes
            if (status is None or r["status"] == status)
            and (supplier_id is None or r["supplier_id"] == supplier_id)
            and (factory_id is None or r.get("factory_id") == factory_id)]
    return copy.deepcopy(sorted(rows, key=lambda r: r["id"]))


def get_all_production_lines() -> list[dict[str, Any]]:
    """Fetch all production lines."""
    return fetch_all("production_lines")


def get_production_line(line_id: str) -> dict[str, Any] | None:
    """Fetch a single production line."""
    return fetch_by_id("production_lines", "line_id", line_id)


def _live_hours(order: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    """`hours_remaining` is display only: recompute it from the absolute due_at on every read.
    A legacy order without due_at keeps its stored (static) value."""
    if order is not None and order.get("due_at"):
        order["hours_remaining"] = round(deadline_hours(order, now), 1)
    return order


def get_all_orders() -> list[dict[str, Any]]:
    """Fetch all active orders (hours_remaining recomputed from due_at)."""
    now = datetime.now(timezone.utc)
    return [_live_hours(o, now) for o in fetch_all("orders")]


def get_order(order_id: str) -> dict[str, Any] | None:
    """Fetch a single order (hours_remaining recomputed from due_at)."""
    return _live_hours(fetch_by_id("orders", "order_id", order_id), datetime.now(timezone.utc))


def log_agent_step(
    run_id: str,
    step_order: int,
    agent_name: str,
    agent_role: str,
    badge_color: str,
    tool_called: str = "",
    tool_output_summary: str = "",
    message: str = "",
    factory_id: str | None = None,
) -> dict[str, Any]:
    """Insert an agent log entry for realtime streaming to the terminal. `factory_id` scopes the
    entry to its tenant (GET /api/v1/state shows a factory only its own logs)."""
    row = {
        "run_id": run_id,
        "factory_id": factory_id,
        "step_order": step_order,
        "agent_name": agent_name,
        "agent_role": agent_role,
        "badge_color": badge_color,
        "tool_called": tool_called,
        "tool_output_summary": tool_output_summary,
        "message": message,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return insert_row("agent_logs", row)


def get_agent_logs(run_id: str | None = None) -> list[dict[str, Any]]:
    """Fetch agent logs, optionally filtered by run_id."""
    client = _get_supabase()
    if client is not None:
        try:
            query = client.table("agent_logs").select("*").order("step_order")
            if run_id:
                query = query.eq("run_id", run_id)
            response = query.execute()
            return response.data or []
        except Exception as exc:
            raise _fail("get_agent_logs", "agent_logs", exc) from exc
    # Offline
    logs = _mirror.agent_logs
    if run_id:
        logs = [l for l in logs if l.get("run_id") == run_id]
    return copy.deepcopy(sorted(logs, key=lambda x: x.get("step_order", 0)))


def save_purchase_order(po: dict[str, Any]) -> dict[str, Any]:
    """Save or update a purchase order."""
    return upsert_row("purchase_orders", po)


def get_full_state(factory_id: str) -> dict[str, Any]:
    """
    The snapshot of ONE factory, used by /api/v1/state and by the frontend store for initial
    hydration. Every table is filtered by the factory: suppliers, lines, orders, events, agent
    logs and purchase orders by their factory_id column; vendor_history through the factory's
    supplier ids. A row without a factory_id belongs to no tenant and is never shown.
    """
    if not factory_id:
        raise ValueError("get_full_state needs a factory_id")
    now = datetime.now(timezone.utc)
    suppliers = fetch_where("suppliers", {"factory_id": factory_id})
    return {
        "factory_name": (get_factory_row(factory_id) or {}).get("name") or factory_id,
        "suppliers": suppliers,
        "vendor_history": fetch_in("vendor_history", "supplier_id", [r["id"] for r in suppliers]),
        "production_lines": fetch_where("production_lines", {"factory_id": factory_id}),
        "orders": [_live_hours(o, now) for o in fetch_where("orders", {"factory_id": factory_id})],
        "disruption_events": fetch_where("disruption_events", {"factory_id": factory_id}),
        "agent_logs": fetch_where("agent_logs", {"factory_id": factory_id}),
        "purchase_orders": fetch_where("purchase_orders", {"factory_id": factory_id}),
    }


# Tables a factory owns through another table rather than a factory_id column.
_OWNED_VIA: dict[str, tuple[str, str]] = {
    "vendor_history": ("supplier_id", "supplier"),
    "order_lines": ("order_id", "order"),
    "sourcing_sessions": ("run_id", "run"),
    "sourcing_rfqs": ("run_id", "run"),
}
# Not owned by any factory; a factory reset leaves them alone (webhook ids stay recorded so a
# reset can never re-open another tenant's processed message to a replay).
_UNSCOPED_TABLES = ("webhook_events", "schema_migrations")
# Live tables cleared by a factory reset through their factory_id column.
_FACTORY_DYNAMIC_TABLES = (
    "sourcing_rfqs", "sourcing_sessions",
    "purchase_orders", "agent_logs", "disruption_events", "delivery_outcomes",
    "order_coordination", "execution_receipts", "analysis_runs",
)


def _row_owner(table: str, row: dict[str, Any], owners: dict[str, dict[str, Any]]) -> Any:
    if table == "factories":
        return row.get("id")
    if table in _OWNED_VIA:
        column, kind = _OWNED_VIA[table]
        return owners[kind].get(row.get(column))
    return row.get("factory_id")


def _reset_mirror_factory(factory_id: str) -> None:
    """Offline: the factory's rows go back to the seed; every other factory's rows are kept."""
    global _mirror
    old, new = _mirror, InMemoryMirror()
    owners: dict[str, dict[str, Any]] = {"supplier": {}, "order": {}, "run": {}}
    for m in (old, new):
        owners["supplier"].update({r.get("id"): r.get("factory_id") for r in m.suppliers})
        owners["order"].update({r.get("order_id"): r.get("factory_id") for r in m.orders})
        owners["run"].update({r.get("run_id"): r.get("factory_id") for r in m.analysis_runs})
    for table in list(vars(new)):
        if table in _UNSCOPED_TABLES:
            setattr(new, table, old.get_table(table))
            continue
        seed = [r for r in new.get_table(table) if _row_owner(table, r, owners) == factory_id]
        others = [r for r in old.get_table(table) if _row_owner(table, r, owners) not in (None, factory_id)]
        setattr(new, table, seed + others)
    _mirror = new


def _reset_live_factory(client, factory_id: str) -> None:
    """Live: delete the factory's dynamic rows (by factory_id), then upsert the demo seed.
    Other factories' rows are never touched."""
    for tbl in _FACTORY_DYNAMIC_TABLES:
        client.table(tbl).delete().eq("factory_id", factory_id).execute()


# Seed tables keyed by a global id (not by factory): a seed row is written only where the key is
# free or already the demo factory's (upsert_owned), never over another factory's row.
_SEED_GLOBAL_KEYS: dict[str, tuple[str, ...]] = {
    "suppliers": ("id",),
    "production_lines": ("line_id",),
    "orders": ("order_id",),
    "order_lines": ("order_id", "item_code"),
    "inbound_shipments": ("shipment_id",),
}


def _upsert_demo_seed(client) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    for tbl, seed in (
        ("factories", _SEED_FACTORIES),
        ("suppliers", _SEED_SUPPLIERS),
        ("production_lines", _SEED_PRODUCTION_LINES),
        ("orders", _seed_orders()),
        ("scenarios", _SEED_SCENARIOS),
        ("items", _SEED_ITEMS),
        ("stock_levels", [{**r, "as_of": now_iso} for r in _SEED_STOCK_LEVELS]),
        ("order_lines", _SEED_ORDER_LINES),
        ("inbound_shipments", _seed_inbound_shipments()),
    ):
        for row in seed:
            if tbl in _SEED_GLOBAL_KEYS:
                try:
                    upsert_owned(tbl, row, _SEED_GLOBAL_KEYS[tbl])
                except OwnershipConflict as exc:
                    logger.warning("Reset skipped seed row %s: %s", exc.key, exc)
            else:   # factories (the demo factory's own row) or keyed by (factory_id, ...)
                client.table(tbl).upsert(row).execute()


def reset_to_seed(factory_id: str | None = None) -> dict[str, str]:
    """
    Reset to the demo seed data.

    With `factory_id` (POST /api/v1/reset): only that factory, which must be DEMO_FACTORY_ID;
    every other factory's rows are kept. Without it (tests, local tooling): everything.
    """
    if factory_id is not None and factory_id != DEMO_FACTORY_ID:
        raise ValueError(f"no demo seed for factory {factory_id}")
    global _mirror
    client = _get_supabase()
    if client is None:
        if factory_id is None:
            _mirror = InMemoryMirror()
        else:
            _reset_mirror_factory(factory_id)
        return {"success": True, "status": "reset_complete", "factory": default_factory_name()}

    try:
        if factory_id is not None:
            _reset_live_factory(client, factory_id)
        else:
            # Clear dynamic tables
            client.table("purchase_orders").delete().neq("po_number", "___none___").execute()
            for tbl in ("agent_logs", "disruption_events"):  # SERIAL integer id
                client.table(tbl).delete().gte("id", 0).execute()
            try:
                client.table("sourcing_rfqs").delete().neq("id", "").execute()
            except Exception as exc:
                logger.warning("Could not clear sourcing_rfqs: %s", exc)
            for tbl, pk in _DURABLE_TABLES:
                client.table(tbl).delete().neq(pk, "___impossible___").execute()
            client.table("delivery_outcomes").delete().gte("id", 0).execute()  # BIGSERIAL id
        _upsert_demo_seed(client)
    except Exception as exc:
        raise _fail("reset", "all", exc) from exc
    logger.info("Supabase tables reset to seed data (%s)", factory_id or "all factories")
    return {"success": True, "status": "reset_complete", "factory": default_factory_name()}


# ─── CLI Test Runner ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import io

    # Force UTF-8 output on Windows to support emojis and rupee symbols
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print("=" * 70)
    print("  CASCADEZERO -- Database Layer Verification")
    print("=" * 70)

    state = get_full_state(settings.DEFAULT_FACTORY_ID)
    print(f"\n[FACTORY] {state['factory_name']}")

    print(f"\n[SUPPLIERS] ({len(state['suppliers'])} rows):")
    for s in state["suppliers"]:
        print(
            f"  [{s['id']}] {s['name']} | {s['tier']} | "
            f"Route: {s['route']} | Inbound: {s['inbound_qty']} | "
            f"Max: {s['max_available_qty']} | Status: {s['status']}"
        )

    print(f"\n[VENDOR HISTORY] ({len(state['vendor_history'])} rows):")
    for v in state["vendor_history"]:
        print(
            f"  [{v['supplier_id']}] {v['past_orders_count']} orders | "
            f"{v['on_time_deliveries']} on-time ({v['reliability_score_pct']}%) | "
            f"Rejection: {v['quality_rejection_rate_pct']}% | "
            f"Note: {v['last_incident_note']}"
        )

    print(f"\n[PRODUCTION LINES] ({len(state['production_lines'])} rows):")
    for line in state["production_lines"]:
        print(
            f"  [{line['line_id']}] {line['name']} | {line['status']} | "
            f"Speed: {line['speed_pct']}% | Temp: {line['temp_celsius']}C | "
            f"Cap: {line['daily_capacity_units']} units | "
            f"OT: INR {line['overtime_cost_per_hour_inr']:,}/hr x {line['max_ot_hours']}h"
        )

    print(f"\n[ORDERS] ({len(state['orders'])} rows):")
    for o in state["orders"]:
        print(
            f"  [{o['order_id']}] {o['client']} | "
            f"{o['required_qty']} units | {o['deadline_label']} | "
            f"SLA Penalty: INR {o['sla_penalty_inr']:,} | Status: {o['status']}"
        )

    print(f"\n[DISRUPTION EVENTS] {len(state['disruption_events'])} rows")
    print(f"[AGENT LOGS] {len(state['agent_logs'])} rows")
    print(f"[PURCHASE ORDERS] {len(state['purchase_orders'])} rows")

    print("\n" + "=" * 70)
    print("  STEP 1 VERIFICATION COMPLETE -- All seed data loaded!")
    print("=" * 70)
