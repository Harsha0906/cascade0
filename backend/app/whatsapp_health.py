"""
WhatsApp integration health check (no secrets are ever returned or logged).

Checks: settings present, access token valid / not expiring, phone number reachable,
App ID + App Secret accepted, webhook subscribed to `messages`.

CLI:  python -m app.whatsapp_health
API:  GET /api/v1/whatsapp/health
"""

from __future__ import annotations

import io
import logging
import sys
import time
from typing import Any, Dict, List

import httpx

from app.config import settings
from app.meta_whatsapp import GRAPH_API_VERSION

# httpx logs full request URLs at INFO; some Graph calls below carry tokens in the query string.
logging.getLogger("httpx").setLevel(logging.WARNING)


def _graph_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
        return f"{err.get('type', 'Error')} {err.get('code', resp.status_code)}: {err.get('message', '')}"[:300]
    except ValueError:
        return f"HTTP {resp.status_code}"


def check_whatsapp_health() -> Dict[str, Any]:
    checks: List[Dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    cfg = {
        "META_WA_ACCESS_TOKEN": bool(settings.META_WA_ACCESS_TOKEN),
        "META_WA_PHONE_NUMBER_ID": bool(settings.META_WA_PHONE_NUMBER_ID),
        "META_APP_ID": bool(settings.META_APP_ID),
        "META_APP_SECRET": bool(settings.META_APP_SECRET),
        "META_WA_VERIFY_TOKEN": bool(settings.META_WA_VERIFY_TOKEN),
        "WA_APPROVER_NUMBERS": bool(settings.WA_APPROVER_NUMBERS),
    }
    missing = [k for k, ok in cfg.items() if not ok]
    add("config", "ok" if not missing else "fail",
        "All WhatsApp settings present." if not missing else "Missing in backend/.env: " + ", ".join(missing))
    add("sourcing_mode", "ok" if settings.SOURCING_MODE == "whatsapp" else "warn",
        f"SOURCING_MODE={settings.SOURCING_MODE}"
        + ("" if settings.SOURCING_MODE == "whatsapp" else " (vendor enquiries are not sent over WhatsApp)"))
    add("rfq_template", "ok" if settings.SOURCING_RFQ_TEMPLATE else "warn",
        f"Using template '{settings.SOURCING_RFQ_TEMPLATE}'." if settings.SOURCING_RFQ_TEMPLATE else
        "No SOURCING_RFQ_TEMPLATE: enquiries are free text and only reach vendors who messaged "
        "this number in the last 24h.")

    base = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
    try:
        with httpx.Client(timeout=10.0) as client:
            if settings.META_WA_ACCESS_TOKEN and settings.META_WA_PHONE_NUMBER_ID:
                r = client.get(
                    f"{base}/{settings.META_WA_PHONE_NUMBER_ID}",
                    params={"fields": "display_phone_number,verified_name,quality_rating"},
                    headers={"Authorization": f"Bearer {settings.META_WA_ACCESS_TOKEN}"},
                )
                if r.status_code == 200:
                    d = r.json()
                    add("phone_number", "ok", f"{d.get('display_phone_number')} ({d.get('verified_name')}), "
                                              f"quality {d.get('quality_rating', 'n/a')}")
                else:
                    add("phone_number", "fail", "Token or phone number ID rejected: " + _graph_error(r))

            if settings.META_WA_ACCESS_TOKEN and settings.META_APP_ID and settings.META_APP_SECRET:
                app_token = f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"
                r = client.get(f"{base}/debug_token",
                               params={"input_token": settings.META_WA_ACCESS_TOKEN, "access_token": app_token})
                if r.status_code == 200:
                    add("app_secret", "ok", "App ID + App Secret accepted by Meta.")
                    data = r.json().get("data", {})
                    if not data.get("is_valid"):
                        add("token", "fail", "Meta reports the access token is invalid or expired.")
                    else:
                        expires = data.get("expires_at", 0)
                        if not expires:
                            add("token", "ok", "Access token valid and does not expire (system-user token).")
                        else:
                            hours = (expires - time.time()) / 3600
                            add("token", "warn" if hours > 0 else "fail",
                                f"Access token expires in {hours:.1f}h; use a permanent System User token for demos."
                                if hours > 0 else "Access token has expired.")
                        scopes = set(data.get("scopes", []))
                        ok = "whatsapp_business_messaging" in scopes
                        add("token_scopes", "ok" if ok else "fail",
                            "Has whatsapp_business_messaging." if ok else "Token lacks whatsapp_business_messaging.")
                else:
                    add("app_secret", "fail", "App ID / App Secret rejected: " + _graph_error(r))

                r = client.get(f"{base}/{settings.META_APP_ID}/subscriptions", params={"access_token": app_token})
                if r.status_code == 200:
                    wa = next((s for s in r.json().get("data", []) if s.get("object") == "whatsapp_business_account"), None)
                    fields = {f.get("name") for f in (wa or {}).get("fields", [])}
                    if wa and wa.get("active") and "messages" in fields:
                        add("webhook", "ok", f"Webhook active: {wa.get('callback_url')} (messages subscribed)")
                    elif wa:
                        add("webhook", "fail", f"Webhook {wa.get('callback_url')} inactive or not subscribed to 'messages'.")
                    else:
                        add("webhook", "fail", "No WhatsApp webhook configured for this app.")
                else:
                    add("webhook", "warn", "Could not read webhook subscriptions: " + _graph_error(r))
    except httpx.HTTPError as exc:
        add("network", "fail", f"Could not reach graph.facebook.com: {type(exc).__name__}")

    return {"ready": all(c["status"] != "fail" for c in checks), "checks": checks}


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    result = check_whatsapp_health()
    icons = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
    for c in result["checks"]:
        print(f"[{icons[c['status']]}] {c['check']:<14} {c['detail']}")
    print("\nREADY" if result["ready"] else "\nNOT READY: fix the FAIL items above")
    sys.exit(0 if result["ready"] else 1)
