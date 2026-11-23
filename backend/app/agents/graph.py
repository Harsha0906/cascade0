"""
CascadeZero — 4-node LangGraph StateGraph (Detective → speed ⇄ cost scenarios → Arbitrator solver)

What each node actually does:
  - Detective:   structured extraction (Gemini, or regex fallback), blast-radius DB update.
  - Speed scenario: its proposal is the MILP solved with the expedite vendor forced on
                 (maximum-speed position), scored by Monte Carlo.
  - Cost scenario: its proposal is the unconstrained cost-minimal MILP, scored by Monte Carlo.
  - Rebuttal:    triggered by *computed* risk, not a fixed threshold — when the CFO plan
                 depends on a vendor below RELIABILITY_FLOOR_PCT, is infeasible, or has a
                 materially lower on-time probability than the Ops plan. Ops challenges;
                 the CFO re-solves with low-reliability vendors excluded and keeps whichever
                 version has the lower risk-adjusted expected cost (concede or hold).
                 At most one rebuttal round.
  - Arbitrator (solver): generates and ranks all playbooks by
                 E[cost] = mitigation_cost + (1 − P_on_time) × SLA_penalty.

The LLM's role is limited and stated plainly: it extracts parameters from free text and
writes the narration for each step. Every number and every decision comes from the
solver/simulation. When Gemini is not used, the narration is a template filled with the
computed numbers, and `llm_trace` records that so the UI can say so.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, TypedDict

from langgraph.graph import END, StateGraph

from app.config import settings
from app.agents.tools import (
    extract_disruption_entities,
    last_extraction_stats,
    usage_tokens,
    query_blast_radius_sql,
    run_pulp_milp_and_monte_carlo,
)
from app.db import (
    get_all_orders, get_inbound_shipments, get_order, get_order_lines, get_stock_levels, log_agent_step,
)
from app.disruption import (
    DisruptionOverrides, DisruptionResolutionError, resolve_disruption, risk_adjusted_model,
)
from app.factory_model import FactoryDataError, FactoryModel, load_factory_model
from app.inventory import FINISHED_STATUSES, compute_shortfall, deadline_hours, order_rank
from app.solver import (
    simulate_monte_carlo,
    solve_pulp_milp,
)

logger = logging.getLogger("cascadezero.graph")

RELIABILITY_FLOOR_PCT = 85.0          # Ops challenges CFO plans that rely on vendors below this
CONFIDENCE_GAP_TRIGGER_PCT = 2.0      # ...or whose P(on-time) trails the Ops plan by more than this
MAX_REBUTTAL_ROUNDS = 1

_genai_client = None
_gemini_failure_logged = False
NARRATION_TIMEOUT_MS = 6000           # one narration call; the model usually answers in ~2 s
NARRATION_COOLDOWN_S = 60.0           # after a failure, use templates for this long (no repeated timeouts)
_narration_down_until = 0.0


# ─── Narration guard: no number that is not in the computed facts ─────────────

_SCALES = {"l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
           "cr": 1e7, "crore": 1e7, "crores": 1e7}
_NUM_TOKEN_RE = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)"                      # 1,80,000 / 1.8 / 94.2
    r"(?:\s*(?P<scale>lakhs?|lacs?|crores?|Cr|L)(?![A-Za-z]))?"
    r"(?P<pct>\s*%)?"
    r"(?:\s*(?P<day>days?)(?![A-Za-z]))?", re.I)
_LIST_MARKER_RE = re.compile(r"(?m)^\s*\d+[.)]\s+")
_SMALL_INT_MAX = 10


def _numbers_in(text: str) -> list:
    """(value, tolerance, kind) for every number written in `text`: lakh/crore scaled, with the
    tolerance of the printed precision. kind is "pct", "day", "small" (a bare integer 1-10) or ""."""
    out = []
    for m in _NUM_TOKEN_RE.finditer(_LIST_MARKER_RE.sub("", text or "")):
        digits = m.group(1).replace(",", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        places = len(digits.split(".")[1]) if "." in digits else 0
        scale = _SCALES.get((m.group("scale") or "").lower(), 1.0)
        tol = 0.5 * 10 ** -places * scale
        kind = "pct" if m.group("pct") else "day" if m.group("day") else ""
        if not kind and scale == 1.0 and places == 0 and 1 <= value <= _SMALL_INT_MAX:
            kind = "small"
        out.append((value * scale, tol, kind))
    return out


def _fact_numbers(facts: Any) -> list:
    """Every number in the facts, flattened (numbers inside strings such as ids and rupee
    amounts count too)."""
    out: list = []
    if isinstance(facts, bool) or facts is None:
        return out
    if isinstance(facts, (int, float)):
        return [float(facts)]
    if isinstance(facts, str):
        return [v for v, _, _ in _numbers_in(facts)]
    if isinstance(facts, dict):
        for v in facts.values():
            out += _fact_numbers(v)
    elif isinstance(facts, (list, tuple, set)):
        for v in facts:
            out += _fact_numbers(v)
    return out


def narration_is_grounded(text: str, facts: Dict[str, Any]) -> bool:
    """True when every number in `text` equals a number in `facts`, allowing rupee formats
    (1.8L, 1,80,000, 1.8 lakh, 0.18 Cr), rounding at the printed precision, a percentage written
    against a fraction, and days for hours. A bare integer 1-10 must match a fact exactly."""
    known = _fact_numbers(facts)
    for value, tol, kind in _numbers_in(text):
        candidates = [value] + ([value * 24] if kind == "day" else [])
        limit = 1e-9 if kind == "small" else tol
        ok = any(abs(c - t) <= limit
                 for c in candidates for f in known for t in ([f] + ([f * 100] if kind == "pct" else [])))
        if not ok:
            return False
    return True


# ─── LLM narration (optional) ────────────────────────────────────────────────

_call_stats = threading.local()   # the latest narration call of this thread, read once by _trace


def _get_genai_client():
    global _genai_client
    if _genai_client is None:
        from google import genai
        _genai_client = genai.Client(api_key=settings.GEMINI_API_KEY,
                                     http_options={"timeout": NARRATION_TIMEOUT_MS})
    return _genai_client


def _llm_agent_reason(
    agent_name: str,
    agent_role: str,
    objective: str,
    context: dict[str, Any],
    fallback_message: str,
) -> Tuple[str, str]:
    """
    Ask Gemini to narrate a decision that has already been computed.
    Returns (text, mode): "gemini", "template", or "template-guarded" when Gemini wrote a number
    that is not in the computed facts (the template is used instead). The call's latency and token
    counts are kept for the next `_trace`.
    """
    global _gemini_failure_logged, _narration_down_until
    _call_stats.last = None
    if not settings.has_gemini or time.monotonic() < _narration_down_until:
        return fallback_message, "template"
    started = time.perf_counter()
    try:
        prompt = (
            f"You are {agent_name} ({agent_role}) in a factory crisis-response workflow.\n"
            f"OBJECTIVE: {objective}\n"
            f"COMPUTED FACTS (from a MILP solver and Monte Carlo simulation — do not change any number): "
            f"{json.dumps(context, default=str)}\n\n"
            f"Write 2 sentences describing what this result shows. Quote only numbers "
            f"present in COMPUTED FACTS. Do not invent figures."
        )
        resp = _get_genai_client().models.generate_content(model=settings.GEMINI_MODEL, contents=prompt)
        _call_stats.last = {"latency_ms": round((time.perf_counter() - started) * 1000, 1),
                            **usage_tokens(resp)}
        if resp.text and len(resp.text.strip()) > 15:
            text = resp.text.strip()
            if not narration_is_grounded(text, context):
                logger.warning("Gemini narration for %s quoted a number not in the computed facts; "
                               "using the template", agent_name)
                return fallback_message, "template-guarded"
            return text, "gemini"
    except Exception as exc:
        # One slow or failed call should not make every remaining step wait for its own timeout.
        _narration_down_until = time.monotonic() + NARRATION_COOLDOWN_S
        _call_stats.last = {"latency_ms": round((time.perf_counter() - started) * 1000, 1)}
        if not _gemini_failure_logged:
            logger.warning("Gemini narration unavailable (%s) — using templated narration", exc)
            _gemini_failure_logged = True
    return fallback_message, "template"


def _trace(state: Dict[str, Any], node: str, mode: str,
           stats: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Append a trace entry. latency_ms (and token counts when Gemini reported usage) come from the
    narration call just made by this thread, or from `stats`; a step that made no call has 0 ms."""
    if stats is None:
        stats = getattr(_call_stats, "last", None) or {}
        _call_stats.last = None
    entry: Dict[str, Any] = {"node": node, "mode": mode, "latency_ms": float(stats.get("latency_ms", 0.0))}
    for key in ("input_tokens", "output_tokens"):
        if key in stats:
            entry[key] = stats[key]
    return list(state.get("llm_trace", [])) + [entry]


