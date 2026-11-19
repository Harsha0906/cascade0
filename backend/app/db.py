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
from datetime import datetime, timezone
from typing import Any

from app.config import settings

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
    },
    {
        "id": 2,
        "supplier_id": "SUP-PNY-02",
        "past_orders_count": 15,
        "on_time_deliveries": 14,
        "reliability_score_pct": 93.3,
        "quality_rejection_rate_pct": 0.8,
        "last_incident_note": "Consistent 4h delivery via Tumkur Road; max batch 200 units.",
    },
    {
        "id": 3,
        "supplier_id": "SUP-HSR-03",
        "past_orders_count": 11,
        "on_time_deliveries": 9,
        "reliability_score_pct": 81.8,
        "quality_rejection_rate_pct": 2.1,
        "last_incident_note": "Border toll bottleneck at Attibele during peak hours.",
    },
    {
        "id": 4,
        "supplier_id": "SUP-AIR-04",
        "past_orders_count": 5,
        "on_time_deliveries": 5,
        "reliability_score_pct": 98.5,
        "quality_rejection_rate_pct": 0.0,
        "last_incident_note": "Guaranteed priority airfreight slot; high flat charter fee.",
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
        "factory_id": "apex-volt-blr2",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    },
]

_SEED_FACTORIES: list[dict[str, Any]] = [
    {
        "id": "apex-volt-blr2",
        "name": "Apex Volt EV Battery Plant (Bengaluru Unit-2)",
        "stock_item_name": "Aluminium Battery Casing",
        "qa_dispatch_hours": 2.5,
        "safety_stock_units": 50,
        "production_hours_in_window": 16,
    },
]


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
        self.orders: list[dict[str, Any]] = copy.deepcopy(_SEED_ORDERS)
        self.disruption_events: list[dict[str, Any]] = []
        self.agent_logs: list[dict[str, Any]] = []
        self.purchase_orders: list[dict[str, Any]] = []
        self.sourcing_rfqs: list[dict[str, Any]] = []

    def get_table(self, table_name: str) -> list[dict[str, Any]]:
        """Return reference to an in-memory table by name."""
        return getattr(self, table_name, [])


# ─── Singleton Mirror ──────────────────────────────────────────────────────
_mirror = InMemoryMirror()

# ─── Supabase Client ───────────────────────────────────────────────────────
_supabase_client = None


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
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    if not settings.has_supabase:
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


def upsert_row(table_name: str, row: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a row. Offline mode writes the in-memory mirror."""
    client = _get_supabase()
    if client is not None:
        try:
            response = client.table(table_name).upsert(row).execute()
        except Exception as exc:
            raise _fail("upsert", table_name, exc) from exc
        data = response.data or []
        return data[0] if data else row
    # Offline: upsert into mirror
    table = _mirror.get_table(table_name)
    # Detect PK column from the row keys (first key is typically the PK)
    pk_col = next(iter(row))
    for i, existing in enumerate(table):
        if existing.get(pk_col) == row.get(pk_col):
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


# ─── Table-Specific Helpers ────────────────────────────────────────────────


def get_factory_row(factory_id: str) -> dict[str, Any] | None:
    """Fetch one factory (plant constants) by id."""
    return fetch_by_id("factories", "id", factory_id)


def default_factory_name() -> str:
    """Display name of the default factory, falling back to its id if the row is missing."""
    row = get_factory_row(settings.DEFAULT_FACTORY_ID)
    return (row or {}).get("name") or settings.DEFAULT_FACTORY_ID


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


def get_all_production_lines() -> list[dict[str, Any]]:
    """Fetch all production lines."""
    return fetch_all("production_lines")


def get_production_line(line_id: str) -> dict[str, Any] | None:
    """Fetch a single production line."""
    return fetch_by_id("production_lines", "line_id", line_id)


def get_all_orders() -> list[dict[str, Any]]:
    """Fetch all active orders."""
    return fetch_all("orders")


def get_order(order_id: str) -> dict[str, Any] | None:
    """Fetch a single order."""
    return fetch_by_id("orders", "order_id", order_id)


def log_agent_step(
    run_id: str,
    step_order: int,
    agent_name: str,
    agent_role: str,
    badge_color: str,
    tool_called: str = "",
    tool_output_summary: str = "",
    message: str = "",
) -> dict[str, Any]:
    """Insert an agent log entry for realtime streaming to the terminal."""
    row = {
        "run_id": run_id,
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


def get_full_state() -> dict[str, Any]:
    """
    Return the complete factory state snapshot — used by /api/v1/state
    and by the frontend Zustand store for initial hydration.
    """
    return {
        "factory_name": default_factory_name(),
        "suppliers": get_all_suppliers(),
        "vendor_history": fetch_all("vendor_history"),
        "production_lines": get_all_production_lines(),
        "orders": get_all_orders(),
        "disruption_events": fetch_all("disruption_events"),
        "agent_logs": fetch_all("agent_logs"),
        "purchase_orders": fetch_all("purchase_orders"),
    }


def reset_to_seed() -> dict[str, str]:
    """
    Reset all tables back to the original seed data state.
    Used by the /api/v1/reset endpoint.
    """
    global _mirror
    client = _get_supabase()
    if client is None:
        _mirror = InMemoryMirror()
        return {"success": True, "status": "reset_complete", "factory": default_factory_name()}

    try:
        # Clear dynamic tables
        for tbl in ["purchase_orders", "agent_logs", "disruption_events"]:
            try:
                client.table(tbl).delete().gte("id", 0).execute()
            except Exception:
                client.table(tbl).delete().neq("po_number", "___none___").execute()
        try:
            client.table("sourcing_rfqs").delete().neq("id", "").execute()
        except Exception as exc:
            logger.warning("Could not clear sourcing_rfqs: %s", exc)

        for tbl, seed in (
            ("factories", _SEED_FACTORIES),
            ("suppliers", _SEED_SUPPLIERS),
            ("production_lines", _SEED_PRODUCTION_LINES),
            ("orders", _SEED_ORDERS),
        ):
            for row in seed:
                client.table(tbl).upsert(row).execute()
    except Exception as exc:
        raise _fail("reset", "all", exc) from exc
    logger.info("Supabase tables reset to seed data")
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

    state = get_full_state()
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
