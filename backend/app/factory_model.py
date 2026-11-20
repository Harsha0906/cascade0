"""Pure domain model for a factory: vendors, production lines and derived quantities."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Optional

from app.config import settings
from app.db import fetch_all, get_all_production_lines, get_all_suppliers, get_factory_row


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
    stock_item_code: str
    qa_dispatch_hours: float
    safety_stock_units: int
    production_hours_in_window: float
    vendors: tuple[Vendor, ...]
    lines: tuple[ProductionLine, ...]
    # (supplier_id, name) of PRIMARY suppliers: the disrupted inbound source, not in `vendors`.
    primary_suppliers: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation (tuples become lists)."""
        return json.loads(json.dumps(asdict(self)))

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "FactoryModel":
        def vendor(v: Mapping[str, Any]) -> Vendor:
            v = dict(v)
            v["delay_shock_range"] = tuple(v["delay_shock_range"])
            v["unreliability_delay_range"] = tuple(v["unreliability_delay_range"])
            return Vendor(**v)

        d = dict(d)
        # Run payloads saved before Phase 4 lack the code; only from_dict tolerates that.
        d.setdefault("stock_item_code", "")
        d["vendors"] = tuple(vendor(v) for v in d["vendors"])
        d["lines"] = tuple(ProductionLine(**l) for l in d["lines"])
        d["primary_suppliers"] = tuple(tuple(x) for x in d.get("primary_suppliers", ()))
        return cls(**d)

    def vendor(self, supplier_id: str) -> Vendor:
        for v in self.vendors:
            if v.supplier_id == supplier_id:
                return v
        raise FactoryDataError(f"Unknown supplier id: {supplier_id}")

    @property
    def expedite_vendor_id(self) -> Optional[str]:
        """The first EXPEDITE vendor by supplier id (vendors are kept sorted by id), or None."""
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


# ─── Loader ────────────────────────────────────────────────────────────────

_MIGRATION_HINT = "apply supabase/migrations/003_factory_model.sql"
_INVENTORY_MIGRATION_HINT = "apply supabase/migrations/006_inventory.sql"
_VALID_ROLES = ("PRIMARY", "BACKUP", "EXPEDITE")


class _Problems:
    """Collects every data problem so one FactoryDataError can report them all."""

    def __init__(self) -> None:
        self.items: list[str] = []
        self._missing: set[str] = set()

    def add(self, msg: str) -> None:
        if msg not in self.items:
            self.items.append(msg)

    def missing(self, table: str, column: str, hint: str = _MIGRATION_HINT) -> None:
        key = f"{table}.{column}"
        if key not in self._missing:
            self._missing.add(key)
            self.items.append(f"{key} missing — {hint}")


def _num(row: Mapping[str, Any], table: str, column: str, label: str, p: _Problems,
         *, minimum: Optional[float] = None, maximum: Optional[float] = None,
         strictly_positive: bool = False) -> Optional[float]:
    """Read a numeric column; record a problem and return None if absent or invalid."""
    value = row.get(column)
    if value is None:
        p.missing(table, column)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        p.add(f"{label}: {table}.{column} must be a finite number, got {value!r}")
        return None
    if strictly_positive and value <= 0:
        p.add(f"{label}: {table}.{column} must be > 0, got {value}")
        return None
    if minimum is not None and value < minimum:
        p.add(f"{label}: {table}.{column} must be >= {minimum:g}, got {value}")
        return None
    if maximum is not None and value > maximum:
        p.add(f"{label}: {table}.{column} must be <= {maximum:g}, got {value}")
        return None
    return float(value)


def _range(lo: Optional[float], hi: Optional[float], label: str, name: str,
           p: _Problems) -> Optional[tuple[float, float]]:
    if lo is None or hi is None:
        return None
    if lo > hi:
        p.add(f"{label}: {name} min ({lo:g}) exceeds max ({hi:g})")
        return None
    return (lo, hi)


def _load_vendor(row: Mapping[str, Any], history: Optional[Mapping[str, Any]],
                 p: _Problems) -> Optional[Vendor]:
    sid = row.get("id")
    label = f"supplier {sid}"
    t = "suppliers"
    max_units = _num(row, t, "max_available_qty", label, p, minimum=0)
    unit_cost = _num(row, t, "extra_cost_per_unit_inr", label, p, minimum=0)
    flat_cost = _num(row, t, "flat_charter_cost_inr", label, p, minimum=0)
    lead = _num(row, t, "lead_time_hours", label, p, strictly_positive=True)
    sigma = _num(row, t, "lead_time_sigma_hours", label, p, minimum=0)
    traffic = _num(row, t, "traffic_risk_pct", label, p, minimum=0, maximum=100)
    weather = _num(row, t, "weather_risk_pct", label, p, minimum=0, maximum=100)
    s_min = _num(row, t, "delay_shock_min_hours", label, p, minimum=0)
    s_max = _num(row, t, "delay_shock_max_hours", label, p, minimum=0)
    u_min = _num(row, t, "unreliable_delay_min_hours", label, p, minimum=0)
    u_max = _num(row, t, "unreliable_delay_max_hours", label, p, minimum=0)
    min_lead = _num(row, t, "min_lead_hours", label, p, strictly_positive=True)

    shock_pct = None
    if traffic is not None and weather is not None:
        shock_pct = traffic + weather
        if shock_pct > 100:
            p.add(f"{label}: traffic_risk_pct + weather_risk_pct must be <= 100, got {shock_pct:g}")
            shock_pct = None
    shock_range = _range(s_min, s_max, label, "delay_shock", p)
    unrel_range = _range(u_min, u_max, label, "unreliable_delay", p)

    reliability = None
    if history is None:
        p.add(f"{label}: no vendor_history row (required for BACKUP/EXPEDITE vendors)")
    else:
        reliability = _num(history, "vendor_history", "reliability_score_pct", label, p,
                           minimum=0, maximum=100)

    text_ok = True
    for col in ("name", "tier", "route"):
        if not row.get(col):
            p.missing(t, col)
            text_ok = False
    parts = (max_units, unit_cost, flat_cost, lead, sigma, shock_pct, shock_range,
             reliability, unrel_range, min_lead)
    if not text_ok or any(x is None for x in parts):
        return None
    return Vendor(
        supplier_id=sid, name=row["name"], tier=row["tier"], route=row["route"],
        max_units=int(round(max_units)), unit_cost=int(round(unit_cost)),
        flat_cost=int(round(flat_cost)), lead_hours=lead, lead_sigma=sigma,
        delay_shock_pct=shock_pct, delay_shock_range=shock_range,
        reliability_pct=reliability, unreliability_delay_range=unrel_range,
        min_lead_hours=min_lead, sourcing_role=row["sourcing_role"],
    )


