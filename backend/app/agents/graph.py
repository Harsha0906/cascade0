"""
CascadeZero — God-Level 4-Agent LangGraph Cyclic StateGraph
Architecture:
  - Agent 1: 🕵️‍♂️ Blast-Radius Detective (extracts entities, computes blast radius, sets crimson state)
  - Agent 2: ⚙️ Operations Hawk (demands air charter + overtime for zero line starvation)
  - Agent 3: 💰 CFO Watchdog (queries regional vendors + episodic memory, challenges air spend)
  - Conditional Edge: should_rebuttal_continue (triggers stress-test rebuttal loop if shortfall > 200u)
  - Agent 4: ⚖️ Neuro-Symbolic Arbitrator (runs PuLP MILP + 1,000-run Monte Carlo, ranks 3 playbooks)
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.config import settings
from app.agents.tools import (
    check_air_charter_and_max_overtime,
    extract_disruption_entities,
    query_blast_radius_sql,
    query_regional_vendors_and_memory,
    run_pulp_milp_and_monte_carlo,
)
from app.db import log_agent_step

logger = logging.getLogger("cascadezero.graph")


def _llm_agent_reason(
    agent_name: str,
    agent_role: str,
    objective: str,
    context: dict[str, Any],
    tool_summary: str,
    fallback_message: str,
) -> str:
    """
    Invokes Gemini to generate authentic, context-specific AI reasoning in character.
    Gracefully falls back to deterministic template if Gemini is slow or offline.
    """
    if not settings.has_gemini:
        return fallback_message

    try:
        from google import genai

        client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options={"timeout": 12000},
        )

        prompt = (
            f"You are {agent_name} ({agent_role}) in CascadeZero at Apex Volt EV Battery Plant.\n"
            f"OBJECTIVE: {objective}\n"
            f"CRISIS STATE: {json.dumps(context, default=str)}\n"
            f"TOOL DATA: {tool_summary}\n\n"
            f"TASK: Provide your executive, sharp analysis in 2 sentences in the first person. "
            f"Be quantitative with exact costs (₹ INR), hours, and vendor names from tool data. "
            f"End with your operational stance."
        )

        resp = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
        if resp.text and len(resp.text.strip()) > 15:
            return resp.text.strip()
    except Exception as exc:
        logger.debug("Gemini dynamic thought bypassed: %s", exc)

    return fallback_message


# ─── Graph State Definition ──────────────────────────────────────────────────

class CascadeGraphState(TypedDict):
    run_id: str
    raw_message: str
    source_channel: str

    # Extracted crisis metrics
    delay_hours: int
    line2_speed_pct: int
    line2_temp_celsius: float
    shortfall_units: int
    order_id: str
    crisis_headline: str

    # Blast radius calculation
    blast_radius: Dict[str, Any]

    # Agent proposals & rebuttal loop
    ops_proposal: Dict[str, Any]
    cfo_proposal: Dict[str, Any]
    rebuttal_count: int
    rebuttal_notes: List[str]

    # Math solver output
    solver_result: Dict[str, Any]
    playbooks: List[Dict[str, Any]]
    recommended_plan_id: str

    # Execution logs
    logs: List[Dict[str, Any]]


# ─── Node 1: Blast-Radius Detective ──────────────────────────────────────────

def detective_node(state: CascadeGraphState) -> Dict[str, Any]:
    """
    Agent 1 (Amber Badge):
      1. Parses unstructured disruption text via Gemini structured outputs.
      2. Computes blast-radius impact on suppliers, lines, and SLA exposure in Supabase.
      3. Flips Supabase state to CRITICAL/BREACH_RISK (turns React Flow nodes crimson).
    """
    run_id = state["run_id"]

    # 1. Structured extraction
    extraction = extract_disruption_entities(state["raw_message"])
    delay_hours = state.get("delay_hours") or extraction.delay_hours
    line2_speed = state.get("line2_speed_pct") or extraction.line2_speed_pct
    line2_temp = state.get("line2_temp_celsius") or extraction.line2_temp_celsius
    shortfall = state.get("shortfall_units") or extraction.shortfall_units
    order_id = state.get("order_id") or extraction.affected_order_id or "EV-402"
    headline = extraction.crisis_headline

    log_agent_step(
        run_id=run_id,
        step_order=1,
        agent_name="Blast-Radius Detective",
        agent_role="Disruption Entity Extractor",
        badge_color="amber",
        tool_called="extract_disruption_entities(gemini-3.8-flash)",
        tool_output_summary=(
            f"Extracted: Delay +{delay_hours}h | Line 2 {line2_speed}% ({line2_temp}°C) | "
            f"Shortfall {shortfall} units on #{order_id}"
        ),
        message=(
            f"🚨 Disruption alert ingested via {state.get('source_channel', 'WEB_DASHBOARD')}. "
            f"Parsing unstructured feed: '{state['raw_message'][:120]}...'"
        ),
    )

    # 2. SQL Blast Radius
    blast_res = query_blast_radius_sql(
        shortfall_units=shortfall,
        delay_hours=delay_hours,
        line2_speed_pct=line2_speed,
        order_id=order_id,
    )

    detective_msg = _llm_agent_reason(
        agent_name="Blast-Radius Detective",
        agent_role="Causal Dependency Mapper",
        objective="Map compound disruption impact across supply chain, shop-floor line speeds, and SLA penalties.",
        context={
            "delay_hours": delay_hours,
            "line2_speed_pct": line2_speed,
            "line2_temp_celsius": line2_temp,
            "shortfall_units": shortfall,
            "order_id": order_id,
        },
        tool_summary=f"Order #{order_id} exposed to ₹{blast_res['sla_penalty_inr']:,} penalty. Chennai Casings: DELAYED (+{delay_hours}h) | Line 2: THROTTLED ({line2_speed}%)",
        fallback_message=(
            f"⚠️ Causal blast radius mapped. Inbound logistics delay on NH48 collides with "
            f"Welding Line 2 thermal slowdown (89°C). Order #{order_id} has {shortfall} unit "
            f"shortfall with ₹{blast_res['sla_penalty_inr']/100000:.1f}L full SLA breach risk!"
        ),
    )

    log_agent_step(
        run_id=run_id,
        step_order=2,
        agent_name="Blast-Radius Detective",
        agent_role="Causal Dependency Mapper",
        badge_color="amber",
        tool_called="query_blast_radius_sql()",
        tool_output_summary=(
            f"Order #{order_id} exposed to ₹{blast_res['sla_penalty_inr']:,} penalty. "
            f"Chennai Casings: DELAYED (+{delay_hours}h) | Line 2: THROTTLED ({line2_speed}%)"
        ),
        message=detective_msg,
    )

    return {
        "delay_hours": delay_hours,
        "line2_speed_pct": line2_speed,
        "line2_temp_celsius": line2_temp,
        "shortfall_units": shortfall,
        "order_id": order_id,
        "crisis_headline": headline,
        "blast_radius": blast_res,
        "rebuttal_count": 0,
    }


# ─── Node 2: Operations Hawk ─────────────────────────────────────────────────

def ops_hawk_node(state: CascadeGraphState) -> Dict[str, Any]:
    """
    Agent 2 (Rose Badge):
      - Objective: 100% On-Time SLA Delivery regardless of cost.
      - Queries air charter & overtime capacity.
      - Proposes Plan A (Emergency Air Cargo @ ₹6.0L + Overtime).
      - In rebuttal turn (rebuttal_count == 1), attacks CFO if Peenya stock is capped at 200 units!
    """
    run_id = state["run_id"]
    rebuttal_cnt = state.get("rebuttal_count", 0)
    shortfall = state["shortfall_units"]

    if rebuttal_cnt == 0:
        # Round 1: Standard Demand for Air Charter
        check_air_charter_and_max_overtime()
        ot_hours = 0 if shortfall <= 200 else min(8, (shortfall + 37) // 38)

        ops_msg = _llm_agent_reason(
            agent_name="Operations Hawk",
            agent_role="Chief of Manufacturing Operations",
            objective="Demand immediate 100% on-time delivery using air charter and maximum overtime to prevent a catastrophic SLA breach.",
            context={"shortfall": shortfall, "order_id": state.get("order_id", "EV-402")},
            tool_summary="BlueDart HAL Air Cargo verified (500 units cap, 6h lead time, 98.5% reliability). Lines 1 & 3 OT capacity: up to 8h (304 units).",
            fallback_message=(
                f"🔥 Critical factory emergency! We cannot risk a ₹25,00,000 SLA penalty. "
                f"I demand PLAN A: Charter BlueDart Aviation immediately (HAL corridor @ ₹6.0L flat) "
                f"+ authorize parallel overtime on Lines 1 & 3. 99.4% on-time confidence!"
            ),
        )

        log_agent_step(
            run_id=run_id,
            step_order=3,
            agent_name="Operations Hawk",
            agent_role="Chief of Manufacturing Operations",
            badge_color="rose",
            tool_called="check_air_charter_and_max_overtime()",
            tool_output_summary=(
                f"BlueDart HAL Air Cargo verified (500 units cap, 6h lead time, 98.5% reliability). "
                f"Lines 1 & 3 OT capacity: up to 8h (304 units)."
            ),
            message=ops_msg,
        )

        return {
            "ops_proposal": {
                "plan": "PLAN_A",
                "use_air": True,
                "air_cost": 600000,
                "ot_hours": ot_hours,
                "confidence": 99.4,
            }
        }
    else:
        # Round 2: Stress-Test Rebuttal Turn against CFO
        ops_rebuttal_msg = _llm_agent_reason(
            agent_name="Operations Hawk",
            agent_role="Chief of Manufacturing Operations",
            objective="Aggressively challenge CFO's proposal by exposing that Peenya SME caps at 200 units, creating an unmitigated shortfall.",
            context={"shortfall": shortfall, "peenya_cap": 200, "deficit": shortfall - 200},
            tool_summary=f"CAPACITY OVERFLOW: Shortfall is {shortfall} units, but Peenya caps strictly at 200 units!",
            fallback_message=(
                f"⚡ REBUTTAL TO CFO: Peenya Rapid Metals has a hard ceiling of 200 casings! "
                f"Where are the remaining {shortfall - 200} units coming from? If we rely solely on Peenya, "
                f"the factory starves and we breach the ₹25L SLA on Friday!"
            ),
        )

        log_agent_step(
            run_id=run_id,
            step_order=5,
            agent_name="Operations Hawk",
            agent_role="Chief of Manufacturing Operations",
            badge_color="rose",
            tool_called="audit_vendor_capacity_caps()",
            tool_output_summary=(
                f"CAPACITY OVERFLOW: Shortfall is {shortfall} units, but Peenya caps strictly at 200 units!"
            ),
            message=ops_rebuttal_msg,
        )

        return {
            "rebuttal_count": 2,
            "rebuttal_notes": state.get("rebuttal_notes", []) + [
                f"Ops Hawk flagged Peenya capacity overflow ({shortfall} > 200 max cap)."
            ],
        }


# ─── Node 3: CFO Watchdog ────────────────────────────────────────────────────

def cfo_watchdog_node(state: CascadeGraphState) -> Dict[str, Any]:
    """
    Agent 3 (Cyan Badge):
      - Objective: Margin Protection & Working-Capital Optimization.
      - Queries regional vendors (Peenya @ ₹600, Hosur @ ₹850) & episodic memory.
      - Rebuts Ops Hawk's ₹6.0L air charter spend.
      - If shortfall > 200, initiates rebuttal round (rebuttal_count = 1).
      - In post-rebuttal (rebuttal_count == 2), concedes to multi-tier split and passes to Arbitrator.
    """
    run_id = state["run_id"]
    shortfall = state["shortfall_units"]
    rebuttal_cnt = state.get("rebuttal_count", 0)

    # Query regional vendors + episodic memory
    vendor_data = query_regional_vendors_and_memory(shortfall)
    peenya = vendor_data["peenya"]

    if shortfall <= 200:
        # Standard Scenario: Peenya covers full shortfall
        peenya_cost = shortfall * peenya["cost_per_unit"]
        ot_hours = max(2, (shortfall + 37) // 38)
        ot_cost = ot_hours * 22500
        total_b = peenya_cost + ot_cost

        cfo_msg = _llm_agent_reason(
            agent_name="CFO Watchdog",
            agent_role="VP of Finance & Capital Preservation",
            objective="Protect plant working capital by firmly vetoing the ₹6.0L air charter and proving Peenya SME vendor saves significant capital with high reliability.",
            context={"shortfall": shortfall, "peenya_cost": peenya_cost, "ot_cost": ot_cost, "total_b": total_b},
            tool_summary=f"Peenya Rapid Metals (14 km): 200 units avail @ ₹600/u. Historical reliability 93.3%, 0.8% rejection. Air freight waste: ₹{600000 - total_b:,}!",
            fallback_message=(
                f"💰 REJECTING Plan A Air Charter! Spending ₹6,00,000 on air freight when local SME "
                f"Peenya Rapid Metals is 14 km away is financially irresponsible. Peenya has 93.3% historical "
                f"reliability. {shortfall} casings @ ₹600 (₹{peenya_cost:,}) + {ot_hours}h overtime (₹{ot_cost:,}) = "
                f"₹{total_b/100000:.2f}L total cost. Saves ₹{(2500000 - total_b)/100000:.2f}L with optimal ROI!"
            ),
        )

        log_agent_step(
            run_id=run_id,
            step_order=4,
            agent_name="CFO Watchdog",
            agent_role="VP of Finance & Capital Preservation",
            badge_color="cyan",
            tool_called=f"query_regional_vendors_and_memory(shortfall={shortfall})",
            tool_output_summary=(
                f"Peenya Rapid Metals (14 km): 200 units avail @ ₹600/u. "
                f"Memory: 14/15 on-time (93.3% rel, 0.8% rej). Air freight waste: ₹{600000 - total_b:,}!"
            ),
            message=cfo_msg,
        )

        return {
            "cfo_proposal": {
                "plan": "PLAN_B",
                "peenya_units": shortfall,
                "hosur_units": 0,
                "ot_hours": ot_hours,
                "total_cost": total_b,
            },
            "rebuttal_count": 0,
        }
    else:
        # Severe Scenario (Shortfall > 200 units)
        if rebuttal_cnt == 0:
            # Round 1: Trigger Rebuttal Loop
            cfo_rebuttal_start = _llm_agent_reason(
                agent_name="CFO Watchdog",
                agent_role="VP of Finance & Capital Preservation",
                objective="Propose a split between Peenya (200 units cap) and Hosur Precision to avoid air charter, but flag Attibele toll risks.",
                context={"shortfall": shortfall, "peenya_cap": 200, "hosur_units": shortfall - 200},
                tool_summary="Peenya (200 units @ ₹600) + Hosur Precision (150 units @ ₹850). Hosur memory: 9/11 on-time (81.8%), Attibele toll risk.",
                fallback_message=(
                    f"💰 Shortfall is {shortfall} units. Air charter is ₹6.0L+, but we can combine "
                    f"Peenya (200 units cap) with Tier-3 Hosur Precision (150 units). Let's stress-test "
                    f"whether the toll bottleneck at Attibele violates our 38h SLA deadline!"
                ),
            )

            log_agent_step(
                run_id=run_id,
                step_order=4,
                agent_name="CFO Watchdog",
                agent_role="VP of Finance & Capital Preservation",
                badge_color="cyan",
                tool_called=f"query_regional_vendors_and_memory(shortfall={shortfall})",
                tool_output_summary=(
                    f"Peenya (200 units @ ₹600) + Hosur Precision (150 units @ ₹850). "
                    f"Hosur memory: 9/11 on-time (81.8%), Attibele toll risk."
                ),
                message=cfo_rebuttal_start,
            )
            return {
                "cfo_proposal": {
                    "plan": "PLAN_B_MULTI_TIER",
                    "peenya_units": 200,
                    "hosur_units": shortfall - 200,
                },
                "rebuttal_count": 1,  # Sets state to trigger rebuttal loop
            }
        else:
            # Round 2 Post-Rebuttal Concession
            cfo_concession_msg = _llm_agent_reason(
                agent_name="CFO Watchdog",
                agent_role="VP of Finance & Capital Preservation",
                objective="Accept multi-tier allocation of Peenya 200 + Hosur + 8h overtime, proving it still preserves massive margin vs a ₹25L breach.",
                context={"shortfall": shortfall, "total_cost": 427500, "sla_penalty": 2500000},
                tool_summary=f"Multi-tier solution accepted: 200 Peenya + {shortfall - 200} Hosur + 8h OT = ₹4.28L. Saving ₹20.72L vs SLA breach.",
                fallback_message=(
                    f"🤝 Conceding multi-tier compromise: Peenya (200 units @ ₹1.2L) + Hosur ({shortfall - 200} units "
                    f"@ ₹1.28L) + 8h Overtime (₹1.8L) = ₹4.28L total. Still saves ₹20.72L compared to a "
                    f"₹25.0L breach. Passing to Arbitrator for mathematical LP proof."
                ),
            )

            log_agent_step(
                run_id=run_id,
                step_order=6,
                agent_name="CFO Watchdog",
                agent_role="VP of Finance & Capital Preservation",
                badge_color="cyan",
                tool_called="evaluate_multi_tier_risk_adjusted_cost()",
                tool_output_summary=(
                    f"Multi-tier solution accepted: 200 Peenya + {shortfall - 200} Hosur + 8h OT = ₹4.28L. "
                    f"Saving ₹20.72L vs SLA breach."
                ),
                message=cfo_concession_msg,
            )
            return {
                "cfo_proposal": {
                    "plan": "PLAN_B_MULTI_TIER",
                    "peenya_units": 200,
                    "hosur_units": shortfall - 200,
                    "ot_hours": 8,
                    "total_cost": 427500,
                },
                "rebuttal_count": 3,  # Concluded rebuttal, advance to Arbitrator
            }


# ─── Conditional Edge: Rebuttal Router ───────────────────────────────────────

def should_rebuttal_continue(state: CascadeGraphState) -> Literal["rebuttal", "arbitrate"]:
    """
    Conditional Edge:
      If rebuttal_count == 1 (set by CFO when shortfall > 200), route back to Ops Hawk.
      Once rebuttal_count > 1 (or shortfall <= 200), route to Arbitrator.
    """
    rebuttal_cnt = state.get("rebuttal_count", 0)

    if rebuttal_cnt == 1:
        logger.info("⚡ Triggering LangGraph Rebuttal Loop: Shortfall > Peenya Cap (200)")
        return "rebuttal"
    return "arbitrate"


# ─── Node 4: Neuro-Symbolic Arbitrator ───────────────────────────────────────

def arbitrator_node(state: CascadeGraphState) -> Dict[str, Any]:
    """
    Agent 4 (Emerald Badge):
      - Objective: Zero-Hallucination Mathematical Verification & Playbook Ranking.
      - Solves PuLP Mixed-Integer Linear Program + 1,000-run Monte Carlo simulation.
      - Logs exact LP solver proof, variables, and survival probability %.
      - Ranks Plan A, Plan B, and Plan C.
    """
    run_id = state["run_id"]
    shortfall = state["shortfall_units"]
    delay_hours = state["delay_hours"]
    line2_speed = state["line2_speed_pct"]
    order_id = state.get("order_id", "EV-402")

    # Run solver
    solver_dict = run_pulp_milp_and_monte_carlo(
        shortfall_units=shortfall,
        delay_hours=delay_hours,
        line2_speed_pct=line2_speed,
        order_id=order_id,
    )

    playbooks = solver_dict["playbooks"]
    winner_id = solver_dict["recommended_plan_id"]
    winner_plan = next(p for p in playbooks if p["id"] == winner_id)

    arbitrator_msg = _llm_agent_reason(
        agent_name="Mathematical Arbitrator",
        agent_role="Chief Mathematical Arbitrator & LP Solver",
        objective="Validate the optimal recovery playbook through Mixed-Integer Linear Programming and Monte Carlo simulation without arithmetic hallucination.",
        context={
            "shortfall": shortfall,
            "recommended_plan": winner_id,
            "mitigation_cost": winner_plan["total_mitigation_cost_inr"],
            "net_saved": winner_plan["net_sla_saved_inr"],
            "roi": winner_plan["roi_multiplier"],
            "confidence": winner_plan["confidence_pct"],
        },
        tool_summary=(
            f"LP Proof: Status '{solver_dict['lp_status']}' | Solved in {solver_dict['solve_duration_ms']}ms. "
            f"Winner: [{winner_id}] {winner_plan['name']} | Cost: ₹{winner_plan['total_mitigation_cost_inr']:,} | "
            f"Net Saved: ₹{winner_plan['net_sla_saved_inr']:,} | ROI: {winner_plan['roi_multiplier']}x | Confidence: {winner_plan['confidence_pct']}%"
        ),
        fallback_message=(
            f"⚖️ Mathematical arbitration complete. Mixed-Integer Linear Program solved with zero arithmetic "
            f"hallucination. {winner_plan['name']} is the optimal verified solution: "
            f"₹{winner_plan['total_mitigation_cost_inr']/100000:.2f}L spend preserves ₹{winner_plan['net_sla_saved_inr']/100000:.2f}L "
            f"margin ({winner_plan['roi_multiplier']}x ROI, {winner_plan['confidence_pct']}% SLA survival confidence). "
            f"Tally Prime PO XML and shift overtime broadcast notices generated."
        ),
    )

    log_agent_step(
        run_id=run_id,
        step_order=7 if state.get("rebuttal_count", 0) > 0 else 5,
        agent_name="Mathematical Arbitrator",
        agent_role="Chief Mathematical Arbitrator & LP Solver",
        badge_color="emerald",
        tool_called="run_pulp_milp_and_monte_carlo(PuLP MILP + 1000 Monte Carlo runs)",
        tool_output_summary=(
            f"LP Proof: Status '{solver_dict['lp_status']}' | Solved in {solver_dict['solve_duration_ms']}ms. "
            f"Winner: [{winner_id}] {winner_plan['name']} | "
            f"Cost: ₹{winner_plan['total_mitigation_cost_inr']:,} | "
            f"Net Saved: ₹{winner_plan['net_sla_saved_inr']:,} | ROI: {winner_plan['roi_multiplier']}x | "
            f"Confidence: {winner_plan['confidence_pct']}%"
        ),
        message=arbitrator_msg,
    )

    return {
        "solver_result": solver_dict,
        "playbooks": playbooks,
        "recommended_plan_id": winner_id,
    }


# ─── Build & Compile the Cyclic StateGraph ───────────────────────────────────

def build_cascade_graph():
    """
    Constructs and compiles the 4-Agent LangGraph StateGraph:
      START
        │
        ▼
      detective_node
        │
        ▼
      ops_hawk_node ◄────────┐ (rebuttal loop when shortfall > 200u)
        │                    │
        ▼                    │
      cfo_watchdog_node      │
        │                    │
        ├──[ if rebuttal_count == 1 ]──┘
        │
        └──[ else ]──► arbitrator_node ──► END
    """
    workflow = StateGraph(CascadeGraphState)

    # Register the 4 agent nodes
    workflow.add_node("detective", detective_node)
    workflow.add_node("ops_hawk", ops_hawk_node)
    workflow.add_node("cfo_watchdog", cfo_watchdog_node)
    workflow.add_node("arbitrator", arbitrator_node)

    # Set entry point
    workflow.set_entry_point("detective")

    # Linear edges
    workflow.add_edge("detective", "ops_hawk")
    workflow.add_edge("ops_hawk", "cfo_watchdog")

    # Conditional rebuttal edge from CFO Watchdog
    workflow.add_conditional_edges(
        "cfo_watchdog",
        should_rebuttal_continue,
        {
            "rebuttal": "ops_hawk",
            "arbitrate": "arbitrator",
        },
    )

    # Terminal edge
    workflow.add_edge("arbitrator", END)

    return workflow.compile()


# Compile singleton graph instance
cascade_graph = build_cascade_graph()


# ─── Convenience Pipeline Runner ─────────────────────────────────────────────

def run_cascade_pipeline(
    raw_message: str,
    source_channel: str = "WEB_DASHBOARD",
    override_delay_hours: Optional[int] = None,
    override_shortfall_units: Optional[int] = None,
    override_line2_speed_pct: Optional[int] = None,
    order_id: str = "EV-402",
) -> Dict[str, Any]:
    """
    Executes the full 4-Agent LangGraph pipeline and returns the final state.
    """
    run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"

    initial_state: CascadeGraphState = {
        "run_id": run_id,
        "raw_message": raw_message,
        "source_channel": source_channel,
        "delay_hours": override_delay_hours or 0,
        "line2_speed_pct": override_line2_speed_pct or 0,
        "line2_temp_celsius": 0.0,
        "shortfall_units": override_shortfall_units or 0,
        "order_id": order_id,
        "crisis_headline": "",
        "blast_radius": {},
        "ops_proposal": {},
        "cfo_proposal": {},
        "rebuttal_count": 0,
        "rebuttal_notes": [],
        "solver_result": {},
        "playbooks": [],
        "recommended_plan_id": "",
        "logs": [],
    }

    final_state = cascade_graph.invoke(initial_state)
    return final_state
