"""
CascadeZero — Mathematical Optimization (PuLP) & Monte Carlo Risk Engine

Single source of truth for:
  - A mixed-integer program (PuLP) that allocates casing supply across vendors and
    schedules overtime on Lines 1 & 3, subject to vendor capacity, lead-time
    feasibility against the order deadline, and Line 2 throughput loss.
  - A seeded Monte Carlo simulation that estimates the probability each plan
    lands before the deadline.
  - Plan ranking by *risk-adjusted expected cost*:
        E[cost] = mitigation_cost + (1 - P(on-time)) * SLA_penalty
    The recommended plan is whichever minimises E[cost]. No plan is hard-coded
    as the winner.

Modelling assumptions are explicit constants below. They describe the demo
plant (Apex Volt) and are NOT learned from data. Replace them with values from
the `suppliers` / `production_lines` tables before using this on a real plant.
"""

from __future__ import annotations

import math
import random
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape as _xml_escape

import pulp

from app.schemas import (
    PlaybookOption,
    SolverResult,
    VendorAllocation,
)

# ─── Demo-plant constants (assumptions, not data) ────────────────────────────
DEFAULT_ORDER_ID = "EV-402"
DEFAULT_CLIENT = "Ather-Grid Mobility Corp"
DEFAULT_COMPANY_NAME = "Apex Volt EV Battery Plant"
DEFAULT_SLA_PENALTY_INR = 2_500_000      # ₹25,00,000 full breach penalty
DEFAULT_PARTIAL_PENALTY_INR = 500_000    # ₹5,00,000 negotiated delay fee
DEFAULT_HOURS_REMAINING = 38             # hours to the committed dispatch deadline
STOCK_ITEM_NAME = "Aluminium Battery Casing"

QA_DISPATCH_HOURS = 2.5                  # inspection + dispatch after last unit is built

# Line 2 throughput loss model: lost units = rated_uph * (1 - speed) * production hours in window
LINE2_RATED_UNITS_PER_HOUR = 19
LINE2_PRODUCTION_HOURS_IN_WINDOW = 16    # two shifts fall inside the 38h window

# Overtime on parallel Lines 1 & 3
OVERTIME_COST_PER_HOUR = 22_500
OVERTIME_UNITS_PER_HOUR = 38
MAX_OVERTIME_HOURS = 8

# On-hand safety stock that an overtime-only plan may draw on (assumption)
SAFETY_STOCK_UNITS = 50

# Penalty per unit left uncovered by the optimiser. Large enough that slack is only
# used when the problem is genuinely infeasible; it lets us report *how* infeasible.
UNCOVERED_UNIT_PENALTY = 1_000_000


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


PEENYA = Vendor(
    "SUP-PNY-02", "Peenya Rapid Metals (Local SME Vendor)", "TIER-2",
    "Peenya Industrial Area (14 km)", 200, 600, 0, 4, 0.45, 6.0, (1.0, 2.5), 93.3, (1.5, 3.0), 2.0,
)
HOSUR = Vendor(
    "SUP-HSR-03", "Hosur Precision Castings", "TIER-3",
    "Hosur Industrial Corridor (42 km)", 180, 850, 0, 8, 1.1, 8.0, (2.0, 4.0), 81.8, (2.5, 5.0), 4.0,
)
AIR = Vendor(
    "SUP-AIR-04", "BlueDart Aviation Charter", "EMERGENCY-AIR",
    "HAL/KEMPEGOWDA Air Cargo Corridor", 500, 0, 600_000, 6, 0.25, 2.0, (1.0, 2.0), 98.5, (1.0, 2.0), 4.5,
)
VENDORS: List[Vendor] = [PEENYA, HOSUR, AIR]


def effective_vendors(overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Vendor]:
    """
    Apply per-run vendor overrides (e.g. offers confirmed by the Sourcing Agent).
    Override keys: max_units, unit_cost, flat_cost, lead_hours. max_units <= 0 removes the vendor
    (declined or unreachable). Vendors without an override keep their catalogue assumptions.
    """
    if not overrides:
        return list(VENDORS)
    out: List[Vendor] = []
    for v in VENDORS:
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
    return out

# Back-compat aliases (imported elsewhere in the codebase)
PEENYA_MAX_CAP = PEENYA.max_units
PEENYA_UNIT_COST = PEENYA.unit_cost
HOSUR_MAX_CAP = HOSUR.max_units
HOSUR_UNIT_COST = HOSUR.unit_cost
AIR_FLAT_COST = AIR.flat_cost


