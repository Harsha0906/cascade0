"""Shared test fixtures: a second, non-demo factory."""

from tests import _offline_env  # noqa: F401  (must precede any app import)

from datetime import datetime, timezone

from app.factory_model import FactoryModel, ProductionLine, Vendor


def _vendor(supplier_id, role, max_units, unit_cost, flat_cost, lead_hours, reliability_pct):
    return Vendor(
        supplier_id, f"Vendor {supplier_id}", "TIER-2", "Test route",
        max_units, unit_cost, flat_cost, lead_hours, 0.5, 5.0, (1.0, 2.0),
        reliability_pct, (1.0, 2.0), 1.0, role,
    )


def small_factory() -> FactoryModel:
    return FactoryModel(
        factory_id="test-plant",
        name="Test Plant",
        stock_item_name="Widget",
        stock_item_code="ITEM-W",
        qa_dispatch_hours=2.0,
        safety_stock_units=30,
        production_hours_in_window=10.0,
        vendors=(
            _vendor("V1", "BACKUP", 100, 500, 0, 4, 90),
            _vendor("V2", "BACKUP", 200, 900, 0, 6, 85),
            _vendor("V3", "EXPEDITE", 300, 0, 200_000, 3, 99),
        ),
        lines=(
            ProductionLine("L-A", "Line A", 10.0, 0, 0, 0),
            ProductionLine("L-B", "Line B", 10.0, 20, 5000, 6),
        ),
    )


def seed_second_factory() -> None:
    """Insert the `test-plant` factory (equivalent to small_factory()) into the offline mirror.

    Callers must `db.reset_to_seed()` in tearDown so the rows do not leak into other tests."""
    from app import db

    db.insert_row("factories", {
        "id": "test-plant", "name": "Test Plant", "stock_item_name": "Widget",
        "stock_item_code": "ITEM-W", "qa_dispatch_hours": 2.0, "safety_stock_units": 30, "production_hours_in_window": 10.0,
    })
    for sid, role, max_units, unit_cost, flat, lead, rel in (
        ("V1", "BACKUP", 100, 500, 0, 4, 90),
        ("V2", "BACKUP", 200, 900, 0, 6, 85),
        ("V3", "EXPEDITE", 300, 0, 200_000, 3, 99),
    ):
        db.insert_row("suppliers", {
            "id": sid, "name": f"Vendor {sid}", "tier": "TIER-2", "route": "Test route",
            "part_name": "Widget", "inbound_qty": 0, "max_available_qty": max_units,
            "extra_cost_per_unit_inr": unit_cost, "flat_charter_cost_inr": flat,
            "lead_time_hours": lead, "traffic_risk_pct": 5.0, "weather_risk_pct": 0.0,
            "status": "STANDBY", "delay_hours": 0, "whatsapp_number": "",
            "factory_id": "test-plant", "sourcing_role": role,
            "lead_time_sigma_hours": 0.5, "delay_shock_min_hours": 1.0,
            "delay_shock_max_hours": 2.0, "unreliable_delay_min_hours": 1.0,
            "unreliable_delay_max_hours": 2.0, "min_lead_hours": 1.0,
        })
        db.insert_row("vendor_history", {
            "supplier_id": sid, "past_orders_count": 10, "on_time_deliveries": 9,
            "reliability_score_pct": float(rel), "quality_rejection_rate_pct": 0.5,
        })
    for lid, name, ot_units, ot_cost, max_ot in (
        ("L-A", "Line A", 0, 0, 0), ("L-B", "Line B", 20, 5000, 6),
    ):
        db.insert_row("production_lines", {
            "line_id": lid, "name": name, "status": "NORMAL", "speed_pct": 100,
            "temp_celsius": 60.0, "daily_capacity_units": 100,
            "overtime_cost_per_hour_inr": ot_cost, "extra_units_per_ot_hour": ot_units,
            "max_ot_hours": max_ot, "factory_id": "test-plant", "rated_units_per_hour": 10.0,
        })
    db.insert_row("orders", {
        "order_id": "WO-77", "client": "Test Client", "required_qty": 100,
        "deadline_label": "30 hours", "hours_remaining": 30, "sla_penalty_inr": 400_000,
        "partial_delay_penalty_inr": 80_000, "status": "ON_TRACK", "shortfall_units": 0,
        "factory_id": "test-plant", "priority": 100,
    })
    db.insert_row("items", {"factory_id": "test-plant", "item_code": "ITEM-W", "name": "Widget", "unit": "pcs"})
    db.insert_row("stock_levels", {
        "factory_id": "test-plant", "item_code": "ITEM-W", "on_hand_qty": 40,
        "as_of": datetime.now(timezone.utc).isoformat(),
    })
    db.insert_row("order_lines", {"order_id": "WO-77", "item_code": "ITEM-W", "qty": 80})
