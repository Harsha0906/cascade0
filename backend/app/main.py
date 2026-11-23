"""
CascadeZero — FastAPI server

  GET  /api/v1/state                       factory snapshot                      [any role]
  GET  /api/v1/factory                     factory model: vendors + lines        [any role]
  POST /api/v1/simulate-crisis             run the agent graph + solver          [owner/approver, API key]
  GET  /api/v1/webhooks/whatsapp           Meta verification handshake
  POST /api/v1/webhooks/whatsapp           Meta (HMAC-verified) / Twilio webhook
  POST /api/v1/telegram/webhook            Telegram Bot API updates (secret-token header)
  POST /api/v1/channels/link-code          one-time code to link a chat to this user [any role]
  POST /api/v1/ingest/plc-telemetry        line telemetry (HTTP JSON, simulated) [owner/approver, API key]
  POST /api/v1/ingest/erp-csv              Tally/Excel CSV order upsert          [owner/approver, API key]
  POST /api/v1/ingest/stock-summary        Tally stock summary CSV               [owner/approver, API key]
  POST /api/v1/ingest/open-purchase-orders open purchase orders CSV              [owner/approver, API key]
  POST /api/v1/ingest/sales-order-lines    sales order lines CSV                 [owner/approver, API key]
  POST /api/v1/ingest/live-highway-check   weather check (labelled when offline) [any role, API key]
  POST /api/v1/execute-plan                execute a server-computed playbook    [owner/approver]
  POST /api/v1/deliveries                  record a vendor delivery (learns reliability) [owner/approver]
  GET  /api/v1/deliveries                  delivery outcomes (?status=PENDING|DELIVERED) [any role]
  POST /api/v1/sourcing/start              Sourcing Agent: send vendor enquiries [owner/approver]
  GET  /api/v1/sourcing/{run_id}           enquiry status + confirmed plan       [any role]
  POST /api/v1/sourcing/{run_id}/vendor-reply  record a vendor reply           [owner/approver]
  POST /api/v1/client/draft                Client Agent: draft an extension request [owner/approver]
  POST /api/v1/client/approve              human sign-off: send it to the client [owner/approver]
  POST /api/v1/client/answer               record the client's answer (re-plans) [owner/approver]
  GET  /api/v1/client/{run_id}             the run's extension request / answer  [any role]
  GET  /api/v1/whatsapp/health             WhatsApp configuration check          [owner/approver, API key]
  POST /api/v1/reset                       reset demo data                       [owner]

Security model (app/auth.py): every route except `/`, `/healthz` and the signature-checked
WhatsApp / secret-checked Telegram webhooks needs a verified actor: a Supabase user (Authorization: Bearer <access token>)
with a role in the factory (`factory_members`), or, on automation endpoints only, the machine
key in X-API-Key.

Tenancy: every endpoint authorises against the factory of the RESOURCE it touches: a run's
`factory_id` (sourcing sessions, client records and receipts through their run), a delivery
outcome's or a production line's `factory_id`, or the factory a request names
(`factory_id` query/body field, default: the caller's own factory). A caller who is not a member
of that factory gets 404, identical to an unknown resource; a member without the role gets 403. `approved_by` / `entered_by` always come from the verified user, never from
the request body. AUTH_MODE=dev (offline storage only, never production) accepts X-Dev-User.
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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import importers, inbound, reliability, run_store, setup_api
from app.auth import (
    ChooseFactory,
    ANY_ROLE,
    OWNER_ONLY,
    WRITE_ROLES,
    Actor,
    machine_actor,
    require,
    user_actor,
)
from app.agents import client as client_agent
from app.agents import sourcing
from app.agents.graph import run_cascade_pipeline
from app.channels import TelegramChannel, WhatsAppChannel
from app import db
from app.config import settings
from app.factory_model import FactoryDataError, load_factory_model
from app.solver import SolverInputError
from app.db import (
    default_factory_name,
    get_full_state,
    insert_row,
    reset_to_seed,
    update_rows,
    upsert_row,
)
from app.meta_whatsapp import send_whatsapp_interactive_buttons, send_whatsapp_text
from app.schemas import (
    DeliveryRecordRequest,
    ErpCsvSyncRequest,
    ResetRequest,
    ExecutePlanRequest,
    ExecutionReceiptResponse,
    LinkCodeRequest,
    LiveHighwayCheckRequest,
    PlcTelemetryRequest,
    SimulateCrisisRequest,
    ClientAnswerRequest,
    ClientApproveRequest,
    ClientDraftRequest,
    SourcingReplyRequest,
    SourcingStartRequest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("cascadezero.server")

def _docs_kwargs(cfg) -> Dict[str, Any]:
    """In production the interactive docs and the OpenAPI schema are not served."""
    return {"docs_url": None, "redoc_url": None, "openapi_url": None} if cfg.is_production else {}


app = FastAPI(
    title="CascadeZero API",
    description="Disruption-response copilot: LLM extraction + MILP/Monte Carlo planning with human approval",
    version="2.1.0",
    **_docs_kwargs(settings),
)

# ─── Startup security posture ────────────────────────────────────────────────
def _enforce_startup_security(cfg) -> None:
    """Refuse to start on an auth misconfiguration (always) or any security gap (production)."""
    fatal = cfg.auth_problems()
    if fatal:
        raise RuntimeError("Refusing to start: " + "; ".join(fatal))
    problems = cfg.security_problems()
    if cfg.is_production and problems:
        raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    for p in problems:
        logger.warning("SECURITY (dev mode): %s", p)
    if cfg.AUTH_MODE == "dev":
        logger.warning("SECURITY (dev mode): AUTH_MODE=dev, X-Dev-User headers are trusted")


_enforce_startup_security(settings)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(setup_api.router)

# Endpoints that touch no factory resource (configuration checks, weather): a role in the
# caller's own factory. Everything factory-scoped authorises per resource (helpers below).
machine_read_access = require(*ANY_ROLE, machine=True)
machine_write_access = require(*WRITE_ROLES, machine=True)

_RUN_GONE = "Unknown or expired run_id; run the analysis again."


def _authorize_resource(actor: Actor, factory_id: Optional[str], roles, not_found: str) -> str:
    """Authorise against the factory owning a resource. A non-member sees exactly the 404 an
    unknown resource gives (`not_found`), so a foreign id cannot be told from a missing one."""
    try:
        return actor.authorize_resource(factory_id, *roles)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=not_found) from None
        raise


def _authorized_run(actor: Actor, run_id: str, roles, not_found: str = _RUN_GONE) -> Dict[str, Any]:
    """The stored run, after authorising `roles` in the run's own factory. A derived run
    (sourced / client re-plan) must belong to the same factory as its root."""
    run = run_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=not_found)
    factory_id = run.get("factory_id")
    parent_id = run.get("parent_run_id")
    if parent_id:
        root = run_store.get_run(parent_id)
        if root is None or root.get("factory_id") != factory_id:
            raise HTTPException(status_code=404, detail=not_found)
    _authorize_resource(actor, factory_id, roles, not_found)
    return run


def _run_pipeline(
    message: str,
    source_channel: str,
    delay=None,
    shortfall=None,
    line_speeds=None,
    order_id=None,
    extra: Optional[Dict[str, Any]] = None,
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    result = run_cascade_pipeline(
        raw_message=message,
        source_channel=source_channel,
        override_delay_hours=delay,
        override_shortfall_units=shortfall,
        override_line_speeds=line_speeds,
        order_id=order_id,
        factory_id=factory_id,
    )
    result.update(extra or {})   # request context kept with the run (GET /api/v1/runs/{run_id})
    run_store.save_run(result)
    insert_row("disruption_events", {
        "source_channel": source_channel,
        "raw_message": message,
        "delay_hours": result["delay_hours"],
        "shortfall_units": result["shortfall_units"],
        "factory_id": result["factory_id"],
        "order_id": result["order_id"],
        "affected_supplier_id": result["affected_supplier_id"],
        "line_impacts": result["line_impacts"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return result


# ─── 1. Health & state ───────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"app": "CascadeZero", "status": "online", "factory": default_factory_name(), "docs_url": "/docs"}


@app.get("/healthz")
def healthz():
    """Readiness probe: database reachable and migrations applied. Never raises, no secrets."""
    required = db.REQUIRED_MIGRATION_LEVEL
    try:
        level, db_status = db.migration_level(), "ok"
    except db.DatabaseError:
        level, db_status = 0, "error"
    ready = db_status == "ok" and level >= required
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"storage": settings.storage_mode, "db": db_status, "migration_level": level,
                 "required_migration_level": required, "ready": ready},
    )


def _check_migration_level() -> None:
    """Startup check: complain when the database schema is behind; refuse to start in production."""
    required = db.REQUIRED_MIGRATION_LEVEL
    try:
        level = db.migration_level()
    except db.DatabaseError as exc:
        level, problem = 0, f"database unreachable at startup ({exc})"
    else:
        problem = f"database migration level {level} is below required {required}: apply supabase/migrations"
    if level < required:
        logger.error("STARTUP: %s", problem)
        if settings.is_production:
            raise RuntimeError("Refusing to start in production: " + problem)


@app.on_event("startup")
def _startup_migration_check() -> None:
    if settings.storage_mode == "supabase":
        _check_migration_level()


@app.get("/api/v1/state")
def get_state(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    return get_full_state(actor.authorize(factory_id, *ANY_ROLE))


@app.exception_handler(ChooseFactory)
async def _choose_factory_handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": exc.detail, "factories": exc.factories})


@app.exception_handler(db.DatabaseError)
async def _database_error_handler(request: Request, exc: db.DatabaseError):
    """Live-database failure: generic 503. The driver message stays in the server log."""
    return JSONResponse(
        status_code=503,
        content={"detail": f"Database unavailable: {exc.operation} {exc.table}"},
    )


# Sent to WhatsApp senders when factory data is invalid; the detail stays in the server log.
_MISCONFIGURED_REPLY = "Sorry — the planning service is misconfigured; the operator has been notified."


def _factory_503(exc: Exception) -> HTTPException:
    logger.error("Factory data invalid: %s", exc)
    return HTTPException(status_code=503, detail=f"Factory data invalid: {exc}")


@app.get("/api/v1/factory")
def get_factory(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    """The factory model the planner uses (vendors + lines), loaded from the database."""
    fid = actor.authorize(factory_id, *ANY_ROLE)
    try:
        m = load_factory_model(fid)
    except FactoryDataError as exc:
        raise _factory_503(exc)
    return {
        "factory_id": m.factory_id,
        "name": m.name,
        "vendors": [
            {k: getattr(v, k) for k in ("supplier_id", "name", "sourcing_role", "max_units",
                                        "unit_cost", "flat_cost", "lead_hours", "reliability_pct",
                                        "prior_total", "outcomes_total")}
            for v in m.vendors
        ],
        "lines": [
            {k: getattr(l, k) for k in ("line_id", "name", "rated_units_per_hour", "ot_units_per_hour",
                                        "ot_cost_per_hour", "max_ot_hours")}
            for l in m.lines
        ],
    }


@app.get("/api/v1/runs/latest")
def get_latest_run(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    """Summary of the factory's most recent analysis run (used by the mobile controller to approve it)."""
    run_id = run_store.latest_run_id(actor.authorize(factory_id, *ANY_ROLE))
    run = run_store.get_run(run_id) if run_id else None
    if not run:
        return {"run_id": None}
    winner = next((p for p in run["playbooks"] if p["id"] == run["recommended_plan_id"]), None)
    receipt = db.get_receipt(run.get("parent_run_id") or run_id)
    return {
        "run_id": run_id,
        "recommended_plan_id": run["recommended_plan_id"],
        "winner": winner,
        "executed": receipt is not None,
        "ai_mode": run.get("ai_mode", {}),
        "parent_run_id": run.get("parent_run_id"),
    }