# ─── Proposal helpers (numbers come from the solver) ─────────────────────────

def _score_proposal(model: FactoryModel, lp: Dict[str, Any], deadline: float, delay: int,
                    penalty: int) -> Dict[str, Any]:
    mc = simulate_monte_carlo(
        model, "PROPOSAL", lp["units_by_vendor"], lp["overtime_hours"],
        deadline_hours=deadline, fully_covered=lp["feasible"], delay_hours=delay,
    )
    p = mc["confidence_pct"] / 100.0
    return {
        **lp,
        "confidence_pct": mc["confidence_pct"],
        "expected_cost_inr": int(round(lp["total_cost_inr"] + (1 - p) * penalty)),
    }


def _fmt_units(model: FactoryModel, units_by_vendor: Dict[str, int]) -> str:
    parts = [f"{n}u {model.vendor(sid).name.split(' (')[0]}" for sid, n in units_by_vendor.items()]
    return ", ".join(parts) or "no vendors"


def _weak_vendors(model: FactoryModel, units_by_vendor: Dict[str, int]) -> List[str]:
    return [
        f"{model.vendor(sid).name.split(' (')[0]} ({model.vendor(sid).reliability_pct}%)"
        for sid in units_by_vendor
        if model.vendor(sid).reliability_pct < RELIABILITY_FLOOR_PCT
    ]


