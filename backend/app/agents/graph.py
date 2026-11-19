"""
CascadeZero — 4-node LangGraph StateGraph (Detective → Ops ⇄ CFO → Arbitrator)

What each node actually does:
  - Detective:   structured extraction (Gemini, or regex fallback), blast-radius DB update.
  - Ops Hawk:    its proposal is the MILP solved with the expedite vendor forced on
                 (maximum-speed position), scored by Monte Carlo.
  - CFO Watchdog: its proposal is the unconstrained cost-minimal MILP, scored by Monte Carlo.
  - Rebuttal:    triggered by *computed* risk, not a fixed threshold — when the CFO plan
                 depends on a vendor below RELIABILITY_FLOOR_PCT, is infeasible, or has a
                 materially lower on-time probability than the Ops plan. Ops challenges;
                 the CFO re-solves with low-reliability vendors excluded and keeps whichever
                 version has the lower risk-adjusted expected cost (concede or hold).
                 At most one rebuttal round.
  - Arbitrator:  generates and ranks all playbooks by
                 E[cost] = mitigation_cost + (1 − P_on_time) × SLA_penalty.

The LLM's role is limited and stated plainly: it extracts parameters from free text and
writes the narration for each step. Every number and every decision comes from the
solver/simulation. When Gemini is not used, the narration is a template filled with the
computed numbers, and `llm_trace` records that so the UI can say so.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict

from langgraph.graph import END, StateGraph

from app.config import settings
from app.agents.tools import (
    extract_disruption_entities,
    query_blast_radius_sql,
    run_pulp_milp_and_monte_carlo,
)
from app.db import log_agent_step
from app.factory_model import FactoryModel, load_factory_model
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


# ─── LLM narration (optional) ────────────────────────────────────────────────

def _get_genai_client():
    global _genai_client
    if _genai_client is None:
        from google import genai
        _genai_client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options={"timeout": 12000})
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
    Returns (text, mode) where mode is "gemini" or "template".
    """
    global _gemini_failure_logged
    if not settings.has_gemini:
        return fallback_message, "template"
    try:
        prompt = (
            f"You are {agent_name} ({agent_role}) in a factory crisis-response workflow.\n"
            f"OBJECTIVE: {objective}\n"
            f"COMPUTED FACTS (from a MILP solver and Monte Carlo simulation — do not change any number): "
            f"{json.dumps(context, default=str)}\n\n"
            f"Write 2 sentences in the first person stating your position. Quote only numbers "
            f"present in COMPUTED FACTS. Do not invent figures."
        )
        resp = _get_genai_client().models.generate_content(model=settings.GEMINI_MODEL, contents=prompt)
        if resp.text and len(resp.text.strip()) > 15:
            return resp.text.strip(), "gemini"
    except Exception as exc:
        if not _gemini_failure_logged:
            logger.warning("Gemini narration unavailable (%s) — using templated narration", exc)
            _gemini_failure_logged = True
    return fallback_message, "template"


def _trace(state: Dict[str, Any], node: str, mode: str) -> List[Dict[str, str]]:
    return list(state.get("llm_trace", [])) + [{"node": node, "mode": mode}]


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
    line2_speed_pct: int
    line2_temp_celsius: float
    shortfall_units: int
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

    llm_trace: List[Dict[str, str]]


def _default(value: Any, fallback: Any) -> Any:
    """Use `fallback` only when `value` is missing (None) — never for a legitimate 0."""
    return fallback if value is None else value


def _ctx(state: CascadeGraphState) -> Tuple[float, int, int]:
    br = state.get("blast_radius", {})
    return (
        float(_default(br.get("hours_remaining"), 38)),
        int(state.get("delay_hours", 0)),
        int(_default(br.get("sla_penalty_inr"), 2_500_000)),
    )


# ─── Node 1: Detective ───────────────────────────────────────────────────────

