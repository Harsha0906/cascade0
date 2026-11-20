"""
CascadeZero — Mathematical Optimization (PuLP) & Monte Carlo Risk Engine

Single source of truth for:
  - A mixed-integer program (PuLP) that allocates supply across a factory's vendors and
    schedules overtime per production line, subject to vendor capacity, lead-time
    feasibility against the order deadline, and the throughput lost on throttled lines.
  - A seeded Monte Carlo simulation that estimates the probability each plan
    lands before the deadline.
  - Plan ranking by *risk-adjusted expected cost*:
        E[cost] = mitigation_cost + (1 - P(on-time)) * SLA_penalty
    The recommended plan is whichever minimises E[cost]. No plan is hard-coded
    as the winner.

Every plant-specific number (vendors, lines, overtime rates, QA time, safety stock,
production window, company and stock-item names) comes from the `FactoryModel`
passed in by the caller (see `app.factory_model.load_factory_model`).
"""

from __future__ import annotations

import math
import random
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional

from xml.sax.saxutils import escape as _xml_escape

import pulp

from app.factory_model import FactoryModel, Vendor
from app.schemas import (
    PlaybookOption,
    SolverResult,
    VendorAllocation,
)

# Penalty per unit left uncovered by the optimiser. Large enough that slack is only
# used when the problem is genuinely infeasible; it lets us report *how* infeasible.
UNCOVERED_UNIT_PENALTY = 1_000_000

# Objective tie-breaks (never part of any reported cost):
#   per hour of elapsed overtime window → prefer balancing overtime across lines;
#   per sourced unit → never allocate more units than needed from a zero-unit-cost
#   (flat-fee) vendor.
# All real cost coefficients are whole rupees, so any two plans with different real cost
# differ by >= ₹1. The weights are sized from the model so that the tie-breaks' worst case
# (longest possible window, every vendor at capacity) stays below ₹1 in total; with a zero
# MIP gap they can therefore only choose among plans of equal real cost.
_TIE_BREAK_BUDGET_INR = 0.4   # per term; two terms -> worst case 0.8 < ₹1


def _tie_break_weights(model: FactoryModel) -> tuple[float, float]:
    """(₹ per overtime-window hour, ₹ per sourced unit), each term's worst case <= ₹0.4."""
    max_window = max((l.max_ot_hours for l in model.overtime_lines), default=0)
    max_units = sum(v.max_units for v in model.vendors)
    return _TIE_BREAK_BUDGET_INR / max(1, max_window), _TIE_BREAK_BUDGET_INR / max(1, max_units)


class SolverInputError(ValueError):
    """Raised for inputs the model cannot represent (negative shortfall, etc.)."""


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


def _unsolved(status: str, solver_status: str, shortfall_units: int, gap: int) -> Dict[str, Any]:
    return {
        "status": status,
        "solver_status": solver_status,
        "feasible": False,
        "uncovered_material_units": shortfall_units,
        "uncovered_capacity_units": max(0, gap),
        "throughput_gap_units": gap,
        "units_by_vendor": {},
        "air_charter": False,
        "overtime_hours": 0,
        "overtime_line_hours": {},
        "total_cost_inr": 0,
    }