# ─── Graph State ─────────────────────────────────────────────────────────────

class CascadeGraphState(TypedDict, total=False):
    run_id: str
    factory_id: str
    factory_model: FactoryModel
    line_speeds: Dict[str, int]
    raw_message: str
    source_channel: str

    delay_hours: int
    line_impacts: List[Dict[str, Any]]
    affected_supplier_id: Optional[str]
    shortfall_units: int
    shortfall_source: str
    shortfall_breakdown: Optional[Dict[str, Any]]
    alert_stated_shortfall: Optional[int]
    order_selection: str
    other_order_shortfalls: List[Dict[str, Any]]
    blocked_route: Optional[str]
    blocked_routes: List[str]
    weather_alert: bool
    route_note: Optional[str]
    now: datetime
    order_id: str
    crisis_headline: str
    extraction_source: str

    blast_radius: Dict[str, Any]

    ops_proposal: Optional[Dict[str, Any]]
    cfo_proposal: Dict[str, Any]
    rebuttal_count: int
    rebuttal_pending: bool
    rebuttal_notes: List[str]
    cfo_reliability_floor_pct: float

    solver_result: Dict[str, Any]
    playbooks: List[Dict[str, Any]]
    recommended_plan_id: str

    llm_trace: List[Dict[str, Any]]



def _ctx(state: CascadeGraphState) -> Tuple[float, int, int]:
    br = state["blast_radius"]
    return float(br["hours_remaining"]), int(state["delay_hours"]), int(br["sla_penalty_inr"])


def _supplier_name(model: FactoryModel, supplier_id: str) -> str:
    names = {**dict(model.primary_suppliers), **{v.supplier_id: v.name for v in model.vendors}}
    return names.get(supplier_id, supplier_id)


# ─── Node 1: Detective ───────────────────────────────────────────────────────

def _planning_item(model: FactoryModel) -> str:
    item_code = (model.stock_item_code or "").strip()
    if not item_code:
        raise FactoryDataError(
            f"factory {model.factory_id} has no stock_item_code; cannot compute a shortfall")
    return item_code


def _factory_orders(model: FactoryModel) -> List[Dict[str, Any]]:
    # Only this factory's orders: another factory's orders must never reserve stock here.
    return [o for o in get_all_orders() if o.get("factory_id") == model.factory_id]


def _make_shortfall_resolver(model: FactoryModel, now: datetime) -> Callable[..., Any]:
    """Inventory-based shortfall for one factory; reads data only when called (not on override).

    Returns None when the order has no line for the planning item (no inventory data)."""
    def resolve(order_id: str, supplier_id: Optional[str], delay_hours: int):
        item_code = _planning_item(model)
        orders = _factory_orders(model)
        lines = get_order_lines([o["order_id"] for o in orders])
        if not any(l["order_id"] == order_id and l["item_code"] == item_code for l in lines):
            return None
        return compute_shortfall(
            order_id, item_code, orders, lines, get_stock_levels(model.factory_id),
            get_inbound_shipments(model.factory_id), now,
            delayed_supplier_id=supplier_id, delay_hours=delay_hours,
        )
    return resolve


def _make_order_ranker(model: FactoryModel, now: datetime) -> Callable[..., List[Any]]:
    """Shortfall breakdowns of every open order of the factory with a line for the planning item,
    most urgent first (the reservation order). Used when the alert names no order."""
    def rank(supplier_id: Optional[str], delay_hours: int) -> List[Any]:
        item_code = _planning_item(model)
        orders = _factory_orders(model)
        lines = get_order_lines([o["order_id"] for o in orders])
        with_line = {l["order_id"] for l in lines if l["item_code"] == item_code}
        candidates = [o for o in orders
                      if o["order_id"] in with_line and o.get("status") not in FINISHED_STATUSES]
        if not candidates:
            return []
        candidates.sort(key=lambda o: order_rank(o, now))
        stock = get_stock_levels(model.factory_id)
        shipments = get_inbound_shipments(model.factory_id)
        return [compute_shortfall(o["order_id"], item_code, orders, lines, stock, shipments, now,
                                  delayed_supplier_id=supplier_id, delay_hours=delay_hours)
                for o in candidates]
    return rank