def _load_line(row: Mapping[str, Any], p: _Problems) -> Optional[ProductionLine]:
    label = f"production line {row.get('line_id')}"
    t = "production_lines"
    rated = _num(row, t, "rated_units_per_hour", label, p, minimum=0)
    ot_units = _num(row, t, "extra_units_per_ot_hour", label, p, minimum=0)
    ot_cost = _num(row, t, "overtime_cost_per_hour_inr", label, p, minimum=0)
    max_ot = _num(row, t, "max_ot_hours", label, p, minimum=0)
    if not row.get("name"):
        p.missing(t, "name")
    if any(x is None for x in (rated, ot_units, ot_cost, max_ot)) or not row.get("name"):
        return None
    return ProductionLine(
        line_id=row["line_id"], name=row["name"], rated_units_per_hour=rated,
        ot_units_per_hour=int(round(ot_units)), ot_cost_per_hour=int(round(ot_cost)),
        max_ot_hours=int(round(max_ot)),
    )


def load_factory_model(factory_id: Optional[str] = None) -> FactoryModel:
    """Build a validated FactoryModel from the database (or the offline mirror).

    All problems found are collected into a single FactoryDataError. PRIMARY suppliers are
    the disrupted inbound source and are excluded from the model's vendors."""
    factory_id = factory_id or settings.DEFAULT_FACTORY_ID
    frow = get_factory_row(factory_id)
    if frow is None:
        raise FactoryDataError(
            f"Unknown factory id: {factory_id} (no row in factories — {_MIGRATION_HINT})")

    p = _Problems()
    label = f"factory {factory_id}"
    name = frow.get("name")
    stock_item = frow.get("stock_item_name")
    stock_code = frow.get("stock_item_code")
    for col, val in (("name", name), ("stock_item_name", stock_item)):
        if not val:
            p.missing("factories", col)
    if not stock_code:
        p.missing("factories", "stock_item_code", _INVENTORY_MIGRATION_HINT)
    qa = _num(frow, "factories", "qa_dispatch_hours", label, p, minimum=0)
    safety = _num(frow, "factories", "safety_stock_units", label, p, minimum=0)
    window = _num(frow, "factories", "production_hours_in_window", label, p, strictly_positive=True)

    history = {h.get("supplier_id"): h for h in fetch_all("vendor_history")}

    vendors: list[Vendor] = []
    primaries: list[tuple[str, str]] = []
    for row in get_all_suppliers():
        if row.get("factory_id") is None:
            p.missing("suppliers", "factory_id")
            continue
        if row["factory_id"] != factory_id:
            continue
        role = row.get("sourcing_role")
        if role is None:
            p.missing("suppliers", "sourcing_role")
            continue
        if role not in _VALID_ROLES:
            p.add(f"supplier {row.get('id')}: suppliers.sourcing_role must be one of "
                  f"{', '.join(_VALID_ROLES)}, got {role!r}")
            continue
        if role == "PRIMARY":
            primaries.append((row["id"], row.get("name") or row["id"]))
            continue
        v = _load_vendor(row, history.get(row.get("id")), p)
        if v is not None:
            vendors.append(v)

    lines: list[ProductionLine] = []
    for row in get_all_production_lines():
        if row.get("factory_id") is None:
            p.missing("production_lines", "factory_id")
            continue
        if row["factory_id"] != factory_id:
            continue
        ln = _load_line(row, p)
        if ln is not None:
            lines.append(ln)

    if p.items:
        raise FactoryDataError(f"Invalid factory data for {factory_id}: " + "; ".join(p.items))
    return FactoryModel(
        factory_id=factory_id, name=name, stock_item_name=stock_item,
        stock_item_code=stock_code,
        qa_dispatch_hours=qa, safety_stock_units=int(round(safety)),
        production_hours_in_window=window,
        # Sorted so the expedite choice and MILP tie-breaks never depend on database row order.
        vendors=tuple(sorted(vendors, key=lambda v: v.supplier_id)),
        lines=tuple(sorted(lines, key=lambda l: l.line_id)),
        primary_suppliers=tuple(sorted(primaries)),
    )
