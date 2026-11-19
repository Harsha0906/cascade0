"""
CascadeZero — FastAPI server

  GET  /api/v1/state                       factory snapshot (read-only, open)
  POST /api/v1/simulate-crisis             run the agent graph + solver          [API key]
  GET  /api/v1/webhooks/whatsapp           Meta verification handshake
  POST /api/v1/webhooks/whatsapp           Meta (HMAC-verified) / Twilio webhook
  POST /api/v1/ingest/plc-telemetry        line telemetry (HTTP JSON, simulated) [API key]
  POST /api/v1/ingest/erp-csv              Tally/Excel CSV order upsert          [API key]
  POST /api/v1/ingest/live-highway-check   weather check (labelled when offline)
  POST /api/v1/execute-plan                execute a server-computed playbook    [API key]
  POST /api/v1/sourcing/start              Sourcing Agent: send vendor enquiries [API key]
  GET  /api/v1/sourcing/{run_id}           enquiry status + confirmed plan
  POST /api/v1/sourcing/{run_id}/vendor-reply  record a vendor reply           [API key]
  POST /api/v1/reset                       reset demo data                       [API key]

Security model: mutating endpoints require the shared operator key in `X-API-Key`
(set CASCADE_API_KEY). The Next.js middleware injects it server-side so it never reaches
the browser. This is an operator-level gate, not per-user auth; add Supabase Auth (or SSO)
before giving access to more than one trusted team.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import html
import io
import logging
import math
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app import run_store
from app.agents import sourcing
from app.agents.graph import run_cascade_pipeline
from app.config import settings
from app.solver import SolverInputError
from app.db import (
    default_factory_name,
    get_full_state,
    insert_row,
    log_agent_step,
    reset_to_seed,
    save_purchase_order,
    update_rows,
    upsert_row,
)
from app.meta_whatsapp import send_whatsapp_interactive_buttons, send_whatsapp_text
from app.schemas import (
    ErpCsvSyncRequest,
    ExecutePlanRequest,
    ExecutionReceiptResponse,
    LiveHighwayCheckRequest,
    PlcTelemetryRequest,
    SimulateCrisisRequest,
    SourcingReplyRequest,
    SourcingStartRequest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cascadezero.server")

app = FastAPI(
    title="CascadeZero API",
    description="Disruption-response copilot: LLM extraction + MILP/Monte Carlo planning with human approval",
    version="2.1.0",
)

# ─── Startup security posture ────────────────────────────────────────────────
_problems = settings.security_problems()
if settings.is_production and _problems:
    raise RuntimeError("Refusing to start in production: " + "; ".join(_problems))
for _p in _problems:
    logger.warning("SECURITY (dev mode): %s", _p)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Shared operator key on mutating endpoints. Open only in dev mode with no key configured."""
    if not settings.CASCADE_API_KEY:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.CASCADE_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-API-Key")


# ─── Preset scenarios ────────────────────────────────────────────────────────
SCENARIO_PROMPTS = {
    1: (
        "NH48 Chennai-Bengaluru highway flooding near Vellore delayed shipment of 500 aluminum battery "
        "casings from Chennai Precision by 48 hours. Simultaneously, Robotic Welding Line 2 overheated "
        "to 89.0°C and throttled to 50% speed. Current unit shortfall is 150 casings on Order #EV-402."
    ),
    2: (
        "Minor toll transit delay on NH48 corridor causing 6 hours shipment delay for 25 units. "
        "Welding Line 2 slightly throttled to 85% speed (74°C). Shortfall is 25 battery casings on Order #EV-402."
    ),
    3: (
        "Severe supplier collapse: Chennai Precision Casings shipment blocked by 72 hours due to "
        "bridge damage near Ranipet. Robotic Welding Line 2 overheated to 92°C and dropped "
        "to 25% speed. Compound shortfall of 350 battery casings on Order #EV-402."
    ),
}
SCENARIO_DEFAULTS = {
    1: {"delay": 48, "shortfall": 150, "speed": 50},
    2: {"delay": 6, "shortfall": 25, "speed": 85},
    3: {"delay": 72, "shortfall": 350, "speed": 25},
}