def detective_node(state: CascadeGraphState) -> Dict[str, Any]:
    run_id = state["run_id"]
    model = load_factory_model(state.get("factory_id"))   # FactoryDataError propagates (-> 503 in main)
    order_ids = [o["order_id"] for o in get_all_orders() if o.get("factory_id") == model.factory_id]
    t0 = time.perf_counter()
    extraction, source = extract_disruption_entities(state["raw_message"], model, order_ids)
    extraction_stats = {**last_extraction_stats(), "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}

    # Explicit overrides (scenario presets / sliders) win over extraction, and we say so.
    # None means "not overridden"; an explicit 0 is a real value and must win.
    overrides = DisruptionOverrides(
        delay_hours=state.get("delay_hours"),
        shortfall_units=state.get("shortfall_units"),
        line_speeds=state.get("line_speeds"),
        order_id=state.get("order_id"),
    )
    overridden = any(
        v is not None for v in (overrides.delay_hours, overrides.shortfall_units, overrides.line_speeds))
    # Resolve before any write: an unknown reference raises with nothing touched.
    now = state.get("now") or datetime.now(timezone.utc)
    disruption = resolve_disruption(
        extraction, model, order_ids, overrides, shortfall_resolver=_make_shortfall_resolver(model, now),
        order_ranker=_make_order_ranker(model, now))
    order_row = get_order(disruption.order_id)
    if order_row is None:
        raise DisruptionResolutionError(f"Unknown order '{disruption.order_id}'")
    hours_left = deadline_hours(order_row, now)
    if hours_left <= 0:
        raise DisruptionResolutionError(
            f"order {disruption.order_id} was due {-hours_left:.1f}h ago; update its due date before planning")
    breakdown = disruption.shortfall_breakdown
    if disruption.shortfall_source == "inventory":
        shortfall_txt = f"inventory: {breakdown.explanation()}"
        if (disruption.alert_stated_shortfall is not None
                and disruption.alert_stated_shortfall != disruption.shortfall_units):
            shortfall_txt = (f"alert said {disruption.alert_stated_shortfall}; "
                             f"using inventory: {breakdown.explanation()}")
    elif disruption.shortfall_source == "override":
        shortfall_txt = f"{disruption.shortfall_units} short (set manually)"
    else:
        shortfall_txt = f"{disruption.shortfall_units} short (from the alert; no inventory data for this order)"

    line_names = {l.line_id: l.name for l in model.lines}
    lines_txt = ", ".join(
        f"{line_names[li.line_id]} {li.speed_pct}%"
        + (f" ({li.temp_celsius:g}°C)" if li.temp_celsius is not None else "")
        for li in disruption.line_impacts) or "no line impact"
    supplier_txt = (f"{_supplier_name(model, disruption.supplier_id)} +{disruption.delay_hours}h"
                    if disruption.supplier_id else "no supplier delay")
    selection_txt = ""
    if disruption.order_selection == "inventory":
        others = ", ".join(f"{x['order_id']} {x['shortfall']} short" for x in disruption.other_order_shortfalls)
        selection_txt = (f" | order not named in the alert: chose #{disruption.order_id}, the most urgent "
                         f"order that is short (checked from inventory"
                         + (f"; also {others}" if others else "") + ")")

    # Every later node (Ops, CFO, arbitrator, Monte Carlo) plans on the risk-adjusted model: vendors
    # on the blocked route are slower, and a weather alert raises every vendor's shock probability.
    planning_model = risk_adjusted_model(model, disruption)
    risk_bits = []
    for route in (disruption.all_blocked_routes if disruption.delay_hours > 0 else ()):
        slowed = [v.name.split(" (")[0] for v in model.vendors if v.route == route]
        risk_bits.append(f"route '{route}' blocked +{disruption.delay_hours}h"
                         + (f": {', '.join(slowed)} slower" if slowed else " (no vendor on it)"))
    if disruption.weather_alert:
        risk_bits.append("weather alert: delay-shock probability doubled (cap 90%)")
    if disruption.route_note:
        risk_bits.append(disruption.route_note)
    log_agent_step(
        run_id=run_id, step_order=1,
        agent_name="Disruption Detective (agent)", agent_role="Disruption Entity Extractor", badge_color="amber",
        tool_called=f"extract_disruption_entities({source})",
        tool_output_summary=(
            f"{supplier_txt} | {lines_txt} | Shortfall {disruption.shortfall_units} units on #{disruption.order_id}"
            f" ({shortfall_txt})"
            + selection_txt
            + (f" | risk: {'; '.join(risk_bits)}" if risk_bits else "")
            + (" | parameters set by scenario/slider override" if overridden else "")
        ),
        message=(
            f"🚨 Alert ingested via {state.get('source_channel', 'WEB_DASHBOARD')}. "
            f"Parsed with {'Gemini' if source.startswith('gemini') else 'the regex fallback (LLM not used)'}: "
            f"'{state['raw_message'][:120]}…'"
        ),
    )

    blast = query_blast_radius_sql(model, disruption, now=now)
    summary = (
        f"Order #{disruption.order_id} exposed to ₹{blast['sla_penalty_inr']:,} penalty, "
        f"{blast['hours_remaining']:g}h to deadline. {supplier_txt}; {lines_txt}."
    )
    msg, mode = _llm_agent_reason(
        "Disruption Detective (agent)", "Causal Dependency Mapper",
        "Summarise the compound disruption and what is at stake.",
        {"delay_hours": disruption.delay_hours, "supplier": supplier_txt, "line_impacts": lines_txt,
         "shortfall_units": disruption.shortfall_units, "order_id": disruption.order_id,
         "sla_penalty_inr": blast["sla_penalty_inr"]},
        f"⚠️ {summary} Shortfall: {disruption.shortfall_units} units.",
    )
    log_agent_step(
        run_id=run_id, step_order=2,
        agent_name="Disruption Detective (agent)", agent_role="Causal Dependency Mapper", badge_color="amber",
        tool_called="query_blast_radius_sql()", tool_output_summary=summary, message=msg,
    )

    trace = _trace({}, "detective_extraction", "gemini" if source.startswith("gemini") else "regex-fallback",
                   stats=extraction_stats)
    trace = _trace({"llm_trace": trace}, "detective", mode)
    return {
        "factory_id": model.factory_id,
        "factory_model": planning_model,
        "blocked_route": disruption.blocked_route,
        "blocked_routes": list(disruption.all_blocked_routes),
        "weather_alert": disruption.weather_alert,
        "route_note": disruption.route_note,
        "line_speeds": disruption.line_speeds,
        "line_impacts": disruption.to_dict()["line_impacts"],
        "affected_supplier_id": disruption.supplier_id,
        "delay_hours": disruption.delay_hours,
        "shortfall_units": disruption.shortfall_units,
        "shortfall_source": disruption.shortfall_source,
        "shortfall_breakdown": breakdown.to_dict() if breakdown is not None else None,
        "alert_stated_shortfall": disruption.alert_stated_shortfall,
        "order_selection": disruption.order_selection,
        "other_order_shortfalls": [dict(x) for x in disruption.other_order_shortfalls],
        "order_id": disruption.order_id,
        "crisis_headline": disruption.headline,
        "extraction_source": source,
        "blast_radius": blast,
        "rebuttal_count": 0,
        "rebuttal_pending": False,
        "cfo_reliability_floor_pct": 0.0,
        "llm_trace": trace,
    }


# ─── Node 2: Speed scenario ─────────────────────────────────────────────────

def ops_hawk_node(state: CascadeGraphState) -> Dict[str, Any]:
    run_id = state["run_id"]
    deadline, delay, penalty = _ctx(state)
    shortfall, line_speeds = state["shortfall_units"], state["line_speeds"]
    model = state["factory_model"]

    if not state.get("rebuttal_pending"):
        expedite_id = model.expedite_vendor_id
        if expedite_id is None:
            log_agent_step(
                run_id=run_id, step_order=3,
                agent_name="Speed scenario (expedite-first)", agent_role="Planning scenario: maximum speed", badge_color="rose",
                tool_called="factory_model.expedite_vendor_id",
                tool_output_summary=f"{model.name} has no expedite vendor available",
                message=(f"🔥 {model.name} has no expedite option (no vendor with role EXPEDITE), "
                         f"so I have no maximum-speed proposal to make."),
            )
            return {"ops_proposal": None, "llm_trace": _trace(state, "ops_hawk", "template")}
        expedite = model.vendor(expedite_id)
        ot_lines = ", ".join(f"{l.line_id} (<={l.max_ot_hours}h OT, {l.ot_units_per_hour}u/h)"
                             for l in model.overtime_lines) or "none"
        lp = solve_pulp_milp(model, shortfall, line_speeds, deadline, force_vendor_id=expedite_id)
        prop = _score_proposal(model, lp, deadline, delay, penalty)
        facts = {
            "expedite_vendor": f"{expedite.name} (flat ₹{expedite.flat_cost:,}, {expedite.lead_hours:g}h lead, "
                               f"cap {expedite.max_units}u, {expedite.reliability_pct}% reliable)",
            "overtime_lines": ot_lines,
            "plan": _fmt_units(model, prop["units_by_vendor"]), "overtime_hours": prop["overtime_hours"],
            "cost_inr": prop["total_cost_inr"], "p_on_time_pct": prop["confidence_pct"],
            "feasible": prop["feasible"],
        }
        msg, mode = _llm_agent_reason(
            "Speed scenario (expedite-first)", "Planning scenario: maximum speed",
            "Explain this planning scenario's computed result: the fastest, most reliable recovery (expedite option).", facts,
            f"🔥 My position: {facts['plan']} + {prop['overtime_hours']}h overtime. "
            f"Cost ₹{prop['total_cost_inr']:,}, modelled P(on-time) {prop['confidence_pct']}%."
            + ("" if prop["feasible"] else " Even this leaves units uncovered."),
        )
        log_agent_step(
            run_id=run_id, step_order=3,
            agent_name="Speed scenario (expedite-first)", agent_role="Planning scenario: maximum speed", badge_color="rose",
            tool_called=f"solve_pulp_milp(force_vendor_id={expedite_id}) + simulate_monte_carlo()",
            tool_output_summary=(
                f"Expedite {facts['expedite_vendor']}; OT lines {ot_lines} | {facts['plan']} + {prop['overtime_hours']}h OT | ₹{prop['total_cost_inr']:,} | "
                f"P(on-time) {prop['confidence_pct']}% | E[cost] ₹{prop['expected_cost_inr']:,}"
            ),
            message=msg,
        )
        return {"ops_proposal": prop, "llm_trace": _trace(state, "ops_hawk", mode)}

    # Rebuttal turn: challenge the CFO plan with computed evidence.
    cfo, ops = state["cfo_proposal"], state.get("ops_proposal")
    weak = _weak_vendors(model, cfo["units_by_vendor"])
    reasons = []
    if weak:
        reasons.append(f"relies on {', '.join(weak)} below the {RELIABILITY_FLOOR_PCT:g}% reliability floor")
    if not cfo["feasible"]:
        reasons.append("leaves units uncovered")
    if ops is not None and ops["confidence_pct"] - cfo["confidence_pct"] > CONFIDENCE_GAP_TRIGGER_PCT:
        reasons.append(f"P(on-time) {cfo['confidence_pct']}% vs my {ops['confidence_pct']}%")
    challenge = "Cost scenario plan " + "; ".join(reasons) + "."
    msg, mode = _llm_agent_reason(
        "Speed scenario (expedite-first)", "Planning scenario: maximum speed",
        "Explain this planning scenario's computed risk check of the cost scenario plan.",
        {"challenge": challenge, "cfo_plan": _fmt_units(model, cfo["units_by_vendor"])},
        f"⚡ REBUTTAL: {challenge} Re-plan without the weak link.",
    )
    log_agent_step(
        run_id=run_id, step_order=5,
        agent_name="Speed scenario (expedite-first)", agent_role="Planning scenario: maximum speed", badge_color="rose",
        tool_called="audit_proposal_risk()", tool_output_summary=challenge, message=msg,
    )
    return {
        "rebuttal_pending": False,
        "rebuttal_notes": list(state.get("rebuttal_notes", [])) + [f"Speed scenario: {challenge}"],
        "llm_trace": _trace(state, "ops_hawk_rebuttal", mode),
    }


# ─── Node 3: Cost scenario ────────────────────────────────────────────────────

def _needs_rebuttal(model: FactoryModel, cfo: Dict[str, Any], ops: Optional[Dict[str, Any]]) -> bool:
    gap = ops is not None and ops["confidence_pct"] - cfo["confidence_pct"] > CONFIDENCE_GAP_TRIGGER_PCT
    return bool(_weak_vendors(model, cfo["units_by_vendor"]) or not cfo["feasible"] or gap)


def cfo_watchdog_node(state: CascadeGraphState) -> Dict[str, Any]:
    run_id = state["run_id"]
    deadline, delay, penalty = _ctx(state)
    shortfall, line_speeds = state["shortfall_units"], state["line_speeds"]
    model = state["factory_model"]
    rounds = state.get("rebuttal_count", 0)

    if rounds == 0:
        lp = solve_pulp_milp(model, shortfall, line_speeds, deadline)
        prop = _score_proposal(model, lp, deadline, delay, penalty)
        ops = state.get("ops_proposal")
        saving = None if ops is None else ops["total_cost_inr"] - prop["total_cost_inr"]
        regional = [f"{v.name.split(' (')[0]} (cap {v.max_units}u, ₹{v.unit_cost}/u, {v.reliability_pct}% reliable)"
                    for v in model.vendors if v.supplier_id != model.expedite_vendor_id]
        facts = {
            "regional_vendors": regional,
            "plan": _fmt_units(model, prop["units_by_vendor"]), "overtime_hours": prop["overtime_hours"],
            "cost_inr": prop["total_cost_inr"], "p_on_time_pct": prop["confidence_pct"],
            "saving_vs_ops_inr": saving,
        }
        saving_txt = f" (₹{saving:,} less than Ops)" if saving is not None else ""
        msg, mode = _llm_agent_reason(
            "Cost scenario (cheapest feasible)", "Planning scenario: lowest cost",
            "Explain this planning scenario's computed result: the lowest-cost plan that still protects the order.", facts,
            f"💰 Cost-minimal plan: {facts['plan']} + {prop['overtime_hours']}h overtime = "
            f"₹{prop['total_cost_inr']:,}{saving_txt}, P(on-time) {prop['confidence_pct']}%.",
        )
        log_agent_step(
            run_id=run_id, step_order=4,
            agent_name="Cost scenario (cheapest feasible)", agent_role="Planning scenario: lowest cost", badge_color="cyan",
            tool_called="solve_pulp_milp(min cost) + simulate_monte_carlo()",
            tool_output_summary=(
                f"Vendors: {'; '.join(regional) or 'none'} | {facts['plan']} + {prop['overtime_hours']}h OT | ₹{prop['total_cost_inr']:,} | "
                f"P(on-time) {prop['confidence_pct']}% | E[cost] ₹{prop['expected_cost_inr']:,}"
            ),
            message=msg,
        )
        pending = _needs_rebuttal(model, prop, ops) and MAX_REBUTTAL_ROUNDS > 0
        return {
            "cfo_proposal": prop,
            "rebuttal_pending": pending,
            "rebuttal_count": 1 if pending else 0,
            "llm_trace": _trace(state, "cfo_watchdog", mode),
        }

    # Response to the rebuttal: re-solve without low-reliability vendors, keep the better E[cost].
    original = state["cfo_proposal"]
    lp = solve_pulp_milp(model, shortfall, line_speeds, deadline,
                         min_vendor_reliability_pct=RELIABILITY_FLOOR_PCT)
    revised = _score_proposal(model, lp, deadline, delay, penalty)
    concede = revised["expected_cost_inr"] < original["expected_cost_inr"]
    chosen = revised if concede else original
    verdict = (
        f"Conceded: revised plan {_fmt_units(model, revised['units_by_vendor'])} has lower E[cost] "
        f"(₹{revised['expected_cost_inr']:,} vs ₹{original['expected_cost_inr']:,})."
        if concede else
        f"Held position: excluding weak vendors raises E[cost] to ₹{revised['expected_cost_inr']:,} "
        f"vs ₹{original['expected_cost_inr']:,}; the reliability risk does not threaten the deadline."
    )
    msg, mode = _llm_agent_reason(
        "Cost scenario (cheapest feasible)", "Planning scenario: lowest cost", "Explain this planning scenario's computed re-solve after the risk check.",
        {"verdict": verdict}, f"🤝 {verdict}",
    )
    log_agent_step(
        run_id=run_id, step_order=6,
        agent_name="Cost scenario (cheapest feasible)", agent_role="Planning scenario: lowest cost", badge_color="cyan",
        tool_called=f"solve_pulp_milp(min_reliability={RELIABILITY_FLOOR_PCT:g}%)",
        tool_output_summary=verdict, message=msg,
    )
    return {
        "cfo_proposal": chosen,
        "cfo_reliability_floor_pct": RELIABILITY_FLOOR_PCT if concede else 0.0,
        "rebuttal_count": rounds,  # rounds completed (set to 1 when the rebuttal started)
        "rebuttal_pending": False,
        "rebuttal_notes": list(state.get("rebuttal_notes", [])) + [f"Cost scenario: {verdict}"],
        "llm_trace": _trace(state, "cfo_watchdog_response", mode),
    }


def should_rebuttal_continue(state: CascadeGraphState) -> Literal["rebuttal", "arbitrate"]:
    if state.get("rebuttal_pending") and state.get("rebuttal_count", 0) <= MAX_REBUTTAL_ROUNDS:
        return "rebuttal"
    return "arbitrate"


# ─── Node 4: Arbitrator ──────────────────────────────────────────────────────

def arbitrator_node(state: CascadeGraphState) -> Dict[str, Any]:
    run_id = state["run_id"]
    deadline, delay, penalty = _ctx(state)
    br = state["blast_radius"]
    solver_dict = run_pulp_milp_and_monte_carlo(
        state["factory_model"],
        shortfall_units=state["shortfall_units"],
        delay_hours=delay,
        line_speeds=state["line_speeds"],
        order_id=state["order_id"],
        sla_penalty_inr=penalty,
        partial_penalty_inr=int(br["partial_delay_penalty_inr"]),
        deadline_hours=deadline,
        client=br["client"],
        cfo_min_vendor_reliability_pct=state.get("cfo_reliability_floor_pct", 0.0),
    )
    playbooks = solver_dict["playbooks"]
    winner_id = solver_dict["recommended_plan_id"]
    w = next(p for p in playbooks if p["id"] == winner_id)
    ranking = " | ".join(f"{p['id']} E[₹{p['expected_cost_inr']:,}]" for p in playbooks)
    summary = (
        f"MILP status: {solver_dict['lp_status']} ({solver_dict['solve_duration_ms']}ms). "
        f"Ranked by {solver_dict['ranking_rule']}: {ranking}. Winner {winner_id}."
    )
    msg, mode = _llm_agent_reason(
        "Arbitrator (solver ranking)", "Solver & Risk Ranking", "Explain why the winning plan has the lowest risk-adjusted cost.",
        {"winner": winner_id, "cost_inr": w["total_mitigation_cost_inr"], "p_on_time_pct": w["confidence_pct"],
         "expected_cost_inr": w["expected_cost_inr"], "ranking": ranking},
        f"⚖️ {w['name']} wins: ₹{w['total_mitigation_cost_inr']:,} spend, P(on-time) {w['confidence_pct']}% "
        f"(95% CI {w.get('confidence_ci_low_pct')}–{w.get('confidence_ci_high_pct')}%), "
        f"lowest expected cost ₹{w['expected_cost_inr']:,}.",
    )
    log_agent_step(
        run_id=run_id, step_order=7 if state.get("rebuttal_count", 0) > 0 else 5,
        agent_name="Arbitrator (solver ranking)", agent_role="Solver & Risk Ranking", badge_color="emerald",
        tool_called="generate_playbooks(MILP + 1000-run Monte Carlo)", tool_output_summary=summary, message=msg,
    )
    return {
        "solver_result": solver_dict,
        "playbooks": playbooks,
        "recommended_plan_id": winner_id,
        "llm_trace": _trace(state, "arbitrator", mode),
    }


# ─── Build & Compile ─────────────────────────────────────────────────────────

def build_cascade_graph():
    workflow = StateGraph(CascadeGraphState)
    workflow.add_node("detective", detective_node)
    workflow.add_node("ops_hawk", ops_hawk_node)
    workflow.add_node("cfo_watchdog", cfo_watchdog_node)
    workflow.add_node("arbitrator", arbitrator_node)
    workflow.set_entry_point("detective")
    workflow.add_edge("detective", "ops_hawk")
    workflow.add_edge("ops_hawk", "cfo_watchdog")
    workflow.add_conditional_edges(
        "cfo_watchdog", should_rebuttal_continue, {"rebuttal": "ops_hawk", "arbitrate": "arbitrator"},
    )
    workflow.add_edge("arbitrator", END)
    return workflow.compile()


cascade_graph = build_cascade_graph()


def summarize_ai_mode(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Collapse the per-node trace into what the UI should disclose. Only "gemini" entries are
    LLM output: "template", "template-guarded" (Gemini quoted a number not in the facts, so the
    template was used) and "regex-fallback" are not."""
    modes = {t["mode"] for t in trace}
    llm_modes = {"gemini"}
    if modes and modes <= llm_modes:
        overall = "llm"
    elif modes & llm_modes:
        overall = "mixed"
    else:
        overall = "fallback"
    return {
        "overall": overall,
        "model": settings.GEMINI_MODEL if overall != "fallback" else None,
        "trace": trace,
        "total_latency_ms": round(sum(t.get("latency_ms", 0.0) for t in trace), 1),
        "input_tokens": sum(t.get("input_tokens", 0) for t in trace),
        "output_tokens": sum(t.get("output_tokens", 0) for t in trace),
        "note": (
            "All numbers come from the MILP solver and Monte Carlo simulation. "
            + ("Narration and extraction used Gemini." if overall == "llm" else
               "Some or all narration/extraction used templates or regex because the LLM was unavailable."
               if overall == "mixed" else
               "LLM not used: extraction ran on regex rules and narration is templated.")
        ),
    }


def run_cascade_pipeline(
    raw_message: str,
    source_channel: str = "WEB_DASHBOARD",
    override_delay_hours: Optional[int] = None,
    override_shortfall_units: Optional[int] = None,
    override_line_speeds: Optional[Dict[str, int]] = None,
    order_id: Optional[str] = None,
    factory_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
    initial: CascadeGraphState = {
        "run_id": run_id,
        "factory_id": factory_id,
        "raw_message": raw_message,
        "source_channel": source_channel,
        "delay_hours": override_delay_hours,
        "line_speeds": override_line_speeds,
        "shortfall_units": override_shortfall_units,
        "order_id": order_id,
        "now": now or datetime.now(timezone.utc),
        "rebuttal_notes": [],
        "llm_trace": [],
    }
    final_state = cascade_graph.invoke(initial)
    final_state.pop("now", None)   # run-internal clock; the persisted run must stay JSON-serialisable
    final_state["ai_mode"] = summarize_ai_mode(final_state.get("llm_trace", []))
    return final_state