def solve_pulp_milp(
    model: FactoryModel,
    shortfall_units: int,
    line_speeds: Mapping[str, int],
    deadline_hours: float,
    force_vendor_id: Optional[str] = None,
    allowed_vendor_ids: Optional[List[str]] = None,
    min_vendor_reliability_pct: float = 0.0,
) -> Dict[str, Any]:
    """
    Minimise   Σ unit_cost_v·x_v + Σ flat_cost_v·y_v + Σ ot_cost_l·h_l
               + BIG·(u_mat + u_cap) + w_H·H + w_x·Σ x_v       (last two: tie-breaks < ₹1 total)
    subject to
      Σ x_v + u_mat               >= material_shortfall          (units to source)
      Σ ot_units_l·h_l + u_cap    >= throughput_gap(line_speeds) (lost line output)
      x_v                         <= cap_v · y_v                 (vendor used only if engaged)
      H                           >= h_l                         (elapsed overtime window)
      lead_v·y_v + H + QA         <= deadline                    (arrival + build + QA fits)
      H + QA                      <= deadline
      x_v ∈ Z+, y_v ∈ {0,1}, h_l ∈ Z ∩ [0, max_ot_l], H, u ≥ 0

    Vendors are the model's vendors filtered by `allowed_vendor_ids` and the reliability
    floor. `force_vendor_id` requires that vendor to be engaged (and used when there is a
    shortfall). Returns allocations, per-line overtime, cost (tie-breaks excluded), `feasible`
    (no slack used) and the raw solver status. Infeasibility is reported, never hidden.
    """
    if shortfall_units < 0:
        raise SolverInputError("shortfall_units must be >= 0")
    if deadline_hours <= model.qa_dispatch_hours:
        raise SolverInputError("deadline_hours must exceed QA/dispatch time")

    qa = model.qa_dispatch_hours
    gap = model.throughput_gap(line_speeds)
    vendors = [
        v for v in model.vendors
        if (allowed_vendor_ids is None or v.supplier_id in allowed_vendor_ids)
        and v.reliability_pct >= min_vendor_reliability_pct
    ]
    vendor_ids = {v.supplier_id for v in vendors}
    if force_vendor_id is not None and force_vendor_id not in vendor_ids:
        # The forced vendor is unavailable for this run (declined, filtered, or below the floor).
        return _unsolved("Infeasible: forced vendor unavailable", "NotAttempted", shortfall_units, gap)

    lines = model.overtime_lines

    prob = pulp.LpProblem("CascadeZero_Recovery", pulp.LpMinimize)
    # Index-based names: ids may contain any characters and sanitised ids can collide.
    x = {v.supplier_id: _new_var(prob, f"x_{i}", 0, v.max_units, "Integer") for i, v in enumerate(vendors)}
    y = {v.supplier_id: _new_var(prob, f"y_{i}", cat="Binary") for i, v in enumerate(vendors)}
    h = {l.line_id: _new_var(prob, f"h_{j}", 0, l.max_ot_hours, "Integer") for j, l in enumerate(lines)}
    window = _new_var(prob, "H_ot_window", 0, max((l.max_ot_hours for l in lines), default=0))
    w_window, w_unit = _tie_break_weights(model)
    u_mat = _new_var(prob, "u_material", 0, None)
    u_cap = _new_var(prob, "u_capacity", 0, None)

    prob += (
        pulp.lpSum(v.unit_cost * x[v.supplier_id] + v.flat_cost * y[v.supplier_id] for v in vendors)
        + pulp.lpSum(l.ot_cost_per_hour * h[l.line_id] for l in lines)
        + UNCOVERED_UNIT_PENALTY * (u_mat + u_cap)
        + w_window * window
        + w_unit * pulp.lpSum(x.values()),
        "Total_Recovery_Cost",
    )
    prob += (pulp.lpSum(x.values()) + u_mat >= shortfall_units, "Material_Coverage")
    prob += (pulp.lpSum(l.ot_units_per_hour * h[l.line_id] for l in lines) + u_cap >= gap,
             "Throughput_Recovery")
    for j, l in enumerate(lines):
        prob += (window >= h[l.line_id], f"Window_{j}")
    for i, v in enumerate(vendors):
        sid = v.supplier_id
        prob += (x[sid] <= v.max_units * y[sid], f"Engage_{i}")
        prob += (v.lead_hours * y[sid] + window + qa <= deadline_hours, f"Deadline_{i}")
    prob += (window + qa <= deadline_hours, "Deadline_Overtime")
    if force_vendor_id is not None:
        prob += (y[force_vendor_id] == 1, "Policy_Forced_Vendor")
        if shortfall_units > 0:
            prob += (x[force_vendor_id] >= 1, "Policy_Forced_Vendor_Used")

    # Relative MIP gap 0: the tie-break terms are < ₹1, so any gap tolerance could hide a
    # cheaper plan behind them.
    solver = None
    if hasattr(pulp, "HiGHS"):
        highs = pulp.HiGHS(msg=False, gapRel=0)
        if highs.available():
            solver = highs
    if solver is None:
        cbc = getattr(pulp, "PULP_CBC_CMD", None) or pulp.COIN_CMD   # PuLP >= 3 has no bundled CBC
        solver = cbc(msg=False, gapRel=0)
    status = _status_name(prob.solve(solver), prob)
    if status == "Infeasible":
        # Coverage has slack, so this can only come from a hard rule: a policy (e.g. a forced
        # vendor) whose lead time cannot meet the deadline. Report it as an unusable plan.
        return _unsolved("Infeasible: policy cannot meet the deadline", status, shortfall_units, gap)
    if status != "Optimal":
        raise RuntimeError(f"MILP solver did not reach optimality (status={status})")

    units = {sid: int(round(_val(var))) for sid, var in x.items()}
    engaged = {sid: int(round(_val(var))) == 1 and units[sid] > 0 for sid, var in y.items()}
    line_hours = {lid: int(round(_val(var))) for lid, var in h.items()}
    line_hours = {lid: n for lid, n in line_hours.items() if n > 0}
    ot_window = max(line_hours.values(), default=0)
    uncovered_material = int(math.ceil(_val(u_mat) - 1e-6))
    uncovered_capacity = int(math.ceil(_val(u_cap) - 1e-6))

    ot_cost_by_line = {l.line_id: l.ot_cost_per_hour for l in lines}
    cost = sum(
        v.unit_cost * units[v.supplier_id] + (v.flat_cost if engaged[v.supplier_id] else 0)
        for v in vendors
    ) + sum(ot_cost_by_line[lid] * n for lid, n in line_hours.items())

    expedite = model.expedite_vendor_id
    feasible = uncovered_material == 0 and uncovered_capacity == 0
    return {
        "status": "Optimal" if feasible else "Infeasible (best effort)",
        "solver_status": status,
        "feasible": feasible,
        "uncovered_material_units": uncovered_material,
        "uncovered_capacity_units": uncovered_capacity,
        "throughput_gap_units": gap,
        "units_by_vendor": {sid: n for sid, n in units.items() if engaged[sid]},
        "air_charter": bool(expedite and engaged.get(expedite)),
        "overtime_hours": ot_window,
        "overtime_line_hours": line_hours,
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
    model: FactoryModel,
    strategy_type: str,
    units_by_vendor: Dict[str, int],
    overtime_hours: int,
    deadline_hours: float,
    fully_covered: bool = True,
    delay_hours: int = 0,
    iterations: int = 1000,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Estimate P(plan completes before the deadline).

    Per iteration, each engaged vendor's arrival time is sampled (Gaussian lead time,
    Bernoulli traffic/weather shock, Bernoulli reliability failure). Completion is
    last arrival + overtime window (with thermal variance) + QA dispatch (Gaussian around
    `model.qa_dispatch_hours`). A plan that leaves units uncovered can never succeed.

    For SLA_RENEGOTIATION, success means the client accepts the paid extension,
    sampled from `renegotiation_acceptance_prob(delay_hours)`.
    """
    rng = random.Random(seed)
    vendors = [v for v in model.vendors if units_by_vendor.get(v.supplier_id, 0) > 0]
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
        qa = max(1.0, rng.gauss(model.qa_dispatch_hours, 0.3))
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


def build_tally_xml(po_number: str, playbook: PlaybookOption, model: FactoryModel) -> str:
    """
    Build a Tally Prime "Import Data" envelope with one Purchase Order voucher per
    supplier (a PO is addressed to a single party). All text is XML-escaped.
    The company is `model.name` and the stock item is `model.stock_item_name`.

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
              <STOCKITEMNAME>{_x(model.stock_item_name)}</STOCKITEMNAME>
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
          <SVCURRENTCOMPANY>{_x(model.name)}</SVCURRENTCOMPANY>
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


