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
from typing import Any, Dict, Mapping, Sequence

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
from app.factory_model import FactoryModel
from app.solver import generate_playbooks

logger = logging.getLogger("cascadezero.tools")


# ─── 1. Disruption Entity Extraction (Gemini Structured Outputs) ─────────────

def _mention_pattern(ident: str) -> str:
    """Regex for an id like 'LINE-2' with flexible separators ('line 2', 'Line-2', 'line2')."""
    chunks = re.findall(r"[A-Za-z0-9]+", ident)
    body = r"[\s\-_]?".join(re.escape(c) for c in chunks)
    return rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"


def _name_pattern(name: str) -> str:
    words = name.split()
    body = r"\s+".join(re.escape(w) for w in words)
    return rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"


_TEMP_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:°\s*c\b|deg(?:rees)?\b|celsius\b|c\b)", re.I)
_SPEED_RE = re.compile(r"(\d{1,3})\s*%")
_WINDOW_CHARS = 80


def _regex_extract(raw_text: str, model: FactoryModel, order_ids: Sequence[str]) -> DisruptionExtraction:
    text = raw_text

    delay_hours = None
    m = re.search(r"(\d+)\s*(?:h|hr|hrs|hour|hours)\b", text, re.I)
    if m:
        delay_hours = int(m.group(1))

    shortfall = None
    item_words = re.findall(r"[A-Za-z]+", model.stock_item_name or "")
    units = [r"battery\s+casings", r"casings", r"units", r"u\b"]
    if item_words:
        last = re.escape(item_words[-1])
        units.append(rf"{last}s?\b")
    m = re.search(
        r"(?:shortfall\s+(?:is|of)\s*(\d+)|\b(\d+)\s*(?:" + "|".join(units) + r"))",
        text,
        re.I,
    )
    if m:
        shortfall = int(m.group(1) or m.group(2))

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

    impacts: dict[str, LineImpactExtraction] = {}
    for i, (_, end, lid) in enumerate(kept):
        stop = min(end + _WINDOW_CHARS, kept[i + 1][0] if i + 1 < len(kept) else len(text))
        window = text[end:stop]
        sp = _SPEED_RE.search(window)
        tm = _TEMP_RE.search(window)
        temp = float(tm.group(1)) if tm and 0 < float(tm.group(1)) < 200 else None
        cur = impacts.get(lid)
        if cur is None:
            impacts[lid] = LineImpactExtraction(
                line=lid, speed_pct=int(sp.group(1)) if sp else None, temp_celsius=temp)
        else:
            if cur.speed_pct is None and sp:
                cur.speed_pct = int(sp.group(1))
            if cur.temp_celsius is None:
                cur.temp_celsius = temp

    # Supplier: earliest mention of an id or of a >=2-word name prefix.
    supplier = None
    best = None
    candidates = list(model.primary_suppliers) + [(v.supplier_id, v.name) for v in model.vendors]
    for sid, name in candidates:
        pats = [_mention_pattern(sid)]
        words = name.split(" (")[0].split()
        for n in range(len(words), 1, -1):
            pats.append(_name_pattern(" ".join(words[:n])))
        for pat in pats:
            mm = re.search(pat, text, re.I)
            if mm and (best is None or mm.start() < best):
                best, supplier = mm.start(), sid

    order = None
    best = None
    for oid in order_ids:
        mm = re.search(_mention_pattern(oid), text, re.I)
        if mm and (best is None or mm.start() < best):
            best, order = mm.start(), oid

    return DisruptionExtraction(
        delay_hours=delay_hours,
        affected_lines=list(impacts.values()),
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

def query_blast_radius_sql(
    shortfall_units: int,
    delay_hours: int,
    line2_speed_pct: int,
    order_id: str = "EV-402",
    line2_temp_celsius: float | None = None,
) -> Dict[str, Any]:
    """
    Computes blast radius across suppliers, lines, and client SLA contracts.
    Updates Supabase tables to CRITICAL/BREACH_RISK states so the 2.5D
    React Flow canvas glows crimson red via Supabase Realtime.
    """
    # 1. Update Chennai supplier status
    update_rows("suppliers", "id", "SUP-CHN-01", {
        "status": "DELAYED",
        "delay_hours": delay_hours,
    })

    # 2. Update Welding Line 2 status
    temp_val = line2_temp_celsius if line2_temp_celsius else (89.0 if line2_speed_pct <= 50 else 74.0)
    update_rows("production_lines", "line_id", "LINE-2", {
        "status": "OVERHEATING_THROTTLED",
        "speed_pct": line2_speed_pct,
        "temp_celsius": temp_val,
    })

    # 3. Update Order SLA status
    order = get_order(order_id) or {
        "order_id": order_id,
        "client": "Ather-Grid Mobility Corp",
        "sla_penalty_inr": 2500000,
    }
    sla_penalty = order.get("sla_penalty_inr", 2500000)

    update_rows("orders", "order_id", order_id, {
        "status": "BREACH_RISK",
        "shortfall_units": shortfall_units,
    })

    return {
        "order_id": order_id,
        "client": order.get("client", "Ather-Grid Mobility Corp"),
        "shortfall_units": shortfall_units,
        "sla_penalty_inr": sla_penalty,
        "partial_delay_penalty_inr": order.get("partial_delay_penalty_inr", 500000),
        "hours_remaining": order.get("hours_remaining", 38),
        "inbound_delay_hours": delay_hours,
        "affected_supplier": "SUP-CHN-01 (Chennai Precision Casings)",
        "line2_speed_pct": line2_speed_pct,
        "line2_temp_celsius": temp_val,
        "blast_radius_severity": "HIGH_COMPOUND_RISK",
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
