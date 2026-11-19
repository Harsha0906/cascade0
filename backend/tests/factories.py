"""Shared test fixtures: a second, non-demo factory."""

from tests import _offline_env  # noqa: F401  (must precede any app import)

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