class SolverInputError(ValueError):
    """Raised for inputs the model cannot represent (negative shortfall, etc.)."""


def line2_throughput_gap(line2_speed_pct: int) -> int:
    """Units Line 2 will fail to build inside the window at its throttled speed."""
    speed = min(100, max(0, line2_speed_pct)) / 100.0
    return int(math.ceil(LINE2_RATED_UNITS_PER_HOUR * (1.0 - speed) * LINE2_PRODUCTION_HOURS_IN_WINDOW))


# ─── 1. Mixed-Integer Program ────────────────────────────────────────────────

def _new_var(prob: pulp.LpProblem, name: str, low=None, up=None, cat="Continuous"):
    """Create a variable in a way that works on PuLP 2.x and 4.x."""
    if hasattr(prob, "add_variable"):
        return prob.add_variable(name, lowBound=low, upBound=up, cat=cat)
    return pulp.LpVariable(name, low, up, cat)


def _status_name(solve_result: Any, prob: pulp.LpProblem) -> str:
    """Normalise the solve status across PuLP 2.x (int + LpStatus dict) and 4.x (LpSolveStats)."""
    status = getattr(solve_result, "status", None)
    if status is not None and hasattr(status, "name"):
        return status.name
    code = getattr(prob, "status", solve_result)
    table = getattr(pulp, "LpStatus", {})
    return table.get(code, str(code))


def _val(var) -> float:
    v = var.value() if hasattr(var, "value") else pulp.value(var)
    return float(v or 0.0)