def detective_node(state: CascadeGraphState) -> Dict[str, Any]:
    run_id = state["run_id"]
    model = load_factory_model(state.get("factory_id"))   # FactoryDataError propagates (-> 503 in main)
    extraction, source = extract_disruption_entities(state["raw_message"])

    # Explicit overrides (scenario presets / sliders) win over extraction, and we say so.
    # None means "not overridden"; an explicit 0 is a real value and must win.
    delay_hours = _default(state.get("delay_hours"), extraction.delay_hours)
    line2_speed = _default(state.get("line2_speed_pct"), extraction.line2_speed_pct)
    line2_temp = _default(state.get("line2_temp_celsius"), extraction.line2_temp_celsius)
    shortfall = _default(state.get("shortfall_units"), extraction.shortfall_units)
    order_id = state.get("order_id") or extraction.affected_order_id or "EV-402"
    overridden = any(state.get(k) is not None for k in ("delay_hours", "line2_speed_pct", "shortfall_units"))

    log_agent_step(
        run_id=run_id, step_order=1,
        agent_name="Blast-Radius Detective", agent_role="Disruption Entity Extractor", badge_color="amber",
        tool_called=f"extract_disruption_entities({source})",
        tool_output_summary=(
            f"Delay +{delay_hours}h | Line 2 {line2_speed}% ({line2_temp}°C) | Shortfall {shortfall} units on #{order_id}"
            + (" | parameters set by scenario/slider override" if overridden else "")
        ),
        message=(
            f"🚨 Alert ingested via {state.get('source_channel', 'WEB_DASHBOARD')}. "
            f"Parsed with {'Gemini' if source.startswith('gemini') else 'the regex fallback (LLM not used)'}: "
            f"'{state['raw_message'][:120]}…'"
        ),
    )

    blast = query_blast_radius_sql(
        shortfall_units=shortfall, delay_hours=delay_hours, line2_speed_pct=line2_speed,
        order_id=order_id, line2_temp_celsius=line2_temp,
    )
    summary = (
        f"Order #{order_id} exposed to ₹{blast['sla_penalty_inr']:,} penalty, "
        f"{blast.get('hours_remaining', 38)}h to deadline. Inbound delay +{delay_hours}h; "
        f"Line 2 at {line2_speed}% ({line2_temp}°C)."
    )
    msg, mode = _llm_agent_reason(
        "Blast-Radius Detective", "Causal Dependency Mapper",
        "Summarise the compound disruption and what is at stake.",
        {"delay_hours": delay_hours, "line2_speed_pct": line2_speed, "line2_temp_celsius": line2_temp,
         "shortfall_units": shortfall, "order_id": order_id, "sla_penalty_inr": blast["sla_penalty_inr"]},
        f"⚠️ {summary} Shortfall: {shortfall} units.",
    )
    log_agent_step(
        run_id=run_id, step_order=2,
        agent_name="Blast-Radius Detective", agent_role="Causal Dependency Mapper", badge_color="amber",
        tool_called="query_blast_radius_sql()", tool_output_summary=summary, message=msg,
    )

    trace = [{"node": "detective_extraction", "mode": "gemini" if source.startswith("gemini") else "regex-fallback"}]
    trace.append({"node": "detective", "mode": mode})
    return {
        "factory_id": model.factory_id,
        "factory_model": model,
        "line_speeds": {"LINE-2": line2_speed},
        "delay_hours": delay_hours,
        "line2_speed_pct": line2_speed,
        "line2_temp_celsius": line2_temp,
        "shortfall_units": shortfall,
        "order_id": order_id,
        "crisis_headline": extraction.crisis_headline,
        "extraction_source": source,
        "blast_radius": blast,
        "rebuttal_count": 0,
        "rebuttal_pending": False,
        "cfo_reliability_floor_pct": 0.0,
        "llm_trace": trace,
    }