def _overtime_lines_text(model: FactoryModel, overtime_line_hours: Mapping[str, int]) -> str:
    """'Line A (4h), Line C (3h)' in model order, for lines with overtime."""
    return ", ".join(
        f"{l.name} ({overtime_line_hours[l.line_id]}h)"
        for l in model.lines if overtime_line_hours.get(l.line_id, 0) > 0
    )


def _overtime_cost(model: FactoryModel, overtime_line_hours: Mapping[str, int]) -> int:
    by_id = {l.line_id: l for l in model.lines}
    return sum(by_id[lid].ot_cost_per_hour * n for lid, n in overtime_line_hours.items() if lid in by_id)


def build_shift_broadcast_msg(model: FactoryModel, overtime_line_hours: Dict[str, int], units_target: int,
                              order_id: str, client: str) -> str:
    """WhatsApp dispatch text for floor supervisors (draft; sending is a separate step)."""
    hours = {lid: n for lid, n in (overtime_line_hours or {}).items() if n > 0}
    if not hours:
        return (
            f"ℹ️ *CASCADEZERO SHIFT NOTICE*\n"
            f"No overtime required for Order #{order_id}. Normal shift plan stands."
        )
    window = max(hours.values())
    return (
        f"🚨 *CASCADEZERO SHIFT OVERTIME DISPATCH NOTICE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Target Lines:* {_overtime_lines_text(model, hours)}\n"
        f"• *Overtime Window:* *{window} Hours*\n"
        f"• *Target Production:* *{units_target} {model.stock_item_name} units*\n"
        f"• *Overtime Cost:* ₹{_overtime_cost(model, hours):,} factory cost\n"
        f"• *Priority Order:* {client} (#{order_id})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Floor supervisors please log confirmation code: *#CZ-OT-{window}H*."
    )


