"""Pure domain model for a factory: vendors, production lines and derived quantities."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional


class FactoryDataError(ValueError):
    """Raised when factory data or a request refers to something the model does not contain."""


@dataclass(frozen=True)
class Vendor:
    supplier_id: str
    name: str
    tier: str
    route: str
    max_units: int
    unit_cost: int
    flat_cost: int
    lead_hours: float
    lead_sigma: float
    delay_shock_pct: float
    delay_shock_range: tuple[float, float]
    reliability_pct: float
    unreliability_delay_range: tuple[float, float]
    min_lead_hours: float
    sourcing_role: str


@dataclass(frozen=True)
class ProductionLine:
    line_id: str
    name: str
    rated_units_per_hour: float
    ot_units_per_hour: int
    ot_cost_per_hour: int
    max_ot_hours: int


@dataclass(frozen=True)
class FactoryModel:
    factory_id: str
    name: str
    stock_item_name: str
    qa_dispatch_hours: float
    safety_stock_units: int
    production_hours_in_window: float
    vendors: tuple[Vendor, ...]
    lines: tuple[ProductionLine, ...]

    def vendor(self, supplier_id: str) -> Vendor:
        for v in self.vendors:
            if v.supplier_id == supplier_id:
                return v
        raise FactoryDataError(f"Unknown supplier id: {supplier_id}")

    @property
    def expedite_vendor_id(self) -> Optional[str]:
        for v in self.vendors:
            if v.sourcing_role == "EXPEDITE":
                return v.supplier_id
        return None

    @property
    def overtime_lines(self) -> tuple[ProductionLine, ...]:
        return tuple(l for l in self.lines if l.ot_units_per_hour > 0 and l.max_ot_hours > 0)

    def throughput_gap(self, line_speeds: Mapping[str, int]) -> int:
        by_id = {l.line_id: l for l in self.lines}
        total = 0.0
        for line_id, speed in line_speeds.items():
            line = by_id.get(line_id)
            if line is None:
                raise FactoryDataError(f"Unknown line id: {line_id}")
            frac = min(max(speed, 0), 100) / 100
            total += line.rated_units_per_hour * (1 - frac) * self.production_hours_in_window
        return math.ceil(total - 1e-9)

    def with_vendor_overrides(
        self, overrides: Optional[Mapping[str, Mapping[str, Any]]]
    ) -> "FactoryModel":
        """Apply per-run vendor overrides (keys: max_units, unit_cost, flat_cost, lead_hours).
        max_units <= 0 drops the vendor. Unknown supplier ids raise FactoryDataError."""
        if not overrides:
            return self
        known = {v.supplier_id for v in self.vendors}
        unknown = sorted(set(overrides) - known)
        if unknown:
            raise FactoryDataError(f"Overrides for unknown supplier(s): {', '.join(unknown)}")
        out = []
        for v in self.vendors:
            o = overrides.get(v.supplier_id)
            if o is None:
                out.append(v)
                continue
            max_units = int(o.get("max_units", v.max_units))
            if max_units <= 0:
                continue
            out.append(replace(
                v,
                max_units=max_units,
                unit_cost=int(o.get("unit_cost", v.unit_cost)),
                flat_cost=int(o.get("flat_cost", v.flat_cost)),
                lead_hours=float(o.get("lead_hours", v.lead_hours)),
            ))
        return replace(self, vendors=tuple(out))