# ─── Node 2: Operations Hawk ─────────────────────────────────────────────────

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
                agent_name="Operations Hawk", agent_role="Chief of Manufacturing Operations", badge_color="rose",
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
            "Operations Hawk", "Chief of Manufacturing Operations",
            "Argue for the fastest, most reliable recovery (expedite option).", facts,
            f"🔥 My position: {facts['plan']} + {prop['overtime_hours']}h overtime. "
            f"Cost ₹{prop['total_cost_inr']:,}, modelled P(on-time) {prop['confidence_pct']}%."
            + ("" if prop["feasible"] else " Even this leaves units uncovered."),
        )
        log_agent_step(
            run_id=run_id, step_order=3,
            agent_name="Operations Hawk", agent_role="Chief of Manufacturing Operations", badge_color="rose",
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
    challenge = "CFO plan " + "; ".join(reasons) + "."
    msg, mode = _llm_agent_reason(
        "Operations Hawk", "Chief of Manufacturing Operations",
        "Challenge the CFO plan using only the computed risk evidence.",
        {"challenge": challenge, "cfo_plan": _fmt_units(model, cfo["units_by_vendor"])},
        f"⚡ REBUTTAL: {challenge} Re-plan without the weak link.",
    )
    log_agent_step(
        run_id=run_id, step_order=5,
        agent_name="Operations Hawk", agent_role="Chief of Manufacturing Operations", badge_color="rose",
        tool_called="audit_proposal_risk()", tool_output_summary=challenge, message=msg,
    )
    return {
        "rebuttal_pending": False,
        "rebuttal_notes": list(state.get("rebuttal_notes", [])) + [f"Ops: {challenge}"],
        "llm_trace": _trace(state, "ops_hawk_rebuttal", mode),
    }


# ─── Node 3: CFO Watchdog ────────────────────────────────────────────────────

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
            "CFO Watchdog", "VP of Finance",
            "Argue for the lowest-cost plan that still protects the order.", facts,
            f"💰 Cost-minimal plan: {facts['plan']} + {prop['overtime_hours']}h overtime = "
            f"₹{prop['total_cost_inr']:,}{saving_txt}, P(on-time) {prop['confidence_pct']}%.",
        )
        log_agent_step(
            run_id=run_id, step_order=4,
            agent_name="CFO Watchdog", agent_role="VP of Finance", badge_color="cyan",
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
        "CFO Watchdog", "VP of Finance", "Respond to the Ops rebuttal using the re-solved numbers.",
        {"verdict": verdict}, f"🤝 {verdict}",
    )
    log_agent_step(
        run_id=run_id, step_order=6,
        agent_name="CFO Watchdog", agent_role="VP of Finance", badge_color="cyan",
        tool_called=f"solve_pulp_milp(min_reliability={RELIABILITY_FLOOR_PCT:g}%)",
        tool_output_summary=verdict, message=msg,
    )
    return {
        "cfo_proposal": chosen,
        "cfo_reliability_floor_pct": RELIABILITY_FLOOR_PCT if concede else 0.0,
        "rebuttal_count": rounds,  # rounds completed (set to 1 when the rebuttal started)
        "rebuttal_pending": False,
        "rebuttal_notes": list(state.get("rebuttal_notes", [])) + [f"CFO: {verdict}"],
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
    br = state.get("blast_radius", {})
    solver_dict = run_pulp_milp_and_monte_carlo(
        state["factory_model"],
        shortfall_units=state["shortfall_units"],
        delay_hours=delay,
        line_speeds=state["line_speeds"],
        order_id=state.get("order_id", "EV-402"),
        sla_penalty_inr=penalty,
        partial_penalty_inr=int(_default(br.get("partial_delay_penalty_inr"), 500_000)),
        deadline_hours=deadline,
        client=br.get("client", "Ather-Grid Mobility Corp"),
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
        "Arbitrator", "Solver & Risk Ranking", "Explain why the winning plan has the lowest risk-adjusted cost.",
        {"winner": winner_id, "cost_inr": w["total_mitigation_cost_inr"], "p_on_time_pct": w["confidence_pct"],
         "expected_cost_inr": w["expected_cost_inr"], "ranking": ranking},
        f"⚖️ {w['name']} wins: ₹{w['total_mitigation_cost_inr']:,} spend, P(on-time) {w['confidence_pct']}% "
        f"(95% CI {w.get('confidence_ci_low_pct')}–{w.get('confidence_ci_high_pct')}%), "
        f"lowest expected cost ₹{w['expected_cost_inr']:,}.",
    )
    log_agent_step(
        run_id=run_id, step_order=7 if state.get("rebuttal_count", 0) > 0 else 5,
        agent_name="Arbitrator", agent_role="Solver & Risk Ranking", badge_color="emerald",
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


def summarize_ai_mode(trace: List[Dict[str, str]]) -> Dict[str, Any]:
    """Collapse the per-node trace into what the UI should disclose."""
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
    override_line2_speed_pct: Optional[int] = None,
    order_id: str = "EV-402",
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
    initial: CascadeGraphState = {
        "run_id": run_id,
        "factory_id": factory_id,
        "raw_message": raw_message,
        "source_channel": source_channel,
        "delay_hours": override_delay_hours,
        "line2_speed_pct": override_line2_speed_pct,
        "line2_temp_celsius": None,
        "shortfall_units": override_shortfall_units,
        "order_id": order_id,
        "rebuttal_notes": [],
        "llm_trace": [],
    }
    final_state = cascade_graph.invoke(initial)
    final_state["ai_mode"] = summarize_ai_mode(final_state.get("llm_trace", []))
    return final_state