def build_client_sla_notice(client: str, order_id: str, deadline_label: str,
                            confidence_pct: Optional[float] = None, renegotiation: bool = False,
                            factory_name: Optional[str] = None) -> str:
    """Client-facing SLA notice (draft). States the modelled confidence instead of a guarantee."""
    if renegotiation:
        status_line = "• *Status:* Requesting a paid delivery extension (partial delay fee offered)\n"
    elif confidence_pct is not None:
        status_line = f"• *Status:* Recovery plan approved — modelled on-time probability {confidence_pct}%\n"
    else:
        status_line = "• *Status:* Recovery plan approved\n"
    signature = f"{factory_name} Operations" if factory_name else "Operations"
    return (
        f"📄 *SLA RECOVERY NOTICE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Client:* {client}\n"
        f"• *Order ID:* #{order_id}\n"
        f"• *Committed Deadline:* {deadline_label}\n"
        f"{status_line}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{signature} — CascadeZero recovery workflow."
    )


# ─── 4. Playbook construction & ranking ──────────────────────────────────────

def _allocations_from(
    units_by_vendor: Dict[str, int],
    vendors: tuple[Vendor, ...],
    confirmed: Optional[set] = None,
) -> List[VendorAllocation]:
    allocs: List[VendorAllocation] = []
    for v in vendors:
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


def _describe(model: FactoryModel, units_by_vendor: Dict[str, int], line_hours: Mapping[str, int],
              uncovered: int) -> str:
    parts = []
    for v in model.vendors:
        n = units_by_vendor.get(v.supplier_id, 0)
        if n > 0:
            cost = v.unit_cost * n + v.flat_cost
            parts.append(f"{n} units from {v.name.split(' (')[0]} (₹{cost:,})")
    if line_hours:
        parts.append(f"overtime on {_overtime_lines_text(model, line_hours)} "
                     f"(₹{_overtime_cost(model, line_hours):,})")
    text = " + ".join(parts) or "No purchase or overtime needed."
    if uncovered:
        text += f" ⚠ {uncovered} units remain uncovered — capacity exhausted."
    return text


