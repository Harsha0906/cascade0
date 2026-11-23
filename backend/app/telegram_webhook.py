"""Point the Telegram bot at the hosted backend (webhook mode).

Usage (from backend/, with TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET in the environment):
    python -m app.telegram_webhook set https://<your-backend>.onrender.com
    python -m app.telegram_webhook info
    python -m app.telegram_webhook delete      # go back to local polling (python -m app.telegram_poll)

Polling and a webhook are exclusive: use the webhook when hosted, polling when running locally.
"""

from __future__ import annotations

import sys

import httpx

from app.config import settings


def _call(method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    resp = httpx.post(url, json=payload or {}, timeout=20)
    return resp.json()


def main(argv: list[str]) -> int:
    if not settings.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not set.")
        return 1
    if not argv or argv[0] not in ("set", "info", "delete"):
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "set":
        if len(argv) < 2 or not argv[1].startswith("https://"):
            print("Give the backend's https URL, e.g. https://cascadezero-backend.onrender.com")
            return 1
        if not settings.TELEGRAM_WEBHOOK_SECRET:
            print("TELEGRAM_WEBHOOK_SECRET is not set (the webhook refuses requests without it).")
            return 1
        out = _call("setWebhook", {
            "url": argv[1].rstrip("/") + "/api/v1/telegram/webhook",
            "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
            "allowed_updates": ["message", "callback_query"],
        })
    elif cmd == "delete":
        out = _call("deleteWebhook")
    else:
        out = _call("getWebhookInfo")
        out.get("result", {}).pop("ip_address", None)
    print("ok" if out.get("ok") else "failed", out.get("result", out.get("description", "")))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