def _run_pipeline(message: str, source_channel: str, delay=None, shortfall=None, speed=None) -> Dict[str, Any]:
    result = run_cascade_pipeline(
        raw_message=message,
        source_channel=source_channel,
        override_delay_hours=delay,
        override_shortfall_units=shortfall,
        override_line2_speed_pct=speed,
    )
    run_store.save_run(result)
    insert_row("disruption_events", {
        "source_channel": source_channel,
        "raw_message": message,
        "delay_hours": result["delay_hours"],
        "line2_speed_pct": result["line2_speed_pct"],
        "shortfall_units": result["shortfall_units"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return result


# ─── 1. Health & state ───────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"app": "CascadeZero", "status": "online", "factory": default_factory_name(), "docs_url": "/docs"}


@app.get("/api/v1/state")
def get_state():
    return get_full_state()


@app.get("/api/v1/runs/latest")
def get_latest_run():
    """Summary of the most recent analysis run (used by the mobile controller to approve it)."""
    run_id = run_store.latest_run_id()
    run = run_store.get_run(run_id) if run_id else None
    if not run:
        return {"run_id": None}
    winner = next((p for p in run["playbooks"] if p["id"] == run["recommended_plan_id"]), None)
    receipt = run_store.get_receipt(run.get("parent_run_id") or run_id)
    return {
        "run_id": run_id,
        "recommended_plan_id": run["recommended_plan_id"],
        "winner": winner,
        "executed": bool(receipt and not receipt.get("pending")),
        "ai_mode": run.get("ai_mode", {}),
        "parent_run_id": run.get("parent_run_id"),
    }


# ─── 2. Crisis simulation ────────────────────────────────────────────────────

@app.post("/api/v1/simulate-crisis", dependencies=[Depends(require_api_key)])
def simulate_crisis(req: SimulateCrisisRequest):
    if req.raw_message:
        message = req.raw_message
    else:
        message = SCENARIO_PROMPTS.get(req.scenario_id or 1, SCENARIO_PROMPTS[1])

    delay, shortfall, speed = req.override_delay_hours, req.override_shortfall_units, req.override_line2_speed_pct
    if req.scenario_id in SCENARIO_DEFAULTS and not req.raw_message:
        d = SCENARIO_DEFAULTS[req.scenario_id]
        delay = d["delay"] if delay is None else delay
        shortfall = d["shortfall"] if shortfall is None else shortfall
        speed = d["speed"] if speed is None else speed

    logger.info("Simulating crisis via %s: %s", req.source_channel, message[:80])
    try:
        result = _run_pipeline(message, req.source_channel, delay, shortfall, speed)
    except SolverInputError as exc:
        raise HTTPException(status_code=422, detail=f"Cannot plan for these inputs: {exc}")

    return {
        "success": True,
        "run_id": result["run_id"],
        "scenario_id": req.scenario_id,
        "headline": result.get("crisis_headline", ""),
        "extracted_parameters": {
            "delay_hours": result["delay_hours"],
            "line2_speed_pct": result["line2_speed_pct"],
            "line2_temp_celsius": result["line2_temp_celsius"],
            "shortfall_units": result["shortfall_units"],
            "affected_order_id": result["order_id"],
            "source": result.get("extraction_source", "unknown"),
            "overridden_by_preset_or_slider": any(v is not None for v in (delay, shortfall, speed)),
        },
        "blast_radius": result.get("blast_radius", {}),
        "ops_proposal": result.get("ops_proposal", {}),
        "cfo_proposal": result.get("cfo_proposal", {}),
        "rebuttal_occurred": result.get("rebuttal_count", 0) > 0,
        "rebuttal_notes": result.get("rebuttal_notes", []),
        "playbooks": result["playbooks"],
        "recommended_plan_id": result["recommended_plan_id"],
        "solver_result": result["solver_result"],
        "ai_mode": result.get("ai_mode", {}),
    }


# ─── 3. WhatsApp webhook ─────────────────────────────────────────────────────

def _verify_meta_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    if not settings.META_APP_SECRET:
        return not settings.is_production  # dev mode without a secret: accept (warned at startup)
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.META_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


def _is_approver(number: str) -> bool:
    if not settings.WA_APPROVER_NUMBERS:
        # No allowlist configured: approvals over WhatsApp are disabled rather than open to anyone.
        return False
    return number.lstrip("+") in settings.WA_APPROVER_NUMBERS


def _status_text() -> str:
    state = get_full_state()
    ev = next((o for o in state["orders"] if o["order_id"] == "EV-402"), None)
    line2 = next((l for l in state["production_lines"] if l["line_id"] == "LINE-2"), {})
    penalty = ev["sla_penalty_inr"] if ev else 0
    return (
        f"🏭 *PLANT STATUS*\n"
        f"• Line 2: {line2.get('status', '?')} ({line2.get('temp_celsius', '?')}°C)\n"
        f"• Order #EV-402: {ev['status'] if ev else 'Nominal'}\n"
        f"• Active shortfall: {ev['shortfall_units'] if ev else 0} units\n"
        f"• SLA penalty exposure: ₹{penalty:,}"
    )


def _winner_summary(result: Dict[str, Any]) -> str:
    winner = next(p for p in result["playbooks"] if p["id"] == result["recommended_plan_id"])
    penalty = result.get("blast_radius", {}).get("sla_penalty_inr", 0)
    mode = result.get("ai_mode", {}).get("overall", "fallback")
    return (
        f"🚨 *CASCADEZERO RECOVERY PLAN* ({result['run_id']})\n"
        f"• Order #{result['order_id']} — ₹{penalty:,} SLA exposure\n"
        f"• Shortfall: {result['shortfall_units']} casings (+{result['delay_hours']}h delay)\n\n"
        f"⚖️ *Recommended: {winner['id']}* — {winner['name']}\n"
        f"• Cost: ₹{winner['total_mitigation_cost_inr']:,}\n"
        f"• Modelled P(on-time): {winner['confidence_pct']}%\n"
        f"• Expected cost incl. risk: ₹{winner['expected_cost_inr']:,}\n"
        f"_Numbers from MILP + Monte Carlo; narration mode: {mode}._"
    )


async def _handle_meta_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        changes = payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return {"status": "ignored"}
    messages = changes.get("messages", [])
    if not messages:
        # Delivery/read receipts. Log failures so undelivered replies are visible.
        for st in changes.get("statuses", []):
            errors = st.get("errors") or []
            if st.get("status") == "failed" or errors:
                for e in errors or [{}]:
                    logger.error("WhatsApp delivery FAILED to %s: code %s %s — %s",
                                 st.get("recipient_id"), e.get("code"), e.get("title"),
                                 (e.get("error_data") or {}).get("details", e.get("message", "")))
            else:
                logger.info("WhatsApp message %s to %s", st.get("status"), st.get("recipient_id"))
        return {"status": "ok"}

    msg = messages[0]
    sender = msg.get("from", "")

    if msg.get("type") == "interactive":
        button_id = msg.get("interactive", {}).get("button_reply", {}).get("id", "")
        if button_id.startswith("APPROVE:"):
            run_id, _, playbook_id = button_id[len("APPROVE:"):].partition(":")
            if not _is_approver(sender):
                logger.warning("Rejected WhatsApp approval from non-allowlisted number %s", sender)
                await run_in_threadpool(send_whatsapp_text, sender, "⛔ This number is not authorised to approve plans.")
                return {"status": "forbidden"}
            try:
                receipt = await run_in_threadpool(
                    _execute, ExecutePlanRequest(run_id=run_id, playbook_id=playbook_id, approved_by=f"whatsapp:{sender}")
                )
            except HTTPException as exc:
                await run_in_threadpool(send_whatsapp_text, sender, f"⚠️ Could not execute: {exc.detail}")
                return {"status": "error", "detail": exc.detail}
            await run_in_threadpool(
                send_whatsapp_text, sender,
                f"✅ *APPROVED* {receipt.playbook_id} for run {receipt.run_id}\n"
                f"• Draft PO: {receipt.po_number}\n• Cost: ₹{receipt.total_cost_inr:,}\n"
                f"• Modelled P(on-time): {receipt.confidence_pct}%\n"
                f"Drafts generated; send POs/notices through your normal channels.",
            )
            return {"status": "success", "action": "plan_executed"}
        if button_id == "VIEW_STATUS":
            await run_in_threadpool(send_whatsapp_text, sender, _status_text())
            return {"status": "success", "action": "status_sent"}
        return {"status": "ignored"}

    body_text = msg.get("text", {}).get("body", "").strip()
    if not body_text:
        return {"status": "ignored"}

    open_rfq = sourcing.find_open_rfq_by_number(sender)
    if open_rfq:
        run_id, supplier_id = open_rfq
        await run_in_threadpool(sourcing.record_reply, run_id, supplier_id, body_text, f"whatsapp:{sender}")
        await run_in_threadpool(send_whatsapp_text, sender, "🙏 Thank you — your reply has been recorded. This is not yet a purchase order.")
        return {"status": "success", "action": "vendor_reply_recorded", "run_id": run_id}
    if body_text.lower() in ("status", "plant", "check"):
        await run_in_threadpool(send_whatsapp_text, sender, _status_text())
        return {"status": "ok"}

    result = await run_in_threadpool(_run_pipeline, body_text, "META_WHATSAPP_CLOUD_API")
    winner_id = result["recommended_plan_id"]
    await run_in_threadpool(
        send_whatsapp_interactive_buttons,
        sender,
        _winner_summary(result),
        [
            {"id": f"APPROVE:{result['run_id']}:{winner_id}", "title": f"Approve {winner_id}"},
            {"id": "VIEW_STATUS", "title": "Plant status"},
        ],
        "Disruption detected",
        "Approval requires an authorised number",
    )
    return {"status": "success", "run_id": result["run_id"]}


@app.get("/api/v1/webhooks/whatsapp")
async def verify_meta_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token") or ""
    challenge = request.query_params.get("hub.challenge") or ""
    if (
        mode == "subscribe"
        and settings.META_WA_VERIFY_TOKEN
        and secrets.compare_digest(token, settings.META_WA_VERIFY_TOKEN)
    ):
        return Response(content=challenge, media_type="text/plain", status_code=200)
    logger.warning("Meta webhook verification failed")
    return Response(content="Verification failed", status_code=403)


@app.post("/api/v1/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        raw = await request.body()
        if not _verify_meta_signature(raw, request.headers.get("x-hub-signature-256")):
            logger.warning("Rejected WhatsApp webhook with invalid signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
        try:
            import json
            payload = json.loads(raw or b"{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        if payload.get("object") != "whatsapp_business_account":
            return {"status": "ignored"}
        return await _handle_meta_payload(payload)

    # Twilio sandbox (form-encoded). Read-only: it can run analysis but never approve execution.
    if settings.is_production:
        raise HTTPException(status_code=403, detail="Twilio sandbox webhook disabled in production")
    form = await request.form()
    body_text = str(form.get("Body", "")).strip()
    sender = str(form.get("From", "")).strip()
    if not body_text or body_text.lower() in ("hi", "hello", "ping", "test") or "join" in body_text.lower():
        reply = "✅ CascadeZero connected. Send a disruption alert, e.g. 'Flood on NH48, 48h delay, 150 casings short on EV-402'."
    else:
        result = await run_in_threadpool(_run_pipeline, body_text, "TWILIO_WHATSAPP_SANDBOX")
        reply = _winner_summary(result) + "\nApprove from the dashboard."
    logger.info("Twilio reply to %s", sender)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<Response><Message><Body>{html.escape(reply)}</Body></Message></Response>"
    )
    return Response(content=twiml, media_type="text/xml")


@app.get("/api/v1/whatsapp/health", dependencies=[Depends(require_api_key)])
def whatsapp_health():
    """Verify token, phone number, app secret and webhook subscription. Never returns secrets."""
    from app.whatsapp_health import check_whatsapp_health

    return check_whatsapp_health()


# ─── 4. Telemetry (simulated PLC over HTTP) ──────────────────────────────────

@app.post("/api/v1/ingest/plc-telemetry", dependencies=[Depends(require_api_key)])
def ingest_plc_telemetry(telemetry: PlcTelemetryRequest):
    update_rows("production_lines", "line_id", telemetry.line_id, {
        "speed_pct": telemetry.speed_pct,
        "temp_celsius": telemetry.temp_celsius,
        "status": telemetry.status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"success": True, **telemetry.model_dump()}


# ─── 5. ERP CSV sync ─────────────────────────────────────────────────────────

def _int_field(row: Dict[str, str], key: str, default: int) -> int:
    raw = (row.get(key) or "").replace(",", "").strip()
    if not raw:
        return default
    number = float(raw)  # ValueError for non-numeric text
    if not math.isfinite(number) or number < 0 or number > 10**12:
        raise ValueError(f"{key} must be a finite, non-negative number")
    return int(number)


@app.post("/api/v1/ingest/erp-csv", dependencies=[Depends(require_api_key)])
def ingest_erp_csv(payload: ErpCsvSyncRequest):
    """Upsert orders from a Tally/Excel CSV export. New orders are inserted, existing ones updated."""
    if not payload.csv_content.strip():
        raise HTTPException(status_code=400, detail="Empty CSV content")

    imported, errors = [], []
    reader = csv.DictReader(io.StringIO(payload.csv_content))
    for line_no, row in enumerate(reader, start=2):
        order_id = (row.get("order_id") or "").strip()
        if not order_id:
            errors.append({"line": line_no, "error": "missing order_id"})
            continue
        try:
            upsert_row("orders", {
                "order_id": order_id,
                "client": (row.get("client") or "").strip(),
                "required_qty": _int_field(row, "required_qty", 0),
                "sla_penalty_inr": _int_field(row, "sla_penalty_inr", 0),
                "partial_delay_penalty_inr": _int_field(row, "partial_delay_penalty_inr", 0),
                "hours_remaining": _int_field(row, "hours_remaining", 0),
                "deadline_label": (row.get("deadline_label") or "").strip(),
                "status": "ON_TRACK",
                "shortfall_units": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            imported.append(order_id)
        except ValueError as exc:
            errors.append({"line": line_no, "order_id": order_id, "error": str(exc)})

    return {
        "success": not errors,
        "filename": payload.filename,
        "imported_count": len(imported),
        "orders": imported,
        "errors": errors,
    }


# ─── 6. Highway weather ──────────────────────────────────────────────────────

@app.post("/api/v1/ingest/live-highway-check")
def live_highway_check(req: LiveHighwayCheckRequest = LiveHighwayCheckRequest()):
    if settings.has_weather:
        try:
            resp = httpx.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": f"{req.city},IN", "appid": settings.OPENWEATHER_API_KEY, "units": "metric"},
                timeout=4.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                main = data.get("weather", [{}])[0].get("main", "")
                return {
                    "corridor": req.corridor,
                    "city": req.city,
                    "condition": main,
                    "description": data.get("weather", [{}])[0].get("description", ""),
                    "temp_celsius": data.get("main", {}).get("temp"),
                    "flood_risk_level": "ELEVATED" if main.lower() in ("rain", "thunderstorm") else "LOW",
                    "is_live": True,
                    "source": "OpenWeatherMap (city weather; not a road-closure feed)",
                }
        except Exception as exc:
            logger.warning("OpenWeatherMap poll failed: %s", exc)

    return {
        "corridor": req.corridor,
        "city": req.city,
        "condition": "Unknown",
        "description": "No live weather source configured or reachable.",
        "temp_celsius": None,
        "flood_risk_level": "UNKNOWN",
        "is_live": False,
        "source": "Offline — set OPENWEATHER_API_KEY for live data",
    }


# ─── 7. Plan execution (human-approved, server-computed) ─────────────────────

def _execute(req: ExecutePlanRequest) -> ExecutionReceiptResponse:
    run = run_store.get_run(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown or expired run_id; run the simulation again.")
    playbook = next((p for p in run["playbooks"] if p["id"] == req.playbook_id), None)
    if playbook is None:
        raise HTTPException(status_code=404, detail=f"Playbook {req.playbook_id} not in run {req.run_id}")

    # One execution per analysis: a sourced re-plan shares its parent's idempotency key.
    root_id = run.get("parent_run_id") or req.run_id

    def _same(existing: Dict[str, Any]) -> bool:
        return existing.get("run_id") == req.run_id and existing.get("playbook_id") == req.playbook_id

    existing = run_store.get_receipt(root_id)
    if existing and not existing.get("pending"):
        if not _same(existing):
            raise HTTPException(
                status_code=409,
                detail=f"This analysis was already executed ({existing.get('run_id')} / {existing.get('playbook_id')}); "
                       f"run a new analysis to choose a different plan.",
            )
        return ExecutionReceiptResponse(**{**existing, "already_executed": True})
    if not playbook.get("feasible", True):
        raise HTTPException(status_code=409, detail="Playbook is infeasible (capacity exhausted); choose another.")
    if not run_store.claim_execution(root_id):
        existing = run_store.get_receipt(root_id) or {}
        if existing.get("pending") or not _same(existing):
            raise HTTPException(status_code=409, detail="This analysis is already being executed or was executed with another plan.")
        return ExecutionReceiptResponse(**{**existing, "already_executed": True})

    try:
        payload = playbook.get("tally_po_payload") or {}
        po_number = payload.get("po_number") or f"PO-CZ-{uuid.uuid4().hex[:8].upper()}"
        order_id = run.get("order_id", "EV-402")
        now = datetime.now(timezone.utc).isoformat()

        save_purchase_order({
            "po_number": po_number,
            "playbook_id": playbook["id"],
            "order_id": order_id,
            "vendor_allocations_json": playbook["vendor_allocations"],
            "overtime_hours": playbook["overtime_hours"],
            "total_cost_inr": playbook["total_mitigation_cost_inr"],
            "net_sla_saved_inr": playbook["net_sla_saved_inr"],
            "confidence_pct": playbook["confidence_pct"],
            "tally_xml_payload": payload.get("tally_xml", ""),
            "shift_broadcast_msg": playbook["shift_broadcast_msg"],
            "client_sla_notice": playbook["client_sla_notice"],
            "status": "APPROVED_DRAFT",
            "approved_by": req.approved_by,
            "run_id": req.run_id,
            "created_at": now,
        })

        new_order_status = {
            "SLA_RENEGOTIATION": "EXTENSION_REQUESTED",
            "NO_ACTION": "RISK_ACCEPTED",
        }.get(playbook["strategy_type"], "RECOVERY_IN_PROGRESS")
        update_rows("orders", "order_id", order_id, {"status": new_order_status, "updated_at": now})
        for a in playbook["vendor_allocations"]:
            update_rows("suppliers", "id", a["supplier_id"], {
                "status": "PO_DRAFTED", "inbound_qty": a["units_allocated"], "updated_at": now,
            })
        if playbook["overtime_hours"] > 0:
            for lid in ("LINE-1", "LINE-3"):
                update_rows("production_lines", "line_id", lid, {"status": "OVERTIME_SCHEDULED", "updated_at": now})

        log_agent_step(
            run_id=req.run_id, step_order=10,
            agent_name="Human Approver", agent_role="HITL Execution", badge_color="emerald",
            tool_called="commit_purchase_order()",
            tool_output_summary=f"PO {po_number} approved by {req.approved_by}; order #{order_id} → {new_order_status}.",
            message=(
                f"✅ {playbook['id']} approved by {req.approved_by}. Draft Tally PO {po_number}, "
                f"shift notice ({playbook['overtime_hours']}h) and client notice generated. "
                f"Nothing has been sent to suppliers automatically."
            ),
        )

        receipt = ExecutionReceiptResponse(
            success=True,
            run_id=req.run_id,
            po_number=po_number,
            playbook_id=playbook["id"],
            order_id=order_id,
            approved_by=req.approved_by,
            total_cost_inr=playbook["total_mitigation_cost_inr"],
            net_sla_saved_inr=playbook["net_sla_saved_inr"],
            confidence_pct=playbook["confidence_pct"],
            tally_xml_payload=payload.get("tally_xml", ""),
            tally_json_payload={
                "voucher_type": "Purchase Order",
                "po_number": po_number,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "company": default_factory_name(),
                "total_cost_inr": playbook["total_mitigation_cost_inr"],
                "allocations": playbook["vendor_allocations"],
                "overtime_hours": playbook["overtime_hours"],
            },
            shift_broadcast_msg=playbook["shift_broadcast_msg"],
            client_sla_notice=playbook["client_sla_notice"],
            executed_at=now,
        )
        run_store.store_receipt(root_id, receipt.model_dump())
        return receipt
    except Exception:
        run_store.release_claim(root_id)
        raise


@app.post("/api/v1/execute-plan", dependencies=[Depends(require_api_key)])
def execute_plan(req: ExecutePlanRequest):
    logger.info("Executing %s from run %s (approved_by=%s)", req.playbook_id, req.run_id, req.approved_by)
    return _execute(req)


# ─── 8. Sourcing Agent (confirm vendor offers before approval) ───────────────

def _sourcing_call(fn, *args):
    try:
        return fn(*args)
    except sourcing.SourcingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.post("/api/v1/sourcing/start", dependencies=[Depends(require_api_key)])
def start_sourcing(req: SourcingStartRequest):
    """Send enquiries to the vendors in a plan and start the confirm → re-plan loop."""
    return _sourcing_call(sourcing.start_sourcing, req.run_id, req.playbook_id)


@app.get("/api/v1/sourcing/{run_id}")
def get_sourcing(run_id: str):
    """Current enquiries, offers and (when finished) the confirmed plan. Also expires timed-out enquiries."""
    return _sourcing_call(sourcing.view, run_id)


@app.post("/api/v1/sourcing/{run_id}/vendor-reply", dependencies=[Depends(require_api_key)])
def post_vendor_reply(run_id: str, req: SourcingReplyRequest):
    """Record a vendor's reply typed by an operator (phone call) or, in simulated mode, a simulated vendor."""
    return _sourcing_call(sourcing.record_reply, run_id, req.supplier_id, req.text, f"operator:{req.entered_by}")


# ─── 9. Reset ────────────────────────────────────────────────────────────────

@app.post("/api/v1/reset", dependencies=[Depends(require_api_key)])
def reset_factory():
    if settings.is_production:
        raise HTTPException(status_code=403, detail="Reset is disabled in production")
    run_store.clear()
    sourcing.clear()
    return reset_to_seed()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