@app.get("/api/v1/runs/{run_id}")
def get_run_by_id(run_id: str, actor: Actor = Depends(user_actor)):
    """A stored run in the simulate-crisis response shape, so the dashboard can restore the latest
    run after a reload; plus its root run id (for the Sourcing and Client panels) and whether it
    was executed."""
    run = _authorized_run(actor, run_id, ANY_ROLE, not_found=f"Unknown run {run_id}")
    root_id = run.get("parent_run_id") or run_id
    return {
        **_run_response(run),
        "root_run_id": root_id,
        "parent_run_id": run.get("parent_run_id"),
        "executed": db.get_receipt(root_id) is not None,
    }


# ─── 2. Crisis simulation ────────────────────────────────────────────────────

@app.get("/api/v1/scenarios")
def list_scenarios(factory_id: Optional[str] = None, actor: Actor = Depends(user_actor)):
    """Preset disruption scenarios of the caller's factory (read-only)."""
    fid = actor.authorize(factory_id, *ANY_ROLE)
    return [
        {k: row.get(k) for k in (
            "scenario_id", "title", "summary", "raw_message",
            "delay_hours", "shortfall_units", "line_speeds", "order_id",
        )}
        for row in db.get_scenarios(fid)
    ]


def _run_response(result: Dict[str, Any]) -> Dict[str, Any]:
    """The simulate-crisis response for a pipeline result or a stored run (same shape)."""
    line_names = {l.line_id: l.name for l in result["factory_model"].lines}
    return {
        "success": True,
        "run_id": result["run_id"],
        "scenario_id": result.get("scenario_id"),
        "headline": result.get("crisis_headline", ""),
        "extracted_parameters": {
            "delay_hours": result["delay_hours"],
            "line_impacts": [
                {
                    "line_id": li["line_id"],
                    "name": line_names[li["line_id"]],
                    "speed_pct": li["speed_pct"],
                    "temp_celsius": li["temp_celsius"],
                }
                for li in result["line_impacts"]
            ],
            "affected_supplier_id": result["affected_supplier_id"],
            "shortfall_units": result["shortfall_units"],
            "shortfall_source": result["shortfall_source"],
            "shortfall_breakdown": result["shortfall_breakdown"],
            "alert_stated_shortfall": result["alert_stated_shortfall"],
            "affected_order_id": result["order_id"],
            "order_selection": result["order_selection"],
            "other_order_shortfalls": result["other_order_shortfalls"],
            "blocked_route": result.get("blocked_route"),
            "blocked_routes": result.get("blocked_routes", []),
            "weather_alert": result.get("weather_alert", False),
            "route_note": result.get("route_note"),
            "source": result.get("extraction_source", "unknown"),
            "overridden_by_preset_or_slider": bool(result.get("overridden_by_preset_or_slider")),
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


@app.post("/api/v1/simulate-crisis")
def simulate_crisis(req: SimulateCrisisRequest, actor: Actor = Depends(machine_actor)):
    factory_id = actor.authorize(req.factory_id, *WRITE_ROLES)
    scenarios = {r["scenario_id"]: r for r in db.get_scenarios(factory_id)}
    if req.scenario_id is not None and req.scenario_id not in scenarios:
        raise HTTPException(status_code=404, detail=f"Unknown scenario_id {req.scenario_id}")

    structured = any(v is not None for v in (
        req.override_line_speeds, req.override_shortfall_units, req.override_delay_hours)) or bool(req.order_id)
    preset = None
    if req.raw_message:
        message = req.raw_message
    elif req.scenario_id is not None:
        preset = scenarios[req.scenario_id]
        message = preset["raw_message"]
    elif structured:
        # Sliders: every parameter comes from the overrides; resolution still requires each one.
        message = ""
    else:
        raise HTTPException(
            status_code=422, detail="Provide scenario_id or raw_message (or structured overrides)")

    delay, shortfall = req.override_delay_hours, req.override_shortfall_units
    line_speeds = dict(req.override_line_speeds) if req.override_line_speeds is not None else None
    order_id = req.order_id
    if preset is not None and req.scenario_id is not None:
        delay = preset["delay_hours"] if delay is None else delay
        shortfall = preset["shortfall_units"] if shortfall is None else shortfall
        if line_speeds is None:
            line_speeds = dict(preset.get("line_speeds") or {})
        order_id = order_id or preset.get("order_id")

    logger.info("Simulating crisis via %s: %s", req.source_channel, message[:80])
    try:
        overridden = any(v is not None for v in (delay, shortfall, line_speeds))
        result = _run_pipeline(message, req.source_channel, delay, shortfall, line_speeds, order_id,
                               extra={"scenario_id": req.scenario_id, "overridden_by_preset_or_slider": overridden},
                               factory_id=factory_id)
    except SolverInputError as exc:
        raise HTTPException(status_code=422, detail=f"Cannot plan for these inputs: {exc}")
    except FactoryDataError as exc:
        raise _factory_503(exc)

    return _run_response(result)


# ─── 3. WhatsApp webhook ─────────────────────────────────────────────────────

def _verify_meta_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    if not settings.META_APP_SECRET:
        # Unsigned payloads only against offline (in-memory) storage in development; with a live
        # database they are refused, since an approval here would execute without a verified actor.
        return settings.storage_mode == "offline" and not settings.is_production
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.META_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


# The chat flow itself (dedupe, /link, status, vendor replies, alerts, approvals) is shared by
# every channel: app/inbound.py. These are kept here for the Twilio sandbox and existing callers.
_status_text = inbound.status_text
_winner_summary = inbound.winner_summary


def _whatsapp_channel() -> WhatsAppChannel:
    """The WhatsApp adapter. The send helpers are bound late (looked up on this module at call
    time), so a patched `main.send_whatsapp_text` is what the adapter calls."""
    return WhatsAppChannel(
        send_text=lambda to, text: send_whatsapp_text(to, text),
        send_buttons=lambda to, text, buttons, header=None, footer=None:
            send_whatsapp_interactive_buttons(to, text, buttons, header, footer),
    )


def _telegram_channel() -> TelegramChannel:
    return TelegramChannel(settings.TELEGRAM_BOT_TOKEN)


async def _handle_meta_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        payload["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return {"status": "ignored"}
    channel = _whatsapp_channel()
    messages = channel.parse_inbound(payload)   # delivery/read receipts are logged, yield nothing
    if not messages:
        return {"status": "ok"}
    return await inbound.handle(channel, messages[0])


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

    # Twilio sandbox (form-encoded, unsigned). Offline development only: it runs analysis
    # anonymously (never approves), so it is not served with a live database or in production.
    if settings.is_production or settings.storage_mode != "offline":
        raise HTTPException(status_code=404, detail="Not Found")
    form = await request.form()
    body_text = str(form.get("Body", "")).strip()
    sender = str(form.get("From", "")).strip()
    if not body_text or body_text.lower() in ("hi", "hello", "ping", "test") or "join" in body_text.lower():
        reply = "✅ CascadeZero connected. Send a disruption alert, e.g. state the delay in hours, the units short, the affected line and order."
    else:
        try:
            result = await run_in_threadpool(_run_pipeline, body_text, "TWILIO_WHATSAPP_SANDBOX")
            reply = _winner_summary(result) + "\nApprove from the dashboard."
        except (FactoryDataError, db.DatabaseError) as exc:
            logger.error("Twilio pipeline failed, factory data/database unavailable: %s", exc)
            reply = _MISCONFIGURED_REPLY
        except SolverInputError as exc:
            reply = f"⚠️ Cannot plan for these inputs: {exc}"
    logger.info("Twilio reply to %s", sender)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<Response><Message><Body>{html.escape(reply)}</Body></Message></Response>"
    )
    return Response(content=twiml, media_type="text/xml")


@app.get("/api/v1/whatsapp/health", dependencies=[Depends(machine_write_access)])
def whatsapp_health():
    """Verify token, phone number, app secret and webhook subscription. Never returns secrets."""
    from app.whatsapp_health import check_whatsapp_health

    return check_whatsapp_health()


# ─── 3b. Telegram webhook and chat linking ─────────────────────────────────────

@app.post("/api/v1/telegram/webhook")
async def telegram_webhook(request: Request):
    """Telegram Bot API updates. Telegram echoes the setWebhook `secret_token` in
    X-Telegram-Bot-Api-Secret-Token; without TELEGRAM_WEBHOOK_SECRET every update is refused."""
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    given = request.headers.get("x-telegram-bot-api-secret-token") or ""
    if not expected or not secrets.compare_digest(given.encode(), expected.encode()):
        logger.warning("Rejected Telegram webhook with a missing or wrong secret token")
        raise HTTPException(status_code=401, detail="Invalid secret token")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    channel = _telegram_channel()
    # parse_inbound answers a button's callback query (a Bot API call): off the event loop.
    messages = await run_in_threadpool(channel.parse_inbound, payload)
    if not messages:
        return {"status": "ignored"}
    return await inbound.handle(channel, messages[0])


@app.post("/api/v1/channels/link-code")
def create_channel_link_code(req: Optional[LinkCodeRequest] = None, actor: Actor = Depends(user_actor)):
    """A one-time code (15 min) that links a WhatsApp/Telegram chat to the signed-in user for one
    factory: send `/link <code>` to the bot. Any role may link; approvals still need owner/approver."""
    factory_id = actor.authorize((req or LinkCodeRequest()).factory_id, *ANY_ROLE)
    if not actor.user_id:
        raise HTTPException(status_code=403, detail="Linking a chat needs a signed-in user")
    return inbound.create_link_code(actor.user_id, factory_id)


# ─── 4. Telemetry (simulated PLC over HTTP) ──────────────────────────────────

@app.post("/api/v1/ingest/plc-telemetry")
def ingest_plc_telemetry(telemetry: PlcTelemetryRequest, actor: Actor = Depends(machine_actor)):
    unknown = f"Unknown line_id {telemetry.line_id}"
    line = db.get_production_line(telemetry.line_id)
    if line is None:
        raise HTTPException(status_code=404, detail=unknown)
    _authorize_resource(actor, line.get("factory_id"), WRITE_ROLES, unknown)
    update_rows("production_lines", "line_id", telemetry.line_id, {
        "speed_pct": telemetry.speed_pct,
        "temp_celsius": telemetry.temp_celsius,
        "status": telemetry.status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"success": True, **telemetry.model_dump()}


# ─── 5. ERP CSV sync ─────────────────────────────────────────────────────────

def _int_field(row: Dict[str, str], key: str, default: Optional[int] = None) -> int:
    """Parse a non-negative integer column. With no default the column is required."""
    raw = (row.get(key) or "").replace(",", "").strip()
    if not raw:
        if default is None:
            raise ValueError(f"{key} is required")
        return default
    number = float(raw)  # ValueError for non-numeric text
    if not math.isfinite(number) or number < 0 or number > 10**12:
        raise ValueError(f"{key} must be a finite, non-negative number")
    return int(number)


# Priority of a new order imported without a `priority` column: the lowest (same as the
# database DEFAULT), so an unranked order never reserves stock ahead of a ranked one.
DEFAULT_ORDER_PRIORITY = 100


@app.post("/api/v1/ingest/erp-csv")
def ingest_erp_csv(payload: ErpCsvSyncRequest, actor: Actor = Depends(machine_actor)):
    """Upsert orders from a Tally/Excel CSV export. New orders are inserted, existing ones updated.

    required_qty and sla_penalty_inr are always required; partial_delay_penalty_inr and a deadline
    (`due_date`, IST, or `hours_remaining` from now) are required for a new order (an existing order
    keeps its value when the column is blank). The deadline is stored as the absolute `due_at`.
    `priority` is optional (lower ranks first); a new order without it gets DEFAULT_ORDER_PRIORITY.
    Updates never overwrite the order's status or shortfall_units.
    """
    factory_id = actor.authorize(payload.factory_id, *WRITE_ROLES)
    if not payload.csv_content.strip():
        raise HTTPException(status_code=400, detail="Empty CSV content")

    imported, errors = [], []
    reader = csv.DictReader(io.StringIO(payload.csv_content.lstrip("\ufeff")))
    reader.fieldnames = [importers.normalize_header(h) for h in (reader.fieldnames or [])]
    for line_no, row in enumerate(reader, start=2):
        order_id = (row.get("order_id") or "").strip()
        if not order_id:
            errors.append({"line": line_no, "error": "missing order_id"})
            continue
        try:
            existing = db.get_order(order_id)
            if existing is not None and existing.get("factory_id") != factory_id:
                # Order ids are global keys: never overwrite (or move) another factory's order.
                raise ValueError(f"order_id {order_id} cannot be used by this factory") from None
            record = {
                "order_id": order_id,
                "required_qty": _int_field(row, "required_qty"),
                "sla_penalty_inr": _int_field(row, "sla_penalty_inr"),
                "factory_id": factory_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if existing is None or (row.get("partial_delay_penalty_inr") or "").strip():
                record["partial_delay_penalty_inr"] = _int_field(row, "partial_delay_penalty_inr")
            due_text = (row.get("due_date") or row.get("due_at") or "").strip()
            if due_text:
                due_at = importers.parse_eta(due_text)
                record["due_at"] = due_at.isoformat()
                hours = (due_at - datetime.now(timezone.utc)).total_seconds() / 3600.0
                record["hours_remaining"] = max(0, int(round(hours)))  # display only; recomputed on read
            elif (row.get("hours_remaining") or "").strip():
                record["hours_remaining"] = _int_field(row, "hours_remaining")
                record["due_at"] = (datetime.now(timezone.utc)
                                    + timedelta(hours=record["hours_remaining"])).isoformat()
            elif existing is None:
                raise ValueError("due_date or hours_remaining is required")
            if (row.get("priority") or "").strip():
                record["priority"] = _int_field(row, "priority")
            elif existing is None:
                record["priority"] = DEFAULT_ORDER_PRIORITY
            for key in ("client", "deadline_label"):
                value = (row.get(key) or "").strip()
                if value or existing is None:  # blank on update keeps the stored value
                    record[key] = value
            if existing is None:
                record["status"] = "ON_TRACK"
                record["shortfall_units"] = 0
            try:   # conditional write: closes the race between the check above and this write
                db.upsert_owned("orders", record, ("order_id",))
            except db.OwnershipConflict:
                raise ValueError(f"order_id {order_id} cannot be used by this factory") from None
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


# ─── 5b. Inventory CSV imports (Tally/Excel) ─────────────────────────────────

def _require_csv(payload: ErpCsvSyncRequest) -> None:
    if not payload.csv_content.strip():
        raise HTTPException(status_code=400, detail="Empty CSV content")


def _import_response(payload: ErpCsvSyncRequest, result: importers.ImportResult) -> Dict[str, Any]:
    return {
        "success": not result.errors,
        "filename": payload.filename,
        "imported_count": len(result.rows),
        "errors": result.errors,
        "warnings": result.warnings,
    }


def _factory_item_codes(factory_id: str) -> set[str]:
    return {i["item_code"] for i in db.get_items(factory_id)}


def _snapshot_warning(text: str) -> Dict[str, Any]:
    return {"line": None, "warning": text}


@app.post("/api/v1/ingest/stock-summary")
def ingest_stock_summary(payload: ErpCsvSyncRequest, actor: Actor = Depends(machine_actor)):
    """Replace on-hand stock from a Tally Stock Summary export (creates items with new codes).

    The file is a full snapshot of the factory's stock: an item of the factory it does not mention
    is set to on_hand_qty 0 (Tally hides zero-balance items; reported in warnings). An item on a
    row with an error is left unchanged.
    """
    factory_id = actor.authorize(payload.factory_id, *WRITE_ROLES)
    _require_csv(payload)
    result = importers.parse_stock_summary(payload.csv_content, factory_id, _factory_item_codes(factory_id))
    # Every item of the factory (with or without a stock row) is covered by the snapshot.
    before = (_factory_item_codes(factory_id) | set(db.get_stock_levels(factory_id))
              if result.header_ok else set())
    now = datetime.now(timezone.utc).isoformat()
    for item in result.items:
        upsert_row("items", item, key_columns=("factory_id", "item_code"))
    for row in result.rows:
        upsert_row("stock_levels", {**row, "as_of": now}, key_columns=("factory_id", "item_code"))
    # Tally's Stock Summary hides zero-balance items, so an item missing from the snapshot ran out.
    for code in sorted(before - result.mentioned):
        upsert_row("stock_levels", {"factory_id": factory_id, "item_code": code, "on_hand_qty": 0, "as_of": now},
                   key_columns=("factory_id", "item_code"))
        result.warnings.append(_snapshot_warning(f"{code} not in file — stock set to 0"))
    return _import_response(payload, result)


@app.post("/api/v1/ingest/open-purchase-orders")
def ingest_open_purchase_orders(payload: ErpCsvSyncRequest, actor: Actor = Depends(machine_actor)):
    """Import open inbound shipments from a pending purchase orders export (dates are IST).

    The file is a full snapshot of the factory's pending POs: an OPEN shipment it does not
    mention is marked CLOSED (received or cancelled) and listed in warnings.
    """
    factory_id = actor.authorize(payload.factory_id, *WRITE_ROLES)
    _require_csv(payload)
    suppliers = {s["id"] for s in db.get_all_suppliers()
                 if s.get("factory_id") == factory_id}
    result = importers.parse_open_purchase_orders(
        payload.csv_content, factory_id, _factory_item_codes(factory_id), suppliers,
        datetime.now(timezone.utc),
        existing_shipments={r["shipment_id"]: r for r in db.fetch_all("inbound_shipments")},
    )
    before = ({s["shipment_id"] for s in db.get_inbound_shipments(factory_id)}
              if result.header_ok else set())
    for row in list(result.rows):
        try:   # conditional write: never overwrites another factory's shipment with this PO number
            db.upsert_owned("inbound_shipments", row, ("shipment_id",))
        except db.OwnershipConflict:
            result.rows.remove(row)
            result.errors.append({"line": None, "error": f"PO number {row['shipment_id']} belongs to another factory"})
    closed = sorted(before - result.mentioned)
    for sid in closed:
        db.update_rows_where("inbound_shipments", {"shipment_id": sid, "factory_id": factory_id},
                             {"status": "CLOSED"})
    if closed:
        result.warnings.append(_snapshot_warning(
            f"{len(closed)} open PO(s) not in this file marked CLOSED (received or cancelled; "
            f"each file is a full snapshot of pending POs): {', '.join(closed)}"))
    return _import_response(payload, result)


@app.post("/api/v1/ingest/sales-order-lines")
def ingest_sales_order_lines(payload: ErpCsvSyncRequest, actor: Actor = Depends(machine_actor)):
    """Import order lines (item quantities per sales order) from a sales order export.

    For every order the file lists, the file replaces that order's lines: a line of that order
    the file does not mention is removed (reported in warnings). Other orders are untouched.
    """
    factory_id = actor.authorize(payload.factory_id, *WRITE_ROLES)
    _require_csv(payload)
    orders = {o["order_id"] for o in db.get_all_orders() if o.get("factory_id") == factory_id}
    result = importers.parse_sales_order_lines(payload.csv_content, orders, _factory_item_codes(factory_id))
    in_file = sorted({oid for oid, _ in result.mentioned}) if result.header_ok else []
    stale = [l for l in db.get_order_lines(in_file) if (l["order_id"], l["item_code"]) not in result.mentioned]
    for row in list(result.rows):
        try:
            db.upsert_owned("order_lines", {**row, "factory_id": factory_id}, ("order_id", "item_code"))
        except db.OwnershipConflict:
            result.rows.remove(row)
            result.errors.append({"line": None, "error": f"order {row['order_id']} cannot be used by this factory"})
    for line in stale:
        db.delete_rows_where("order_lines", {"order_id": line["order_id"], "item_code": line["item_code"],
                                             "factory_id": factory_id})
        result.warnings.append(_snapshot_warning(
            f"order {line['order_id']} line for item {line['item_code']} is not in this file: removed "
            f"(the file replaces all lines of each order it lists)"))
    return _import_response(payload, result)


# ─── 6. Highway weather ──────────────────────────────────────────────────────

@app.post("/api/v1/ingest/live-highway-check", dependencies=[Depends(machine_read_access)])
def live_highway_check(req: LiveHighwayCheckRequest):
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

_EXECUTE_RUN_GONE = "Unknown or expired run_id; run the simulation again."


def _execute(req: ExecutePlanRequest, approved_by: str,
             run: Optional[Dict[str, Any]] = None) -> ExecutionReceiptResponse:
    """Execute a playbook. `approved_by` is the verified approver (never taken from a request body);
    `run` is the run already authorised by the caller (looked up here when not given)."""
    if run is None:
        run = run_store.get_run(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=_EXECUTE_RUN_GONE)
    factory_id = run.get("factory_id")
    if not factory_id:
        raise HTTPException(status_code=404, detail=_EXECUTE_RUN_GONE)   # fail closed: no tenant
    playbook = next((p for p in run["playbooks"] if p["id"] == req.playbook_id), None)
    if playbook is None:
        raise HTTPException(status_code=404, detail=f"Playbook {req.playbook_id} not in run {req.run_id}")

    # One execution per analysis: a sourced re-plan shares its parent's idempotency key.
    root_id = run.get("parent_run_id") or req.run_id

    def _same(existing: Dict[str, Any]) -> bool:
        return existing.get("run_id") == req.run_id and existing.get("playbook_id") == req.playbook_id

    def _already(existing: Dict[str, Any]) -> ExecutionReceiptResponse:
        if not _same(existing):
            raise HTTPException(
                status_code=409,
                detail=f"This analysis was already executed ({existing.get('run_id')} / {existing.get('playbook_id')}); "
                       f"run a new analysis to choose a different plan.",
            )
        return ExecutionReceiptResponse(**{**existing, "already_executed": True})

    existing = db.get_receipt(root_id)
    if existing:
        return _already(existing)
    if not playbook.get("feasible", True):
        raise HTTPException(status_code=409, detail="Playbook is infeasible (capacity exhausted); choose another.")

    payload = playbook.get("tally_po_payload") or {}
    po_number = payload.get("po_number") or f"PO-CZ-{uuid.uuid4().hex[:8].upper()}"
    order_id = run["order_id"]
    now = datetime.now(timezone.utc).isoformat()

    po_row = {
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
        "approved_by": approved_by,
        "run_id": req.run_id,
        "factory_id": factory_id,
        "created_at": now,
    }
    new_order_status = {
        "SLA_RENEGOTIATION": "EXTENSION_REQUESTED",
        "NO_ACTION": "RISK_ACCEPTED",
    }.get(playbook["strategy_type"], "RECOVERY_IN_PROGRESS")
    supplier_updates = [
        {"supplier_id": a["supplier_id"], "inbound_qty": a["units_allocated"]}
        for a in playbook["vendor_allocations"]
    ]
    overtime_line_ids = [lid for lid, hrs in (playbook.get("overtime_line_hours") or {}).items() if hrs > 0]
    # One PENDING delivery outcome per vendor allocation, promised at execution time + what the
    # vendor itself promised: the ETA it confirmed to the Sourcing Agent, else its own (unshifted)
    # lead time from the live factory model; never the run's risk-shifted planning lead.
    # Recorded deliveries later move the vendor's learned reliability (POST /api/v1/deliveries).
    outcome_factory = factory_id
    promised_lead = _promised_leads(root_id, outcome_factory)
    executed_at = datetime.fromisoformat(now)
    outcomes = [
        {
            "factory_id": outcome_factory, "supplier_id": a["supplier_id"], "po_number": po_number,
            "units": a["units_allocated"],
            "promised_at": (executed_at + timedelta(
                hours=promised_lead.get(a["supplier_id"], a["lead_time_hours"]))).isoformat(),
        }
        for a in playbook["vendor_allocations"] if a["units_allocated"] > 0
    ]
    agent_log = {
        "run_id": req.run_id, "factory_id": factory_id, "step_order": 10,
        "agent_name": "Human Approver", "agent_role": "HITL Execution", "badge_color": "emerald",
        "tool_called": "commit_purchase_order()",
        "tool_output_summary": f"PO {po_number} approved by {approved_by}; order #{order_id} → {new_order_status}.",
        "message": (
            f"✅ {playbook['id']} approved by {approved_by}. Draft Tally PO {po_number}, "
            f"shift notice ({playbook['overtime_hours']}h) and client notice generated. "
            f"Nothing has been sent to suppliers automatically."
        ),
        "created_at": now,
    }
    receipt = ExecutionReceiptResponse(
        success=True,
        run_id=req.run_id,
        po_number=po_number,
        playbook_id=playbook["id"],
        order_id=order_id,
        approved_by=approved_by,
        total_cost_inr=playbook["total_mitigation_cost_inr"],
        net_sla_saved_inr=playbook["net_sla_saved_inr"],
        confidence_pct=playbook["confidence_pct"],
        tally_xml_payload=payload.get("tally_xml", ""),
        tally_json_payload={
            "voucher_type": "Purchase Order",
            "po_number": po_number,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "company": getattr(run.get("factory_model"), "name", None) or factory_id,
            "total_cost_inr": playbook["total_mitigation_cost_inr"],
            "allocations": playbook["vendor_allocations"],
            "overtime_hours": playbook["overtime_hours"],
        },
        shift_broadcast_msg=playbook["shift_broadcast_msg"],
        client_sla_notice=playbook["client_sla_notice"],
        executed_at=now,
    )
    try:
        db.execute_plan_tx(
            po=po_row, order_id=order_id, order_status=new_order_status,
            supplier_updates=supplier_updates, overtime_line_ids=overtime_line_ids,
            agent_log=agent_log, root_run_id=root_id, receipt=receipt.model_dump(), outcomes=outcomes,
        )
    except db.AlreadyExecutedError:
        existing = db.get_receipt(root_id)
        if existing is None:
            raise HTTPException(status_code=409, detail="This analysis is already being executed; retry shortly.")
        return _already(existing)
    return receipt


def _promised_leads(root_id: str, factory_id: str) -> Dict[str, float]:
    """Hours each vendor promised: a confirmed ETA from the run's sourcing session wins over the
    vendor's live (unshifted) lead time. Vendors in neither fall back to the allocation's lead."""
    leads: Dict[str, float] = {}
    try:
        leads.update({v.supplier_id: v.lead_hours for v in load_factory_model(factory_id).vendors})
    except FactoryDataError as exc:
        logger.warning("Live factory model unavailable for delivery promises (%s); using the plan's leads", exc)
    session = sourcing.sourcing_store.load(root_id)
    if session is not None:
        for sid in session.confirmed:
            eta = session.overrides.get(sid, {}).get("confirmed_eta_hours")
            if eta is not None:
                leads[sid] = float(eta)
    return leads


@app.post("/api/v1/execute-plan")
def execute_plan(req: ExecutePlanRequest, actor: Actor = Depends(user_actor)):
    run = _authorized_run(actor, req.run_id, WRITE_ROLES, not_found=_EXECUTE_RUN_GONE)
    approved_by = actor.approver_name
    logger.info("Executing %s from run %s (approved_by=%s)", req.playbook_id, req.run_id, approved_by)
    return _execute(req, approved_by, run)


# ─── 7b. Delivery outcomes (vendor reliability is learned from these) ────────

@app.post("/api/v1/deliveries")
def record_delivery(req: DeliveryRecordRequest, actor: Actor = Depends(user_actor)):
    """Record that a purchase-order line was delivered. Moves the vendor's learned reliability."""
    unknown = f"No delivery outcome for PO {req.po_number} / supplier {req.supplier_id}"
    matches = [o for o in db.get_delivery_outcomes(supplier_id=req.supplier_id)
               if o["po_number"] == req.po_number]
    if not matches:
        raise HTTPException(status_code=404, detail=unknown)
    outcome = matches[0]
    factory_id = _authorize_resource(actor, outcome.get("factory_id"), WRITE_ROLES, unknown)
    if outcome["status"] == "DELIVERED":
        raise HTTPException(status_code=409, detail="This delivery was already recorded.")
    if reliability.in_the_future(req.delivered_at):
        raise HTTPException(
            status_code=422,
            detail=f"delivered_at is in the future (more than {reliability.MAX_FUTURE_HOURS}h after now).",
        )
    if reliability.implausibly_early(outcome["promised_at"], req.delivered_at):
        raise HTTPException(
            status_code=422,
            detail=f"delivered_at is more than {reliability.MAX_EARLY_DAYS} days before the promised time ({outcome['promised_at']}).",
        )
    updated = db.update_rows_where(
        "delivery_outcomes",
        {"po_number": req.po_number, "supplier_id": req.supplier_id, "status": "PENDING",
         "factory_id": factory_id},
        {"status": "DELIVERED", "delivered_at": reliability.parse_timestamp(req.delivered_at).isoformat(),
         "recorded_by": actor.approver_name},
    )
    if not updated:  # lost a race with another recording
        raise HTTPException(status_code=409, detail="This delivery was already recorded.")
    row = updated[0]
    try:
        vendor = next((v for v in load_factory_model(factory_id).vendors
                       if v.supplier_id == req.supplier_id), None)
    except FactoryDataError as exc:
        raise _factory_503(exc)
    return {
        "outcome": row,
        "on_time": reliability.on_time(row["promised_at"], row["delivered_at"]),
        "reliability_pct": vendor.reliability_pct if vendor else None,
    }


@app.get("/api/v1/deliveries")
def list_deliveries(status: Optional[str] = None, factory_id: Optional[str] = None,
                    actor: Actor = Depends(user_actor)):
    """The factory's delivery outcomes, by id order; filter with ?status=PENDING or DELIVERED."""
    fid = actor.authorize(factory_id, *ANY_ROLE)
    if status is not None and status not in ("PENDING", "DELIVERED"):
        raise HTTPException(status_code=422, detail="status must be PENDING or DELIVERED")
    return {"outcomes": db.get_delivery_outcomes(status=status, factory_id=fid)}


# ─── 8. Sourcing Agent (confirm vendor offers before approval) ───────────────

def _sourcing_call(fn, *args):
    try:
        return fn(*args)
    except sourcing.SourcingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except FactoryDataError as exc:
        raise _factory_503(exc)


_NO_SESSION = "No sourcing session for this run."


@app.post("/api/v1/sourcing/start")
def start_sourcing(req: SourcingStartRequest, actor: Actor = Depends(user_actor)):
    """Send enquiries to the vendors in a plan and start the confirm → re-plan loop."""
    _authorized_run(actor, req.run_id, WRITE_ROLES)
    return _sourcing_call(sourcing.start_sourcing, req.run_id, req.playbook_id)


@app.get("/api/v1/sourcing/{run_id}")
def get_sourcing(run_id: str, actor: Actor = Depends(user_actor)):
    """Current enquiries, offers and (when finished) the confirmed plan. Also expires timed-out enquiries."""
    _authorized_run(actor, run_id, ANY_ROLE, not_found=_NO_SESSION)
    return _sourcing_call(sourcing.view, run_id)


@app.post("/api/v1/sourcing/{run_id}/vendor-reply")
def post_vendor_reply(run_id: str, req: SourcingReplyRequest, actor: Actor = Depends(user_actor)):
    """Record a vendor's reply typed by an operator (phone call) or, in simulated mode, a simulated vendor."""
    _authorized_run(actor, run_id, WRITE_ROLES, not_found=_NO_SESSION)
    return _sourcing_call(sourcing.record_reply, run_id, req.supplier_id, req.text,
                          f"operator:{actor.approver_name}")


# ─── 8b. Client Agent (deadline extension; human sign-off before sending) ──

def _client_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except client_agent.ClientAgentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except sourcing.SourcingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except SolverInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FactoryDataError as exc:
        raise _factory_503(exc)


@app.post("/api/v1/client/draft")
def client_draft(req: ClientDraftRequest, actor: Actor = Depends(user_actor)):
    """Draft a deadline-extension request for the run's order. Nothing is sent."""
    _authorized_run(actor, req.run_id, WRITE_ROLES)
    return _client_call(client_agent.draft_extension, req.run_id, req.extension_hours, req.reason)


@app.post("/api/v1/client/approve")
def client_approve(req: ClientApproveRequest, actor: Actor = Depends(user_actor)):
    """The signed-in user approves the draft; only then is it sent (SOURCING_MODE channel)."""
    _authorized_run(actor, req.run_id, WRITE_ROLES)
    return _client_call(client_agent.approve_extension, req.run_id, actor.approver_name)


@app.post("/api/v1/client/answer")
def client_answer(req: ClientAnswerRequest, actor: Actor = Depends(user_actor)):
    """Record the client's answer: extends the deadline (accepted), re-plans and restarts sourcing."""
    _authorized_run(actor, req.run_id, WRITE_ROLES)
    return _client_call(client_agent.record_client_answer, req.run_id, req.accepted, req.text,
                        req.new_deadline_hours, f"operator:{actor.approver_name}")


@app.get("/api/v1/client/{run_id}")
def get_client(run_id: str, actor: Actor = Depends(user_actor)):
    """The run's extension request: draft, sent message, answer and re-plan."""
    _authorized_run(actor, run_id, ANY_ROLE)
    return _client_call(client_agent.view, run_id)


# ─── 9. Reset ────────────────────────────────────────────────────────────────

@app.post("/api/v1/reset")
def reset_factory(req: Optional[ResetRequest] = None, actor: Actor = Depends(user_actor)):
    """Reset ONE factory (the body's factory_id, default the caller's) to its demo seed. Needs
    the owner role in that factory; a factory without demo seed data is a 409."""
    factory_id = actor.authorize(req.factory_id if req else None, *OWNER_ONLY)
    if settings.is_production:
        raise HTTPException(status_code=403, detail="Reset is disabled in production")
    if factory_id != db.DEMO_FACTORY_ID:
        raise HTTPException(status_code=409, detail="no demo seed for this factory")
    return reset_to_seed(factory_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