def _build_plan(
    model: FactoryModel,
    plan_id: str,
    name: str,
    strategy_type: str,
    lp: Dict[str, Any],
    sla_penalty_inr: int,
    deadline_hours: float,
    delay_hours: int,
    confirmed: Optional[set] = None,
) -> PlaybookOption:
    units = lp["units_by_vendor"]
    window = lp["overtime_hours"]
    line_hours = lp["overtime_line_hours"]
    allocs = _allocations_from(units, model.vendors, confirmed)
    supplier_cost = sum(a.total_cost_inr for a in allocs)
    ot_cost = _overtime_cost(model, line_hours)
    total = supplier_cost + ot_cost
    uncovered = lp["uncovered_material_units"] + lp["uncovered_capacity_units"]
    mc = simulate_monte_carlo(
        model, strategy_type, units, window, deadline_hours,
        fully_covered=lp["feasible"], delay_hours=delay_hours,
    )
    p = mc["confidence_pct"] / 100.0
    expected = int(round(total + (1 - p) * sla_penalty_inr))
    return PlaybookOption(
        id=plan_id,
        name=name,
        strategy_type=strategy_type,
        vendor_allocations=allocs,
        overtime_hours=window,
        overtime_line_hours=dict(line_hours),
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
        description=_describe(model, units, line_hours, uncovered),
    )


def _build_renegotiation_plan(model: FactoryModel, sla_penalty_inr: int, partial_penalty_inr: int,
                              delay_hours: int, deadline_hours: float) -> PlaybookOption:
    mc = simulate_monte_carlo(model, "SLA_RENEGOTIATION", {}, 0, deadline_hours, delay_hours=delay_hours)
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


def _build_ot_only_plan(model: FactoryModel, shortfall_units: int, line_speeds: Mapping[str, int],
                        sla_penalty_inr: int, deadline_hours: float, delay_hours: int) -> PlaybookOption:
    """Overtime-only plan that draws material from on-hand safety stock (valid only for small shortfalls)."""
    lp = dict(solve_pulp_milp(model, 0, line_speeds, deadline_hours, allowed_vendor_ids=[]))
    stock_short = max(0, shortfall_units - model.safety_stock_units)
    lp["uncovered_material_units"] = stock_short
    lp["feasible"] = lp["feasible"] and stock_short == 0
    plan = _build_plan(model, "PLAN_C", "Plan C — Targeted Overtime + Safety Stock", "TARGETED_OT_ONLY",
                       lp, sla_penalty_inr, deadline_hours, delay_hours)
    line_hours = lp["overtime_line_hours"]
    ot_text = (
        f"run overtime on {_overtime_lines_text(model, line_hours)} (₹{_overtime_cost(model, line_hours):,})"
        if line_hours else "run no overtime"
    )
    plan.description = (
        f"Draw {shortfall_units} units from on-hand safety stock (≤{model.safety_stock_units}) and "
        f"{ot_text}. No supplier spend."
    )
    if lp["uncovered_capacity_units"]:
        plan.description += f" ⚠ {lp['uncovered_capacity_units']} units of lost throughput remain uncovered."
    return plan


