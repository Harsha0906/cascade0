"""
CascadeZero — Autonomous Agent Tools
Defines tools bound to the 4 LangGraph agents:
  1. extract_disruption_entities (Gemini structured extraction + regex fallback; reports which ran)
  2. query_blast_radius_sql (Supabase blast-radius calculation & state updates)
  3. run_pulp_milp_and_monte_carlo (Arbitrator PuLP MILP solver & Monte Carlo engine)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Mapping, Optional, Sequence

from app.config import settings
from app.db import (
    fetch_all,
    get_all_orders,
    get_all_production_lines,
    get_all_suppliers,
    get_order,
    update_rows,
    upsert_row,
)
from app.schemas import DisruptionExtraction, LineImpactExtraction
from app.disruption import DisruptionResolutionError, ResolvedDisruption, resolve_reference
from app.factory_model import FactoryModel
from app.solver import generate_playbooks

logger = logging.getLogger("cascadezero.tools")


# ─── 1. Disruption Entity Extraction (Gemini Structured Outputs) ─────────────

def _single_char_tail(chunks: list[str]) -> str:
    """Join chunks; a final single LETTER must match as an uppercase letter (not 'la la', 'line a bit')."""
    esc = [re.escape(c) for c in chunks]
    if len(chunks[-1]) == 1 and chunks[-1].isalpha():
        esc[-1] = rf"(?-i:{re.escape(chunks[-1].upper())})"
    return esc


def _mention_pattern(ident: str) -> str:
    """Regex for an id like 'LINE-2' with flexible separators ('line 2', 'Line-2', 'line2')."""
    chunks = re.findall(r"[A-Za-z0-9]+", ident)
    body = r"[\s\-_]?".join(_single_char_tail(chunks))
    return rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"


def _name_pattern(name: str) -> str:
    words = [re.sub(r"[^A-Za-z0-9]", "", w) or w for w in name.split()]
    body = r"\s+".join(_single_char_tail(words))
    return rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"


_TEMP_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:°\s*c\b|deg(?:rees)?\b|celsius\b|c\b)", re.I)
_SPEED_CUE_RE = re.compile(
    r"\b(?:at|to)\s*(\d{1,3})\s*%(?!\s*of\b)|(\d{1,3})\s*%\s*(?:speed|capacity)\b", re.I)
_HOURS = r"(?:h|hr|hrs|hours?)\b"
_DELAY_CUE_RES = (
    re.compile(rf"(\d+)\s*{_HOURS}\s*(?:of\s+)?delay", re.I),
    re.compile(rf"delay(?:ed)?\s*(?:by|of|:)?\s*(\d+)\s*{_HOURS}", re.I),
    re.compile(rf"\+\s*(\d+)\s*{_HOURS}", re.I),
)
_SHORT_CUE_RES = (
    re.compile(r"\b(?:shortfall|deficit|missing)\s*(?:is|of|:)?\s*(\d+)", re.I),
    re.compile(r"\b(\d+)\s*(?:[A-Za-z]+\s+){0,3}?(?:short|missing)\b", re.I),
    re.compile(r"\bshort(?!fall)\s*(?:by|of)?\s*(\d+)", re.I),
)
_SUPPLIER_DELAY_CUE_RE = re.compile(r"\b(?:delay(?:ed)?|late|blocked|stuck|held)\b", re.I)
_LINE_MENTION_RE = re.compile(r"\bline[\s\-_]*([A-Za-z0-9]{1,6})\b", re.I)
_ORDER_MENTION_RE = re.compile(r"(?:\border\b\s*#?|#)\s*([A-Za-z]{1,6}-?\d{1,6})\b", re.I)
_ORDER_ON_RE = re.compile(r"\b(?:on|for)\s+([A-Za-z]{1,6}-\d{1,6})\b", re.I)
_SUPPLIER_MENTION_RE = re.compile(
    r"(?i:supplier|vendor)\s+([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*){0,3})")
_WINDOW_CHARS = 80
_SUPPLIER_CUE_CHARS = 60


def _cue_values(regexes, text: str) -> set:
    return {int(g) for rx in regexes for m in rx.finditer(text) for g in m.groups() if g}


def _regex_extract(raw_text: str, model: FactoryModel, order_ids: Sequence[str]) -> DisruptionExtraction:
    text = raw_text

    # Delay: a number bound to a delay cue; else the only hours number; else unknown.
    vals = _cue_values(_DELAY_CUE_RES, text)
    if not vals:
        vals = {int(x) for x in re.findall(rf"(\d+)\s*{_HOURS}", text, re.I)}
    delay_hours = next(iter(vals)) if len(vals) == 1 else None

    # Shortfall: a number bound to a shortfall cue; else the only units-count number; else unknown.
    vals = _cue_values(_SHORT_CUE_RES, text)
    if not vals:
        item_words = re.findall(r"[A-Za-z]+", model.stock_item_name or "")
        units = [r"battery\s+casings", r"casings", r"units", r"pcs", r"u\b"]
        if item_words:
            units.append(rf"{re.escape(item_words[-1])}s?\b")
        vals = {int(x) for x in re.findall(r"\b(\d+)\s*(?:" + "|".join(units) + r")", text, re.I)}
    shortfall = next(iter(vals)) if len(vals) == 1 else None

    # Line mentions (id or full name), overlapping spans collapsed to the earliest/longest.
    spans = []
    for line in model.lines:
        for pat in (_mention_pattern(line.line_id), _name_pattern(line.name)):
            for mm in re.finditer(pat, text, re.I):
                spans.append((mm.start(), mm.end(), line.line_id))
    spans.sort(key=lambda s: (s[0], -s[1]))
    kept = []
    for s in spans:
        if kept and s[0] < kept[-1][1]:
            continue
        kept.append(s)

    speeds: dict[str, set] = {}
    temps: dict[str, Optional[float]] = {}
    for i, (_, end, lid) in enumerate(kept):
        stop = min(end + _WINDOW_CHARS, kept[i + 1][0] if i + 1 < len(kept) else len(text))
        window = text[end:stop]
        speeds.setdefault(lid, set())
        temps.setdefault(lid, None)
        sp = _SPEED_CUE_RE.search(window)
        if sp:
            speeds[lid].add(int(sp.group(1) or sp.group(2)))
        tm = _TEMP_RE.search(window)
        if tm and temps[lid] is None and 0 < float(tm.group(1)) < 200:
            temps[lid] = float(tm.group(1))
    # Line-shaped mentions that match no model line are emitted as-is so resolution fails loudly.
    # A token must look like an identifier (has a digit, a single capital, or is all capitals) so
    # that prose such as "line is down" or "line a bit slow" is not mistaken for a line.
    mentions = [m for m in _LINE_MENTION_RE.finditer(text)]
    for i, m in enumerate(mentions):
        tok = m.group(1)
        if any(m.start() < e and s0 < m.end() for s0, e, _ in kept):
            continue
        if not (any(c.isdigit() for c in tok) or (tok.isupper() and tok.isalpha())):
            continue
        stop = min(m.end() + _WINDOW_CHARS, mentions[i + 1].start() if i + 1 < len(mentions) else len(text))
        sp = _SPEED_CUE_RE.search(text[m.end():stop])
        speeds.setdefault(m.group(0).strip(), set())
        temps.setdefault(m.group(0).strip(), None)
        if sp:
            speeds[m.group(0).strip()].add(int(sp.group(1) or sp.group(2)))
    impacts = [
        LineImpactExtraction(
            line=lid,
            speed_pct=next(iter(sv)) if len(sv) == 1 else None,
            temp_celsius=temps[lid],
        )
        for lid, sv in speeds.items()
    ]

    # Supplier: a single mentioned supplier wins; with several, the one clearly nearest a delay cue.
    mentioned: dict[str, tuple[int, int]] = {}
    candidates = list(model.primary_suppliers) + [(v.supplier_id, v.name) for v in model.vendors]
    for sid, name in candidates:
        pats = [_mention_pattern(sid)]
        words = name.split(" (")[0].split()
        for n in range(len(words), 1, -1):
            pats.append(_name_pattern(" ".join(words[:n])))
        found = [m for pat in pats for m in re.finditer(pat, text, re.I)]
        if found:
            m0 = min(found, key=lambda m: m.start())
            mentioned[sid] = (m0.start(), max(m.end() for m in found if m.start() == m0.start()))
    supplier = None
    if len(mentioned) == 1:
        supplier = next(iter(mentioned))
    elif len(mentioned) > 1:
        cues = [(c.start(), c.end()) for c in _SUPPLIER_DELAY_CUE_RE.finditer(text)]
        dist = {}
        for sid, (st, en) in mentioned.items():
            ds = [max(cs - en, st - ce, 0) for cs, ce in cues]
            if ds and min(ds) <= _SUPPLIER_CUE_CHARS:
                dist[sid] = min(ds)
        ranked = sorted(dist.items(), key=lambda kv: kv[1])
        if ranked and (len(ranked) == 1 or ranked[0][1] < ranked[1][1]):
            supplier = ranked[0][0]

    order = None
    best = None
    for oid in order_ids:
        mm = re.search(_mention_pattern(oid), text, re.I)
        if mm and (best is None or mm.start() < best):
            best, order = mm.start(), oid

    # Order- or supplier-shaped mentions that match nothing known are emitted (fail loud).
    known_orders = {re.sub(r"[^a-z0-9]", "", o.lower()) for o in order_ids}
    other_ids = {re.sub(r"[^a-z0-9]", "", i.lower())
                 for i in [l.line_id for l in model.lines] + [sid for sid, _ in candidates]}
    for mm in [*_ORDER_MENTION_RE.finditer(text), *_ORDER_ON_RE.finditer(text)]:
        norm = re.sub(r"[^a-z0-9]", "", mm.group(1).lower())
        if norm not in known_orders and norm not in other_ids:
            order = mm.group(1)
            break

    names = {sid: nm for sid, nm in candidates}
    for mm in _SUPPLIER_MENTION_RE.finditer(text):
        words = mm.group(1).split()
        resolved = False
        for n in range(len(words), 0, -1):
            try:
                resolve_reference(" ".join(words[:n]), names, "supplier")
                resolved = True
                break
            except DisruptionResolutionError:
                continue
        if not resolved:
            supplier = mm.group(1)
            break

    return DisruptionExtraction(
        delay_hours=delay_hours,
        affected_lines=impacts,
        affected_supplier=supplier,
        affected_order=order,
        shortfall_units=shortfall,
        raw_summary=raw_text[:200],
    )


def _gemini_prompt(raw_text: str, model: FactoryModel, order_ids: Sequence[str]) -> str:
    lines = "\n".join(f"- {l.line_id} — {l.name}" for l in model.lines)
    suppliers = "\n".join(
        [f"- {sid} — {name}" for sid, name in model.primary_suppliers]
        + [f"- {v.supplier_id} — {v.name}" for v in model.vendors]
    )
    orders = ", ".join(order_ids)
    return (
        f"You are the Crisis Detection Engine for {model.name}. "
        f"Extract the disruption parameters stated in this alert:\n\n"
        f'"{raw_text}"\n\n'
        f"Production lines:\n{lines}\n\nSuppliers:\n{suppliers}\n\nOpen orders: {orders}\n\n"
        f"Refer to every line, supplier and order using exactly one of the ids listed above. "
        f"Leave a field null (or the list empty) when the alert does not state it; "
        f"never invent numbers. Report each affected line with its speed_pct and temp_celsius "
        f"only if stated, delay_hours, and shortfall_units of {model.stock_item_name}."
    )


def extract_disruption_entities(
    raw_text: str, model: FactoryModel, order_ids: Sequence[str]
) -> tuple[DisruptionExtraction, str]:
    """
    Extract structured disruption metrics from raw text (English/Hinglish/alerts), aware of the
    factory model so any line, supplier or order can be named. Gemini structured output first;
    deterministic regex fallback otherwise.

    Returns (extraction, source) where source is "gemini:<model>" or "regex-fallback".
    """
    if settings.has_gemini:
        try:
            from google import genai

            client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options={"timeout": 10000},
            )
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=_gemini_prompt(raw_text, model, order_ids),
                config={
                    "response_mime_type": "application/json",
                    "response_schema": DisruptionExtraction,
                },
            )
            if response.text:
                data = json.loads(response.text)
                return DisruptionExtraction(**data), f"gemini:{settings.GEMINI_MODEL}"
        except Exception as exc:
            logger.warning("⚠ Gemini structured extraction failed (%s) — using deterministic fail-safe", exc)

    return _regex_extract(raw_text, model, order_ids), "regex-fallback"


# ─── 2. Blast-Radius SQL Query & Realtime State Updater ──────────────────────

def query_blast_radius_sql(model: FactoryModel, disruption: ResolvedDisruption) -> Dict[str, Any]:
    """
    Computes the blast radius of a resolved disruption and writes it to the database: the delayed
    supplier, every impacted line and the order at risk. Realtime subscribers see the change.
    Everything returned about the order comes from the order row; nothing is defaulted.
    """
    order = get_order(disruption.order_id)
    if order is None:
        raise DisruptionResolutionError(f"Unknown order '{disruption.order_id}'")
    delay = disruption.delay_hours

    if disruption.supplier_id and delay > 0:
        update_rows("suppliers", "id", disruption.supplier_id, {
            "status": "DELAYED",
            "delay_hours": delay,
        })

    for li in disruption.line_impacts:
        updates: Dict[str, Any] = {
            "status": "THROTTLED" if li.speed_pct < 100 else "NORMAL",
            "speed_pct": li.speed_pct,
        }
        if li.temp_celsius is not None:
            updates["temp_celsius"] = li.temp_celsius
        update_rows("production_lines", "line_id", li.line_id, updates)

    update_rows("orders", "order_id", disruption.order_id, {
        "status": "BREACH_RISK",
        "shortfall_units": disruption.shortfall_units,
    })

    has_supply = bool(disruption.supplier_id) and delay > 0
    has_line = bool(disruption.line_impacts)
    if has_supply and has_line:
        severity = "COMPOUND"
    elif has_supply:
        severity = "SUPPLY"
    elif has_line:
        severity = "CAPACITY"
    else:
        severity = "LOW"

    return {
        "order_id": disruption.order_id,
        "client": order["client"],
        "shortfall_units": disruption.shortfall_units,
        "sla_penalty_inr": order["sla_penalty_inr"],
        "partial_delay_penalty_inr": order["partial_delay_penalty_inr"],
        "hours_remaining": order["hours_remaining"],
        "inbound_delay_hours": delay,
        "affected_supplier_id": disruption.supplier_id,
        "line_impacts": [
            {"line_id": li.line_id, "speed_pct": li.speed_pct, "temp_celsius": li.temp_celsius}
            for li in disruption.line_impacts
        ],
        "blast_radius_severity": severity,
    }


# ─── 3. Arbitrator: PuLP MILP Solver & Monte Carlo Engine ────────────────────

def run_pulp_milp_and_monte_carlo(
    model: FactoryModel,
    shortfall_units: int,
    delay_hours: int,
    line_speeds: Mapping[str, int],
    **solver_kwargs: Any,
) -> Dict[str, Any]:
    """
    Invokes the PuLP mixed-integer program and Monte Carlo simulation and
    returns the playbooks ranked by risk-adjusted expected cost.
    Keyword arguments (order_id, sla_penalty_inr, partial_penalty_inr, deadline_hours,
    client, cfo_min_vendor_reliability_pct, ...) are passed through to generate_playbooks.
    FactoryDataError propagates to the caller.
    """
    result = generate_playbooks(
        model=model,
        shortfall_units=shortfall_units,
        delay_hours=delay_hours,
        line_speeds=line_speeds,
        **solver_kwargs,
    )
    return result.model_dump()
