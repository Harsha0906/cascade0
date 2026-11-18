"""
CascadeZero — Strict Pydantic Schemas
Defines schemas for:
  - Gemini 2.5 Flash Structured Extraction (response_schema)
  - Mathematical Solver Inputs & Playbook Outputs
  - Agent Communication & State
  - FastAPI Webhook and REST Payloads
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional
from pydantic import BaseModel, Field


# ─── 1. Gemini Structured Extraction Schemas ─────────────────────────────────

class DisruptionExtraction(BaseModel):
    """
    Pydantic schema passed to Gemini 2.5 Flash `response_schema`
    for deterministic parsing of unstructured WhatsApp/Email/SMS messages.
    """
    source_channel: str = Field(
        default="WHATSAPP",
        description="Source of disruption alert, e.g. WHATSAPP, PLC, ERP, HIGHWAY_WEATHER"
    )
    delay_hours: int = Field(
        default=48,
        description="Estimated inbound shipment delay in hours (e.g. 48 for NH48 flooding)"
    )
    line2_speed_pct: int = Field(
        default=50,
        description="Current speed % of Welding Line 2 (e.g. 50 if throttled, 100 if normal)"
    )
    line2_temp_celsius: float = Field(
        default=89.0,
        description="Operating temperature of Welding Line 2 in degrees Celsius"
    )
    shortfall_units: int = Field(
        default=150,
        description="Net unit shortfall calculated for the active order"
    )
    affected_order_id: str = Field(
        default="EV-402",
        description="Target order ID exposed to disruption, defaults to EV-402"
    )
    crisis_headline: str = Field(
        default="Compound Disruption: NH48 Flood + Line 2 Overheat",
        description="Concise summary headline of the compound crisis"
    )
    raw_summary: str = Field(
        default="",
        description="Brief natural language analysis of the crisis event"
    )


# ─── 2. Optimization & Playbook Schemas ──────────────────────────────────────

class VendorAllocation(BaseModel):
    """Allocation breakdown for a single supplier."""
    supplier_id: str
    supplier_name: str
    tier: str
    units_allocated: int
    cost_per_unit_inr: int
    flat_charter_cost_inr: int = 0
    total_cost_inr: int
    lead_time_hours: int
    route: str
    confirmed: bool = False   # True when the vendor confirmed this offer to the Sourcing Agent


class PlaybookOption(BaseModel):
    """Full recovery playbook evaluated by PuLP and Monte Carlo."""
    id: str  # PLAN_A, PLAN_B, PLAN_C
    name: str
    strategy_type: str  # AIR_CHARTER_MAX_OT | REGIONAL_BALANCED_OT | TARGETED_OT_ONLY | SLA_RENEGOTIATION
    vendor_allocations: List[VendorAllocation]
    overtime_hours: int
    overtime_cost_inr: int
    supplier_cost_inr: int
    total_mitigation_cost_inr: int
    sla_penalty_prevented_inr: int
    net_sla_saved_inr: int
    roi_multiplier: float
    confidence_pct: float
    confidence_ci_low_pct: Optional[float] = None   # 95% Wilson interval on the Monte Carlo estimate
    confidence_ci_high_pct: Optional[float] = None
    p90_finish_hours: Optional[float] = None
    expected_cost_inr: int = 0                       # cost + (1 - P_on_time) * SLA penalty (ranking key)
    feasible: bool = True                            # False when capacity cannot cover the shortfall
    uncovered_units: int = 0
    recommended: bool = False
    badge_label: str = ""
    description: str = ""
    tally_po_payload: Optional[dict[str, Any]] = None
    shift_broadcast_msg: str = ""
    client_sla_notice: str = ""


class SolverResult(BaseModel):
    """Output from the PuLP Optimizer and Monte Carlo Risk Simulator."""
    shortfall_units: int
    delay_hours: int
    line2_speed_pct: int
    order_id: str
    total_sla_exposure_inr: int
    playbooks: List[PlaybookOption]
    recommended_plan_id: str
    solve_duration_ms: float
    lp_status: str
    monte_carlo_iterations: int = 1000
    deadline_hours: float = 38.0
    line2_throughput_gap_units: int = 0
    ranking_rule: str = ""
    capacity_exhausted: bool = False


# ─── 3. Agent Log Schemas ────────────────────────────────────────────────────

class AgentLogEntry(BaseModel):
    """Agent step and reasoning trace logged into Supabase realtime."""
    run_id: str
    step_order: int
    agent_name: str
    agent_role: str
    badge_color: str
    tool_called: str = ""
    tool_output_summary: str = ""
    message: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ─── 4. REST & Webhook Request/Response Schemas ──────────────────────────────

class SimulateCrisisRequest(BaseModel):
    """Payload to trigger crisis simulation."""
    scenario_id: Optional[int] = Field(default=None, ge=1, le=3, description="1, 2, or 3")
    raw_message: Optional[str] = Field(default=None, max_length=2000, description="Custom crisis alert text")
    source_channel: str = Field(default="WEB_DASHBOARD", max_length=64, description="Channel origin")
    override_delay_hours: Optional[int] = Field(default=None, ge=0, le=720)
    override_shortfall_units: Optional[int] = Field(default=None, ge=0, le=100_000)
    override_line2_speed_pct: Optional[int] = Field(default=None, ge=0, le=100)


class PlcTelemetryRequest(BaseModel):
    """Shop-floor machine tick from simulator_plc.py."""
    line_id: str = Field(default="LINE-2", max_length=32)
    speed_pct: int = Field(default=50, ge=0, le=100)
    temp_celsius: float = Field(default=89.0, ge=-50, le=400)
    status: str = Field(default="OVERHEATING_THROTTLED", max_length=64)


class ErpCsvSyncRequest(BaseModel):
    """File upload from legacy Tally or Excel drop folder."""
    filename: str = Field(max_length=255)
    csv_content: str = Field(max_length=2_000_000)


class LiveHighwayCheckRequest(BaseModel):
    """Highway corridor check."""
    corridor: str = "NH48 Chennai-Bengaluru"
    city: str = "Vellore"


class ExecutePlanRequest(BaseModel):
    """
    HITL execution approval. The server executes the playbook it computed for `run_id`;
    costs and allocations are never accepted from the client.
    """
    run_id: str
    playbook_id: str
    approved_by: str = Field(default="dashboard-operator", max_length=120)


class ExecutionReceiptResponse(BaseModel):
    """Execution receipt with draft PO & notices (nothing is sent to suppliers automatically)."""
    success: bool
    run_id: str
    po_number: str
    playbook_id: str
    order_id: str
    approved_by: str
    total_cost_inr: int
    net_sla_saved_inr: int
    confidence_pct: float
    tally_xml_payload: str
    tally_json_payload: dict[str, Any]
    shift_broadcast_msg: str
    client_sla_notice: str
    executed_at: str
    already_executed: bool = False
    dispatch_note: str = (
        "Drafts generated. Supplier POs, shift notices and client notices are NOT sent automatically; "
        "import the Tally XML and send notices through your normal channels."
    )


class SourcingStartRequest(BaseModel):
    """Start the Sourcing Agent on a computed run (defaults to the recommended playbook)."""
    run_id: str = Field(max_length=64)
    playbook_id: Optional[str] = Field(default=None, max_length=16)


class SourcingReplyRequest(BaseModel):
    """A vendor's reply, entered by an operator (e.g. after a phone call) or a simulated vendor."""
    supplier_id: str = Field(max_length=32)
    text: str = Field(min_length=1, max_length=1000)
    entered_by: str = Field(default="dashboard-operator", max_length=120)