def _build_no_action_plan(model: FactoryModel, shortfall_units: int, line_speeds: Mapping[str, int],
                          sla_penalty_inr: int) -> PlaybookOption:
    """Baseline: spend nothing and accept the SLA outcome. Wins whenever mitigation costs more than the risk."""
    nothing_needed = shortfall_units == 0 and model.throughput_gap(line_speeds) == 0
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
    model: FactoryModel,
    shortfall_units: int,
    delay_hours: int,
    line_speeds: Mapping[str, int],
    order_id: str,
    sla_penalty_inr: int,
    partial_penalty_inr: int,
    deadline_hours: float,
    client: str,
    cfo_min_vendor_reliability_pct: float = 0.0,
    vendor_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    confirmed_vendor_ids: Optional[set] = None,
) -> SolverResult:
    """
    Build candidate playbooks and rank them by risk-adjusted expected cost:
      - Plan A: the Ops position — MILP with the factory's EXPEDITE vendor forced on
                (only when the run's model has one).
      - Plan B: the CFO position — unconstrained cost-minimal MILP (optionally
                restricted to vendors above a reliability floor after a rebuttal).
      - Plan C: overtime + safety stock when the shortfall fits in stock,
                otherwise a paid SLA renegotiation.
      - Plan D: no mitigation (accept the SLA outcome) as the baseline.

    `vendor_overrides` (e.g. offers confirmed by the Sourcing Agent) are applied to the
    model for this run only; `delay_hours` is the upstream delay that caused the shortfall.
    """
    t_start = time.perf_counter()
    model = model.with_vendor_overrides(vendor_overrides)
    confirmed = set(confirmed_vendor_ids or ())

    plans: List[PlaybookOption] = []
    lp_a = None
    expedite_id = model.expedite_vendor_id
    if expedite_id is not None:
        lp_a = solve_pulp_milp(model, shortfall_units, line_speeds, deadline_hours, force_vendor_id=expedite_id)
        plans.append(_build_plan(model, "PLAN_A", "Plan A — Ops Hawk Emergency Expedite", "AIR_CHARTER_MAX_OT",
                                 lp_a, sla_penalty_inr, deadline_hours, delay_hours, confirmed))

    lp_b = solve_pulp_milp(model, shortfall_units, line_speeds, deadline_hours,
                           min_vendor_reliability_pct=cfo_min_vendor_reliability_pct)
    plans.append(_build_plan(model, "PLAN_B", "Plan B — Cost-Optimal Regional Re-Route (MILP)",
                             "REGIONAL_BALANCED_OT", lp_b, sla_penalty_inr, deadline_hours, delay_hours, confirmed))

    if shortfall_units <= model.safety_stock_units:
        plans.append(_build_ot_only_plan(model, shortfall_units, line_speeds, sla_penalty_inr,
                                         deadline_hours, delay_hours))
    else:
        plans.append(_build_renegotiation_plan(model, sla_penalty_inr, partial_penalty_inr, delay_hours,
                                               deadline_hours))

    plans.append(_build_no_action_plan(model, shortfall_units, line_speeds, sla_penalty_inr))

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
        p.shift_broadcast_msg = build_shift_broadcast_msg(model, p.overtime_line_hours,
                                                          built_units or shortfall_units, order_id, client)
        p.client_sla_notice = build_client_sla_notice(
            client, order_id, deadline_label, p.confidence_pct,
            renegotiation=p.strategy_type == "SLA_RENEGOTIATION", factory_name=model.name,
        )
        p.tally_po_payload = {
            "po_number": po_number,
            "playbook_id": p.id,
            "order_id": order_id,
            "total_cost_inr": p.total_mitigation_cost_inr,
            "net_sla_saved_inr": p.net_sla_saved_inr,
            "tally_xml": build_tally_xml(po_number, p, model),
        }

    any_infeasible = not (lp_b["feasible"] and (lp_a is None or lp_a["feasible"]))
    lp_status = lp_b["status"]
    if not lp_b["feasible"]:
        lp_status = (
            f"Infeasible: vendor + overtime capacity leaves "
            f"{lp_b['uncovered_material_units'] + lp_b['uncovered_capacity_units']} units uncovered"
        )

    return SolverResult(
        shortfall_units=shortfall_units,
        delay_hours=delay_hours,
        line_speeds=dict(line_speeds),
        order_id=order_id,
        total_sla_exposure_inr=sla_penalty_inr,
        playbooks=plans,
        recommended_plan_id=winner.id,
        solve_duration_ms=round((time.perf_counter() - t_start) * 1000.0, 2),
        lp_status=lp_status,
        monte_carlo_iterations=1000,
        deadline_hours=deadline_hours,
        throughput_gap_units=lp_b["throughput_gap_units"],
        ranking_rule="argmin(mitigation_cost + (1 - P_on_time) × SLA_penalty)",
        capacity_exhausted=any_infeasible,
    )
