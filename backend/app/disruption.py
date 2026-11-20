"""Resolve free-text disruption references against the factory model.

Unknown or ambiguous references fail loudly (DisruptionResolutionError, a
SolverInputError) instead of silently defaulting to demo values.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from app.factory_model import FactoryModel
from app.schemas import DisruptionExtraction
from app.solver import SolverInputError


class DisruptionResolutionError(SolverInputError):
    """A disruption reference could not be mapped to the factory model."""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _forms(cid: str, name: str) -> set:
    """Normalised id, full name, and the name stem before ' ('."""
    stem = name.split(" (")[0]
    return {f for f in (_norm(cid), _norm(name), _norm(stem)) if f}


def _name_forms(name: str) -> set:
    return {f for f in (_norm(name), _norm(name.split(" (")[0])) if f}


def resolve_reference(text: str, candidates: Mapping[str, str], kind: str) -> str:
    t = _norm(text)
    forms = {cid: _forms(cid, name) for cid, name in candidates.items()}

    def ambiguous(ids) -> DisruptionResolutionError:
        return DisruptionResolutionError(
            f"Ambiguous {kind} '{text}': matches {', '.join(sorted(ids))}")

    if t:
        exact = [cid for cid, f in forms.items() if t in f]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise ambiguous(exact)

        sub = []
        if len(t) >= 3 and re.search(r"[a-z]", t):
            sub = [cid for cid, f in forms.items() if any(t in x for x in f)]
        if len(sub) == 1:
            return sub[0]
        if len(sub) > 1:
            raise ambiguous(sub)

        by_norm: dict = {}
        for cid, name in candidates.items():
            for x in _name_forms(name):  # fuzzy matching on names only, never ids
                by_norm.setdefault(x, set()).add(cid)
                # a typo'd partial name ("chenai precision") is compared with same-length
                # windows of the name, so it need not be spelled out in full
                for n in (len(t), len(t) + 1):
                    for i in range(0, max(len(x) - n, 0) + 1):
                        if n >= 3 and n < len(x):
                            by_norm.setdefault(x[i:i + n], set()).add(cid)
        close = difflib.get_close_matches(t, list(by_norm), n=10, cutoff=0.85)
        ids = {cid for x in close for cid in by_norm[x]}
        if len(ids) == 1:
            return next(iter(ids))
        if len(ids) > 1:
            raise ambiguous(ids)

    known = ", ".join(f"{cid} ({name})" for cid, name in candidates.items())
    raise DisruptionResolutionError(f"Unknown {kind} '{text}'. Known: {known}")


@dataclass(frozen=True)
class LineImpact:
    line_id: str
    speed_pct: int
    temp_celsius: Optional[float] = None


@dataclass(frozen=True)
class DisruptionOverrides:
    delay_hours: Optional[int] = None
    shortfall_units: Optional[int] = None
    line_speeds: Optional[Mapping[str, int]] = None
    order_id: Optional[str] = None


@dataclass(frozen=True)
class ResolvedDisruption:
    delay_hours: int
    line_impacts: tuple
    supplier_id: Optional[str]
    order_id: str
    shortfall_units: int
    headline: str

    @property
    def line_speeds(self) -> dict:
        return {li.line_id: li.speed_pct for li in self.line_impacts}

    def to_dict(self) -> dict:
        return {
            "delay_hours": self.delay_hours,
            "line_impacts": [
                {"line_id": li.line_id, "speed_pct": li.speed_pct,
                 "temp_celsius": li.temp_celsius}
                for li in self.line_impacts
            ],
            "supplier_id": self.supplier_id,
            "order_id": self.order_id,
            "shortfall_units": self.shortfall_units,
            "headline": self.headline,
        }


def _check_speed(line_id: str, speed: Any) -> int:
    if isinstance(speed, bool) or not isinstance(speed, int) or not 0 <= speed <= 100:
        raise DisruptionResolutionError(
            f"speed for line {line_id} must be an integer 0..100, got {speed!r}")
    return speed


def resolve_disruption(
    extraction: DisruptionExtraction,
    model: FactoryModel,
    order_ids: Sequence[str],
    overrides: Optional[DisruptionOverrides] = None,
) -> ResolvedDisruption:
    ov = overrides or DisruptionOverrides()
    line_names = {l.line_id: l.name for l in model.lines}
    primaries = dict(model.primary_suppliers)
    vendor_names = {**primaries, **{v.supplier_id: v.name for v in model.vendors}}

    delay = ov.delay_hours if ov.delay_hours is not None else extraction.delay_hours
    if delay is None:
        delay = 0
    if delay < 0:
        raise DisruptionResolutionError(f"delay_hours must be >= 0, got {delay}")

    shortfall = ov.shortfall_units if ov.shortfall_units is not None else extraction.shortfall_units
    if shortfall is None:
        raise DisruptionResolutionError("shortfall_units not stated")
    if shortfall < 0:
        raise DisruptionResolutionError(f"shortfall_units must be >= 0, got {shortfall}")

    impacts = []
    if ov.line_speeds is not None:
        for lid, speed in ov.line_speeds.items():
            if lid not in line_names:
                known = ", ".join(f"{i} ({n})" for i, n in line_names.items())
                raise DisruptionResolutionError(f"Unknown line '{lid}'. Known: {known}")
            impacts.append(LineImpact(lid, _check_speed(lid, speed), None))
    else:
        seen = set()
        for item in extraction.affected_lines:
            lid = resolve_reference(item.line, line_names, "line")
            if lid in seen:
                raise DisruptionResolutionError(f"line {lid} named more than once")
            seen.add(lid)
            if item.speed_pct is None:
                raise DisruptionResolutionError(f"speed for line {lid} not stated")
            impacts.append(LineImpact(lid, _check_speed(lid, item.speed_pct), item.temp_celsius))

    order_map = {o: o for o in order_ids}
    if ov.order_id:
        order_id = resolve_reference(ov.order_id, order_map, "order")
    elif extraction.affected_order:
        order_id = resolve_reference(extraction.affected_order, order_map, "order")
    elif len(order_ids) == 1:
        order_id = order_ids[0]
    else:
        raise DisruptionResolutionError(
            "order not stated; known orders: " + ", ".join(order_ids))

    if extraction.affected_supplier:
        supplier_id = resolve_reference(extraction.affected_supplier, vendor_names, "supplier")
    elif delay > 0:
        if len(primaries) != 1:
            known = ", ".join(f"{i} ({n})" for i, n in vendor_names.items())
            raise DisruptionResolutionError(
                f"name the delayed supplier: no single PRIMARY vendor. Known: {known}")
        supplier_id = next(iter(primaries))
    else:
        supplier_id = None

    headline = (extraction.crisis_headline or "").strip()
    if not headline:
        parts = []
        if supplier_id and delay > 0:
            parts.append(f"{vendor_names[supplier_id].split(' (')[0]} +{delay}h")
        for li in impacts:
            parts.append(f"{line_names[li.line_id]} at {li.speed_pct}%")
        parts.append(f"{shortfall} short on #{order_id}")
        headline = "; ".join(parts)

    return ResolvedDisruption(delay, tuple(impacts), supplier_id, order_id, shortfall, headline)