def solve_pulp_milp(
    shortfall_units: int,
    delay_hours: int = 0,
    line2_speed_pct: int = 100,
    deadline_hours: float = DEFAULT_HOURS_REMAINING,
    force_air: Optional[bool] = None,
    allowed_vendor_ids: Optional[List[str]] = None,
    min_vendor_reliability_pct: float = 0.0,
    vendor_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Minimise   Σ unit_cost_v·x_v + Σ flat_cost_v·y_v + OT_rate·h + BIG·(u_mat + u_cap)
    subject to
      Σ x_v + u_mat               >= material_shortfall          (casings to source)
      OT_UPH·h + u_cap            >= line2_throughput_gap        (lost Line 2 output)
      x_v                         <= cap_v · y_v                 (vendor used only if engaged)
      lead_v·y_v + h + QA         <= deadline                    (arrival + build + QA fits)
      x_v ∈ Z+, y_v ∈ {0,1}, h ∈ Z ∩ [0, 8], u ≥ 0

    `delay_hours` is the upstream delay that *caused* the shortfall; it is already
    reflected in `shortfall_units` and is recorded for traceability only.

    Returns a dict with allocations, cost, `feasible` (no slack used) and the raw
    solver status. Infeasibility is reported, never hidden.
    """
    if shortfall_units < 0:
        raise SolverInputError("shortfall_units must be >= 0")
    if deadline_hours <= QA_DISPATCH_HOURS:
        raise SolverInputError("deadline_hours must exceed QA/dispatch time")

    gap = line2_throughput_gap(line2_speed_pct)
    vendors = [
        v for v in effective_vendors(vendor_overrides)
        if (allowed_vendor_ids is None or v.supplier_id in allowed_vendor_ids)
        and v.reliability_pct >= min_vendor_reliability_pct
    ]

    prob = pulp.LpProblem("CascadeZero_Recovery", pulp.LpMinimize)
    x = {v.supplier_id: _new_var(prob, f"x_{v.supplier_id}", 0, v.max_units, "Integer") for v in vendors}
    y = {v.supplier_id: _new_var(prob, f"y_{v.supplier_id}", cat="Binary") for v in vendors}
    h = _new_var(prob, "h_ot", 0, MAX_OVERTIME_HOURS, "Integer")
    u_mat = _new_var(prob, "u_material", 0, None)
    u_cap = _new_var(prob, "u_capacity", 0, None)

    prob += (
        pulp.lpSum(v.unit_cost * x[v.supplier_id] + v.flat_cost * y[v.supplier_id] for v in vendors)
        + OVERTIME_COST_PER_HOUR * h
        + UNCOVERED_UNIT_PENALTY * (u_mat + u_cap),
        "Total_Recovery_Cost",
    )
    prob += (pulp.lpSum(x.values()) + u_mat >= shortfall_units, "Material_Coverage")
    prob += (OVERTIME_UNITS_PER_HOUR * h + u_cap >= gap, "Line2_Throughput_Recovery")
    for v in vendors:
        sid = v.supplier_id
        prob += (x[sid] <= v.max_units * y[sid], f"Engage_{sid}")
        prob += (v.lead_hours * y[sid] + h + QA_DISPATCH_HOURS <= deadline_hours, f"Deadline_{sid}")
    prob += (h + QA_DISPATCH_HOURS <= deadline_hours, "Deadline_Overtime")
    if force_air is not None and AIR.supplier_id in y:
        prob += (y[AIR.supplier_id] == (1 if force_air else 0), "Policy_Air")
        if force_air and shortfall_units > 0:
            prob += (x[AIR.supplier_id] >= 1, "Policy_Air_Used")
    elif force_air:
        # The air charter is unavailable for this run (declined, or below the reliability floor).
        return {
            "status": "Infeasible: air charter unavailable",
            "solver_status": "NotAttempted",
            "feasible": False,
            "uncovered_material_units": shortfall_units,
            "uncovered_capacity_units": gap,
            "line2_throughput_gap_units": gap,
            "units_by_vendor": {},
            "peenya_units": 0,
            "hosur_units": 0,
            "air_charter": False,
            "overtime_hours": 0,
            "total_cost_inr": 0,
        }

    solver = None
    if hasattr(pulp, "HiGHS"):
        highs = pulp.HiGHS(msg=False)
        if highs.available():
            solver = highs
    if solver is None:
        solver = pulp.PULP_CBC_CMD(msg=False)
    status = _status_name(prob.solve(solver), prob)
    if status == "Infeasible":
        # Coverage has slack, so this can only come from a hard rule: a policy (e.g. a forced
        # air charter) whose lead time cannot meet the deadline. Report it as an unusable plan.
        gap_left = gap if gap > 0 else 0
        return {
            "status": "Infeasible: policy cannot meet the deadline",
            "solver_status": status,
            "feasible": False,
            "uncovered_material_units": shortfall_units,
            "uncovered_capacity_units": gap_left,
            "line2_throughput_gap_units": gap,
            "units_by_vendor": {},
            "peenya_units": 0,
            "hosur_units": 0,
            "air_charter": False,
            "overtime_hours": 0,
            "total_cost_inr": 0,
        }
    if status != "Optimal":
        raise RuntimeError(f"MILP solver did not reach optimality (status={status})")

    units = {sid: int(round(_val(var))) for sid, var in x.items()}
    engaged = {sid: int(round(_val(var))) == 1 and units[sid] > 0 for sid, var in y.items()}
    ot_hours = int(round(_val(h)))
    uncovered_material = int(math.ceil(_val(u_mat) - 1e-6))
    uncovered_capacity = int(math.ceil(_val(u_cap) - 1e-6))

    cost = sum(
        v.unit_cost * units[v.supplier_id] + (v.flat_cost if engaged[v.supplier_id] else 0)
        for v in vendors
    ) + ot_hours * OVERTIME_COST_PER_HOUR

    feasible = uncovered_material == 0 and uncovered_capacity == 0
    return {
        "status": "Optimal" if feasible else "Infeasible (best effort)",
        "solver_status": status,
        "feasible": feasible,
        "uncovered_material_units": uncovered_material,
        "uncovered_capacity_units": uncovered_capacity,
        "line2_throughput_gap_units": gap,
        "units_by_vendor": {sid: n for sid, n in units.items() if engaged[sid]},
        "peenya_units": units.get(PEENYA.supplier_id, 0) if engaged.get(PEENYA.supplier_id) else 0,
        "hosur_units": units.get(HOSUR.supplier_id, 0) if engaged.get(HOSUR.supplier_id) else 0,
        "air_charter": bool(engaged.get(AIR.supplier_id)),
        "overtime_hours": ot_hours,
        "total_cost_inr": int(cost),
    }


# ─── 2. Monte Carlo ──────────────────────────────────────────────────────────

def _wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1))


def renegotiation_acceptance_prob(delay_hours: int) -> float:
    """
    Heuristic (assumption): the longer the client is asked to wait, the less likely
    they accept a paid extension. 85% for a trivial delay, falling ~0.5%/hour.
    """
    return min(0.85, max(0.10, 0.85 - 0.005 * max(0, delay_hours)))


def simulate_monte_carlo(
    strategy_type: str,
    units_by_vendor: Dict[str, int],
    overtime_hours: int,
    deadline_hours: float = DEFAULT_HOURS_REMAINING,
    fully_covered: bool = True,
    delay_hours: int = 0,
    iterations: int = 1000,
    seed: int = 42,
    vendors_pool: Optional[List[Vendor]] = None,
) -> Dict[str, Any]:
    """
    Estimate P(plan completes before the deadline).

    Per iteration, each engaged vendor's arrival time is sampled (Gaussian lead time,
    Bernoulli traffic/weather shock, Bernoulli reliability failure). Completion is
    last arrival + overtime (with thermal variance) + QA dispatch (Gaussian).
    A plan that leaves units uncovered can never succeed.

    For SLA_RENEGOTIATION, success means the client accepts the paid extension,
    sampled from `renegotiation_acceptance_prob(delay_hours)`.
    """
    rng = random.Random(seed)
    vendors = [v for v in (vendors_pool or VENDORS) if units_by_vendor.get(v.supplier_id, 0) > 0]
    successes = 0
    finish_times: List[float] = []

    for _ in range(iterations):
        if strategy_type == "SLA_RENEGOTIATION":
            if rng.random() < renegotiation_acceptance_prob(delay_hours):
                successes += 1
            continue
        if not fully_covered:
            continue

        arrival = 0.0
        for v in vendors:
            lead = rng.gauss(v.lead_hours, v.lead_sigma)
            if rng.random() < v.delay_shock_pct / 100.0:
                lead += rng.uniform(*v.delay_shock_range)
            if rng.random() > v.reliability_pct / 100.0:
                lead += rng.uniform(*v.unreliability_delay_range)
            arrival = max(arrival, max(v.min_lead_hours, lead))

        build = float(overtime_hours) + max(0.0, rng.gauss(0.0, 0.35)) if overtime_hours else 0.0
        qa = max(1.0, rng.gauss(QA_DISPATCH_HOURS, 0.3))
        total = arrival + build + qa
        finish_times.append(total)
        if total <= deadline_hours:
            successes += 1

    lo, hi = _wilson_interval(successes, iterations)
    finish_times.sort()
    p90 = finish_times[int(0.9 * (len(finish_times) - 1))] if finish_times else None
    return {
        "confidence_pct": round(successes / iterations * 100.0, 1),
        "ci_low_pct": lo,
        "ci_high_pct": hi,
        "p90_finish_hours": round(p90, 1) if p90 is not None else None,
        "iterations": iterations,
    }


# ─── 3. Tally XML & Notice Generators ────────────────────────────────────────

def _x(value: Any) -> str:
    return _xml_escape(str(value), {'"': "&quot;"})


def build_tally_xml(po_number: str, playbook: PlaybookOption, company_name: str = DEFAULT_COMPANY_NAME) -> str:
    """
    Build a Tally Prime "Import Data" envelope with one Purchase Order voucher per
    supplier (a PO is addressed to a single party). All text is XML-escaped.

    Limitations (not validated against a live Tally instance): ledgers named here
    ("Purchase Accounts" and the supplier party ledger) and the stock item must
    already exist in the company; GST/tax ledgers are not included.
    Overtime is an internal cost and does not appear on any PO.
    """
    date = time.strftime("%Y%m%d")
    vouchers: List[str] = []
    for idx, alloc in enumerate(playbook.vendor_allocations, start=1):
        amount = int(alloc.total_cost_inr)
        qty = int(alloc.units_allocated)
        rate = round(amount / qty, 2) if qty else 0
        vch_no = po_number if len(playbook.vendor_allocations) == 1 else f"{po_number}-{idx}"
        vouchers.append(f"""          <VOUCHER VCHTYPE="Purchase Order" ACTION="Create" OBJVIEW="Invoice Voucher View">
            <DATE>{date}</DATE>
            <VOUCHERTYPENAME>Purchase Order</VOUCHERTYPENAME>
            <VOUCHERNUMBER>{_x(vch_no)}</VOUCHERNUMBER>
            <REFERENCE>{_x(playbook.id)}</REFERENCE>
            <PARTYLEDGERNAME>{_x(alloc.supplier_name)}</PARTYLEDGERNAME>
            <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
            <NARRATION>{_x(f"CascadeZero emergency PO for {playbook.name}")}</NARRATION>
            <ALLINVENTORYENTRIES.LIST>
              <STOCKITEMNAME>{_x(STOCK_ITEM_NAME)}</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <RATE>{rate}/Nos</RATE>
              <AMOUNT>-{amount}</AMOUNT>
              <ACTUALQTY> {qty} Nos</ACTUALQTY>
              <BILLEDQTY> {qty} Nos</BILLEDQTY>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>Purchase Accounts</LEDGERNAME>
                <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                <AMOUNT>-{amount}</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </ALLINVENTORYENTRIES.LIST>
            <LEDGERENTRIES.LIST>
              <LEDGERNAME>{_x(alloc.supplier_name)}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
              <AMOUNT>{amount}</AMOUNT>
            </LEDGERENTRIES.LIST>
          </VOUCHER>""")

    body = "\n".join(vouchers) if vouchers else "          <!-- No supplier purchase required: internal overtime only -->"
    return f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>{_x(company_name)}</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
{body}
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""


def build_shift_broadcast_msg(overtime_hours: int, units_target: int, order_id: str = DEFAULT_ORDER_ID,
                              client: str = DEFAULT_CLIENT) -> str:
    """WhatsApp dispatch text for floor supervisors (draft; sending is a separate step)."""
    if overtime_hours <= 0:
        return (
            f"ℹ️ *CASCADEZERO SHIFT NOTICE*\n"
            f"No overtime required for Order #{order_id}. Normal shift plan stands."
        )
    return (
        f"🚨 *CASCADEZERO SHIFT OVERTIME DISPATCH NOTICE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Target Lines:* Robotic Welding Lines 1 & 3 (Parallel)\n"
        f"• *Mandated Overtime:* *{overtime_hours} Hours*\n"
        f"• *Target Production:* *{units_target} Battery Casings*\n"
        f"• *Overtime Rate:* ₹{OVERTIME_COST_PER_HOUR:,}/hr factory cost\n"
        f"• *Priority Order:* {client} (#{order_id})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Floor supervisors please log confirmation code: *#CZ-OT-{overtime_hours}H*."
    )


def build_client_sla_notice(client: str, order_id: str, deadline_label: str,
                            confidence_pct: Optional[float] = None, renegotiation: bool = False) -> str:
    """Client-facing SLA notice (draft). States the modelled confidence instead of a guarantee."""
    if renegotiation:
        status_line = "• *Status:* Requesting a paid delivery extension (partial delay fee offered)\n"
    elif confidence_pct is not None:
        status_line = f"• *Status:* Recovery plan approved — modelled on-time probability {confidence_pct}%\n"
    else:
        status_line = "• *Status:* Recovery plan approved\n"
    return (
        f"📄 *SLA RECOVERY NOTICE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Client:* {client}\n"
        f"• *Order ID:* #{order_id}\n"
        f"• *Committed Deadline:* {deadline_label}\n"
        f"{status_line}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Apex Volt Operations — CascadeZero recovery workflow."
    )


# ─── 4. Playbook construction & ranking ──────────────────────────────────────

def _allocations_from(
    units_by_vendor: Dict[str, int],
    vendors: Optional[List[Vendor]] = None,
    confirmed: Optional[set] = None,
) -> List[VendorAllocation]:
    allocs: List[VendorAllocation] = []
    for v in vendors or VENDORS:
        n = units_by_vendor.get(v.supplier_id, 0)
        if n <= 0:
            continue
        total = v.unit_cost * n + v.flat_cost
        allocs.append(VendorAllocation(
            supplier_id=v.supplier_id,
            supplier_name=v.name,
            tier=v.tier,
            units_allocated=n,
            cost_per_unit_inr=v.unit_cost,
            flat_charter_cost_inr=v.flat_cost,
            total_cost_inr=total,
            lead_time_hours=int(round(v.lead_hours)),
            route=v.route,
            confirmed=bool(confirmed and v.supplier_id in confirmed),
        ))
    return allocs


def _describe(units_by_vendor: Dict[str, int], ot_hours: int, uncovered: int,
              vendors: Optional[List[Vendor]] = None) -> str:
    parts = []
    for v in vendors or VENDORS:
        n = units_by_vendor.get(v.supplier_id, 0)
        if n > 0:
            cost = v.unit_cost * n + v.flat_cost
            parts.append(f"{n} units from {v.name.split(' (')[0]} (₹{cost:,})")
    if ot_hours:
        parts.append(f"{ot_hours}h overtime on Lines 1 & 3 (₹{ot_hours * OVERTIME_COST_PER_HOUR:,})")
    text = " + ".join(parts) or "No purchase or overtime needed."
    if uncovered:
        text += f" ⚠ {uncovered} units remain uncovered — capacity exhausted."
    return text


def _build_plan(
    plan_id: str,
    name: str,
    strategy_type: str,
    lp: Dict[str, Any],
    sla_penalty_inr: int,
    deadline_hours: float,
    delay_hours: int,
    vendors: Optional[List[Vendor]] = None,
    confirmed: Optional[set] = None,
) -> PlaybookOption:
    units = lp["units_by_vendor"]
    ot = lp["overtime_hours"]
    allocs = _allocations_from(units, vendors, confirmed)
    supplier_cost = sum(a.total_cost_inr for a in allocs)
    ot_cost = ot * OVERTIME_COST_PER_HOUR
    total = supplier_cost + ot_cost
    uncovered = lp["uncovered_material_units"] + lp["uncovered_capacity_units"]
    mc = simulate_monte_carlo(
        strategy_type, units, ot, deadline_hours=deadline_hours,
        fully_covered=lp["feasible"], delay_hours=delay_hours, vendors_pool=vendors,
    )
    p = mc["confidence_pct"] / 100.0
    expected = int(round(total + (1 - p) * sla_penalty_inr))
    return PlaybookOption(
        id=plan_id,
        name=name,
        strategy_type=strategy_type,
        vendor_allocations=allocs,
        overtime_hours=ot,
        overtime_cost_inr=ot_cost,
        supplier_cost_inr=supplier_cost,
        total_mitigation_cost_inr=total,
        sla_penalty_prevented_inr=sla_penalty_inr if lp["feasible"] else 0,
        net_sla_saved_inr=(sla_penalty_inr - total) if lp["feasible"] else -total,
        roi_multiplier=round(sla_penalty_inr / total, 1) if total > 0 and lp["feasible"] else 0.0,
        confidence_pct=mc["confidence_pct"],
        confidence_ci_low_pct=mc["ci_low_pct"],
        confidence_ci_high_pct=mc["ci_high_pct"],
        p90_finish_hours=mc["p90_finish_hours"],
        expected_cost_inr=expected,
        feasible=lp["feasible"],
        uncovered_units=uncovered,
        description=_describe(units, ot, uncovered, vendors),
    )


def _build_renegotiation_plan(sla_penalty_inr: int, partial_penalty_inr: int, delay_hours: int) -> PlaybookOption:
    mc = simulate_monte_carlo("SLA_RENEGOTIATION", {}, 0, delay_hours=delay_hours)
    p = mc["confidence_pct"] / 100.0
    # Accepted → pay the partial fee. Rejected → full breach penalty.
    expected = int(round(p * partial_penalty_inr + (1 - p) * sla_penalty_inr))
    return PlaybookOption(
        id="PLAN_C",
        name="Plan C — Partial SLA Delay Renegotiation",
        strategy_type="SLA_RENEGOTIATION",
        vendor_allocations=[],
        overtime_hours=0,
        overtime_cost_inr=0,
        supplier_cost_inr=0,
        total_mitigation_cost_inr=partial_penalty_inr,
        sla_penalty_prevented_inr=sla_penalty_inr - partial_penalty_inr,
        net_sla_saved_inr=sla_penalty_inr - partial_penalty_inr,
        roi_multiplier=round(sla_penalty_inr / partial_penalty_inr, 1) if partial_penalty_inr else 0.0,
        confidence_pct=mc["confidence_pct"],
        confidence_ci_low_pct=mc["ci_low_pct"],
        confidence_ci_high_pct=mc["ci_high_pct"],
        expected_cost_inr=expected,
        feasible=True,
        description=(
            f"Ask the client for a paid extension (₹{partial_penalty_inr:,} delay fee). "
            f"Modelled acceptance probability {mc['confidence_pct']}% (heuristic falls with a "
            f"{delay_hours}h delay); if refused, the full ₹{sla_penalty_inr:,} penalty applies."
        ),
    )


def _build_ot_only_plan(shortfall_units, line2_speed_pct, sla_penalty_inr, deadline_hours, delay_hours):
    """Overtime-only plan that draws material from on-hand safety stock (valid only for small shortfalls)."""
    gap = line2_throughput_gap(line2_speed_pct)
    ot = min(MAX_OVERTIME_HOURS, int(math.ceil(gap / OVERTIME_UNITS_PER_HOUR)))
    lp = {
        "units_by_vendor": {},
        "overtime_hours": ot,
        "feasible": (
            gap <= ot * OVERTIME_UNITS_PER_HOUR
            and shortfall_units <= SAFETY_STOCK_UNITS
            and ot + QA_DISPATCH_HOURS <= deadline_hours
        ),
        "uncovered_material_units": max(0, shortfall_units - SAFETY_STOCK_UNITS),
        "uncovered_capacity_units": max(0, gap - ot * OVERTIME_UNITS_PER_HOUR),
    }
    plan = _build_plan("PLAN_C", "Plan C — Targeted Overtime + Safety Stock", "TARGETED_OT_ONLY",
                       lp, sla_penalty_inr, deadline_hours, delay_hours)
    plan.description = (
        f"Draw {shortfall_units} casings from on-hand safety stock (≤{SAFETY_STOCK_UNITS}) and run "
        f"{ot}h overtime on Lines 1 & 3 (₹{ot * OVERTIME_COST_PER_HOUR:,}). No supplier spend."
    )
    return plan


def _build_no_action_plan(shortfall_units: int, line2_speed_pct: int, sla_penalty_inr: int) -> PlaybookOption:
    """Baseline: spend nothing and accept the SLA outcome. Wins whenever mitigation costs more than the risk."""
    nothing_needed = shortfall_units == 0 and line2_throughput_gap(line2_speed_pct) == 0
    p_on_time = 100.0 if nothing_needed else 0.0
    return PlaybookOption(
        id="PLAN_D",
        name="Plan D — No Mitigation (Accept SLA Risk)",
        strategy_type="NO_ACTION",
        vendor_allocations=[],
        overtime_hours=0,
        overtime_cost_inr=0,
        supplier_cost_inr=0,
        total_mitigation_cost_inr=0,
        sla_penalty_prevented_inr=0,
        net_sla_saved_inr=0,
        roi_multiplier=0.0,
        confidence_pct=p_on_time,
        confidence_ci_low_pct=p_on_time,
        confidence_ci_high_pct=p_on_time,
        expected_cost_inr=0 if nothing_needed else sla_penalty_inr,
        feasible=True,
        description=(
            "No shortfall and no lost throughput: nothing to do."
            if nothing_needed else
            f"Spend nothing and absorb the ₹{sla_penalty_inr:,} SLA penalty. Baseline for comparison."
        ),
    )


def generate_playbooks(
    shortfall_units: int = 150,
    delay_hours: int = 48,
    line2_speed_pct: int = 50,
    order_id: str = DEFAULT_ORDER_ID,
    sla_penalty_inr: int = DEFAULT_SLA_PENALTY_INR,
    partial_penalty_inr: int = DEFAULT_PARTIAL_PENALTY_INR,
    deadline_hours: float = DEFAULT_HOURS_REMAINING,
    client: str = DEFAULT_CLIENT,
    cfo_min_vendor_reliability_pct: float = 0.0,
    vendor_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    confirmed_vendor_ids: Optional[set] = None,
) -> SolverResult:
    """
    Build three candidate playbooks and rank them by risk-adjusted expected cost:
      - Plan A: the Ops position — MILP with the air charter forced on.
      - Plan B: the CFO position — unconstrained cost-minimal MILP (optionally
                restricted to vendors above a reliability floor after a rebuttal).
      - Plan D: no mitigation (accept the SLA outcome) as the baseline.
      - Plan C: overtime + safety stock when the shortfall fits in stock,
                otherwise a paid SLA renegotiation.
    """
    t_start = time.perf_counter()
    vendors = effective_vendors(vendor_overrides)
    confirmed = set(confirmed_vendor_ids or ())

    lp_a = solve_pulp_milp(shortfall_units, delay_hours, line2_speed_pct, deadline_hours, force_air=True,
                           vendor_overrides=vendor_overrides)
    plan_a = _build_plan("PLAN_A", "Plan A — Ops Hawk Emergency Air Charter", "AIR_CHARTER_MAX_OT",
                         lp_a, sla_penalty_inr, deadline_hours, delay_hours, vendors, confirmed)

    lp_b = solve_pulp_milp(shortfall_units, delay_hours, line2_speed_pct, deadline_hours,
                           min_vendor_reliability_pct=cfo_min_vendor_reliability_pct,
                           vendor_overrides=vendor_overrides)
    plan_b = _build_plan("PLAN_B", "Plan B — Cost-Optimal Regional Re-Route (MILP)", "REGIONAL_BALANCED_OT",
                         lp_b, sla_penalty_inr, deadline_hours, delay_hours, vendors, confirmed)

    if shortfall_units <= SAFETY_STOCK_UNITS:
        plan_c = _build_ot_only_plan(shortfall_units, line2_speed_pct, sla_penalty_inr, deadline_hours, delay_hours)
    else:
        plan_c = _build_renegotiation_plan(sla_penalty_inr, partial_penalty_inr, delay_hours)

    plan_d = _build_no_action_plan(shortfall_units, line2_speed_pct, sla_penalty_inr)

    plans = [plan_a, plan_b, plan_c, plan_d]
    # Ties go to the cheaper plan, then the more reliable one, then the simpler one (D < C < B < A).
    simplicity = {"PLAN_D": 0, "PLAN_C": 1, "PLAN_B": 2, "PLAN_A": 3}
    winner = min(plans, key=lambda p: (p.expected_cost_inr, p.total_mitigation_cost_inr,
                                       -p.confidence_pct, simplicity[p.id]))
    for p in plans:
        p.recommended = p is winner
        p.badge_label = (
            "RECOMMENDED — LOWEST RISK-ADJUSTED COST" if p.recommended
            else ("INFEASIBLE — CANNOT COVER SHORTFALL IN TIME" if not p.feasible else "ALTERNATIVE")
        )

    po_number = f"PO-CZ-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    deadline_label = f"{deadline_hours:g}h from now"
    for p in plans:
        built_units = sum(a.units_allocated for a in p.vendor_allocations)
        p.shift_broadcast_msg = build_shift_broadcast_msg(p.overtime_hours, built_units or shortfall_units,
                                                          order_id, client)
        p.client_sla_notice = build_client_sla_notice(
            client, order_id, deadline_label, p.confidence_pct,
            renegotiation=p.strategy_type == "SLA_RENEGOTIATION",
        )
        p.tally_po_payload = {
            "po_number": po_number,
            "playbook_id": p.id,
            "order_id": order_id,
            "total_cost_inr": p.total_mitigation_cost_inr,
            "net_sla_saved_inr": p.net_sla_saved_inr,
            "tally_xml": build_tally_xml(po_number, p),
        }

    any_infeasible = not (lp_a["feasible"] and lp_b["feasible"])
    lp_status = lp_b["status"]
    if not lp_b["feasible"]:
        lp_status = (
            f"Infeasible: vendor + overtime capacity leaves "
            f"{lp_b['uncovered_material_units'] + lp_b['uncovered_capacity_units']} units uncovered"
        )

    return SolverResult(
        shortfall_units=shortfall_units,
        delay_hours=delay_hours,
        line2_speed_pct=line2_speed_pct,
        order_id=order_id,
        total_sla_exposure_inr=sla_penalty_inr,
        playbooks=plans,
        recommended_plan_id=winner.id,
        solve_duration_ms=round((time.perf_counter() - t_start) * 1000.0, 2),
        lp_status=lp_status,
        monte_carlo_iterations=1000,
        deadline_hours=deadline_hours,
        line2_throughput_gap_units=lp_b["line2_throughput_gap_units"],
        ranking_rule="argmin(mitigation_cost + (1 - P_on_time) × SLA_penalty)",
        capacity_exhausted=any_infeasible,
    )


# ─── 5. CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    for label, args in [
        ("Scenario 1 (150u, 48h, 50%)", (150, 48, 50)),
        ("Scenario 2 (25u, 6h, 85%)", (25, 6, 85)),
        ("Scenario 3 (350u, 72h, 25%)", (350, 72, 25)),
        ("Over capacity (1000u, 72h, 25%)", (1000, 72, 25)),
    ]:
        res = generate_playbooks(*args)
        print(f"\n== {label} → {res.recommended_plan_id} | {res.lp_status} | {res.solve_duration_ms}ms")
        for p in res.playbooks:
            mark = "*" if p.recommended else " "
            print(f" {mark} {p.id}: cost ₹{p.total_mitigation_cost_inr:,}  P(on-time) {p.confidence_pct}% "
                  f"[{p.confidence_ci_low_pct}-{p.confidence_ci_high_pct}]  E[cost] ₹{p.expected_cost_inr:,}  "
                  f"feasible={p.feasible}  — {p.description}")
