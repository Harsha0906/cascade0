"""
CascadeZero — Autonomous Agent Tools
Defines tools bound to the 4 LangGraph agents:
  1. extract_disruption_entities (Gemini structured extraction + regex fallback; reports which ran)
  2. query_blast_radius_sql (Supabase blast-radius calculation & state updates)
  3. check_air_charter_and_max_overtime (Ops Hawk air & overtime capacity query)
  4. query_regional_vendors_and_memory (CFO Watchdog regional vendors + episodic memory)
  5. run_pulp_milp_and_monte_carlo (Arbitrator PuLP MILP solver & Monte Carlo engine)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from app.config import settings
from app.db import (
    fetch_all,
    get_all_orders,
    get_all_production_lines,
    get_all_suppliers,
    get_order,
    get_supplier,
    get_vendor_history,
    update_rows,
    upsert_row,
)
from app.schemas import DisruptionExtraction
from app.solver import generate_playbooks

logger = logging.getLogger("cascadezero.tools")


# ─── 1. Disruption Entity Extraction (Gemini Structured Outputs) ─────────────

def extract_disruption_entities(raw_text: str) -> tuple[DisruptionExtraction, str]:
    """
    Extract structured disruption metrics from raw text (English/Hinglish/alerts)
    using Gemini with Pydantic Structured Outputs (response_schema).
    Falls back to deterministic regex extraction if the API is unavailable.

    Returns (extraction, source) where source is "gemini:<model>" or "regex-fallback",
    so callers can show users which path actually produced the numbers.
    """
    if settings.has_gemini:
        try:
            from google import genai

            client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options={"timeout": 10000},
            )
            prompt = (
                f"You are the Crisis Detection Engine for Apex Volt EV Battery Plant. "
                f"Extract the exact crisis parameters from this disruption alert:\n\n"
                f'"{raw_text}"\n\n'
                f"If specific numbers are omitted, infer sensible manufacturing defaults: "
                f"delay_hours (default 48), line2_speed_pct (default 50), line2_temp_celsius (default 89.0), "
                f"shortfall_units (default 150), affected_order_id (default EV-402)."
            )

            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
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

    # Deterministic Rule-Based Fallback
    text = raw_text.lower()
    delay_hours = 48
    line2_speed = 50
    temp_c = 89.0
    shortfall = 150

    # Parse delay hours
    delay_match = re.search(r"(\d+)\s*(?:h|hr|hrs|hour|hours)", text, re.I)
    if delay_match:
        delay_hours = int(delay_match.group(1))

    # Parse speed %
    speed_match = re.search(r"(\d+)\s*%", text)
    if speed_match:
        line2_speed = int(speed_match.group(1))

    # Parse temp
    # Require a real temperature unit ("89°C", "89 deg", "89 celsius", "89c") so that
    # "350 casings" is not misread as 350°C; ignore implausible readings.
    temp_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:°\s*c\b|deg(?:rees)?\b|celsius\b|c\b)", text, re.I)
    if temp_match and 0 < float(temp_match.group(1)) < 200:
        temp_c = float(temp_match.group(1))

    # Parse shortfall
    shortfall_match = re.search(
        r"(?:shortfall\s+(?:is|of)\s*(\d+)|\b(\d+)\s*(?:battery\s+casings|casings|units|u\b))",
        text,
        re.I,
    )
    if shortfall_match:
        shortfall = int(shortfall_match.group(1) or shortfall_match.group(2))

    order_id = "EV-402"
    if "ev-405" in text:
        order_id = "EV-405"

    return DisruptionExtraction(
        source_channel="WEB_DASHBOARD",
        delay_hours=delay_hours,
        line2_speed_pct=line2_speed,
        line2_temp_celsius=temp_c,
        shortfall_units=shortfall,
        affected_order_id=order_id,
        crisis_headline=f"Compound Crisis: NH48 Delay (+{delay_hours}h) + Line 2 Throttle ({line2_speed}%)",
        raw_summary=raw_text[:200],
    ), "regex-fallback"


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


# ─── 3. Ops Hawk: Air Charter & Overtime Query ───────────────────────────────

def check_air_charter_and_max_overtime() -> Dict[str, Any]:
    """
    Queries emergency air charter availability and maximum shift overtime capacity.
    Used by Operations Hawk to formulate Plan A (Max Speed).
    """
    air_sup = get_supplier("SUP-AIR-04") or {
        "name": "BlueDart Aviation Charter",
        "flat_charter_cost_inr": 600000,
        "lead_time_hours": 6,
        "max_available_qty": 500,
        "weather_risk_pct": 2.0,
    }

    air_history = get_vendor_history("SUP-AIR-04") or {
        "reliability_score_pct": 98.5,
        "on_time_deliveries": 5,
        "past_orders_count": 5,
    }

    return {
        "air_charter": {
            "supplier_id": "SUP-AIR-04",
            "name": air_sup.get("name", "BlueDart Aviation Charter"),
            "flat_cost_inr": air_sup.get("flat_charter_cost_inr", 600000),
            "lead_time_hours": air_sup.get("lead_time_hours", 6),
            "capacity_units": air_sup.get("max_available_qty", 500),
            "reliability_pct": air_history.get("reliability_score_pct", 98.5),
        },
        "parallel_lines": {
            "lines": ["LINE-1", "LINE-3"],
            "ot_rate_per_hour_inr": 22500,
            "units_per_ot_hour": 38,
            "max_ot_hours": 8,
            "max_extra_units": 304,
        },
    }


# ─── 4. CFO Watchdog: Regional Vendors & Episodic Memory ─────────────────────

def query_regional_vendors_and_memory(shortfall_units: int) -> Dict[str, Any]:
    """
    Queries Tier-2 Peenya & Tier-3 Hosur suppliers AND audits their episodic
    memory history in Supabase. Used by CFO Watchdog to challenge air freight spend.
    """
    peenya_sup = get_supplier("SUP-PNY-02") or {
        "name": "Peenya Rapid Metals",
        "max_available_qty": 200,
        "extra_cost_per_unit_inr": 600,
        "lead_time_hours": 4,
    }
    peenya_hist = get_vendor_history("SUP-PNY-02") or {
        "reliability_score_pct": 93.3,
        "quality_rejection_rate_pct": 0.8,
        "last_incident_note": "Consistent 4h delivery via Tumkur Road; max batch 200 units.",
    }

    hosur_sup = get_supplier("SUP-HSR-03") or {
        "name": "Hosur Precision Castings",
        "max_available_qty": 180,
        "extra_cost_per_unit_inr": 850,
        "lead_time_hours": 8,
    }
    hosur_hist = get_vendor_history("SUP-HSR-03") or {
        "reliability_score_pct": 81.8,
        "quality_rejection_rate_pct": 2.1,
        "last_incident_note": "Border toll bottleneck at Attibele during peak hours.",
    }

    exceeds_peenya_cap = shortfall_units > peenya_sup.get("max_available_qty", 200)

    return {
        "peenya": {
            "id": "SUP-PNY-02",
            "name": peenya_sup.get("name"),
            "max_cap": peenya_sup.get("max_available_qty", 200),
            "cost_per_unit": peenya_sup.get("extra_cost_per_unit_inr", 600),
            "lead_time_hours": peenya_sup.get("lead_time_hours", 4),
            "reliability_pct": peenya_hist.get("reliability_score_pct", 93.3),
            "rejection_rate_pct": peenya_hist.get("quality_rejection_rate_pct", 0.8),
            "memory_note": peenya_hist.get("last_incident_note", ""),
        },
        "hosur": {
            "id": "SUP-HSR-03",
            "name": hosur_sup.get("name"),
            "max_cap": hosur_sup.get("max_available_qty", 180),
            "cost_per_unit": hosur_sup.get("extra_cost_per_unit_inr", 850),
            "lead_time_hours": hosur_sup.get("lead_time_hours", 8),
            "reliability_pct": hosur_hist.get("reliability_score_pct", 81.8),
            "rejection_rate_pct": hosur_hist.get("quality_rejection_rate_pct", 2.1),
            "memory_note": hosur_hist.get("last_incident_note", ""),
        },
        "shortfall_units": shortfall_units,
        "exceeds_peenya_cap": exceeds_peenya_cap,
    }


# ─── 5. Arbitrator: PuLP MILP Solver & Monte Carlo Engine ────────────────────

def run_pulp_milp_and_monte_carlo(
    shortfall_units: int,
    delay_hours: int,
    line2_speed_pct: int,
    order_id: str = "EV-402",
    **solver_kwargs: Any,
) -> Dict[str, Any]:
    """
    Invokes the PuLP mixed-integer program and Monte Carlo simulation and
    returns all 3 playbooks ranked by risk-adjusted expected cost.
    Extra keyword arguments (sla_penalty_inr, deadline_hours, client,
    cfo_min_vendor_reliability_pct, ...) are passed through to generate_playbooks.
    """
    result = generate_playbooks(
        shortfall_units=shortfall_units,
        delay_hours=delay_hours,
        line2_speed_pct=line2_speed_pct,
        order_id=order_id,
        **solver_kwargs,
    )
    return result.model_dump()
