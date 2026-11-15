"""
CascadeZero — Official Meta WhatsApp Business Cloud API Client
Provides native WhatsApp messaging with interactive buttons, lists, and documents.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings

logger = logging.getLogger("cascadezero.meta_whatsapp")

GRAPH_API_VERSION = "v21.0"


def send_whatsapp_text(to_number: str, text: str) -> bool:
    """Sends a plain text WhatsApp message via Meta Cloud API."""
    if not settings.META_WA_ACCESS_TOKEN or not settings.META_WA_PHONE_NUMBER_ID:
        logger.warning("Meta WhatsApp credentials not set. Message logged only: %s", text[:80])
        return False

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{settings.META_WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.META_WA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number.replace("+", "").strip(),
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                logger.info("✅ Meta WhatsApp text delivered to %s", to_number)
                return True
            else:
                logger.error("❌ Meta WhatsApp error %s: %s", resp.status_code, resp.text)
                return False
    except Exception as exc:
        logger.error("❌ Meta WhatsApp HTTP Exception: %s", exc)
        return False


def send_whatsapp_interactive_buttons(
    to_number: str,
    body_text: str,
    buttons: List[Dict[str, str]],
    header_text: Optional[str] = None,
    footer_text: Optional[str] = "CascadeZero AI Crisis Control Tower",
) -> bool:
    """
    Sends a native interactive message with up to 3 clickable buttons.
    buttons format: [{"id": "APPROVE_PLAN_B", "title": "⚡ Approve Plan B"}, ...]
    """
    if not settings.META_WA_ACCESS_TOKEN or not settings.META_WA_PHONE_NUMBER_ID:
        logger.warning("Meta WhatsApp credentials missing. Fallback to mock.")
        return False

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{settings.META_WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.META_WA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    action_buttons = []
    for btn in buttons[:3]:  # WhatsApp allows max 3 buttons
        action_buttons.append({
            "type": "reply",
            "reply": {
                "id": btn["id"],
                "title": btn["title"][:20],  # Max 20 chars
            },
        })

    interactive_payload: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": action_buttons},
    }

    if header_text:
        interactive_payload["header"] = {"type": "text", "text": header_text[:60]}
    if footer_text:
        interactive_payload["footer"] = {"text": footer_text[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number.replace("+", "").strip(),
        "type": "interactive",
        "interactive": interactive_payload,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                logger.info("✅ Meta WhatsApp interactive buttons sent to %s", to_number)
                return True
            else:
                logger.error("❌ Meta WhatsApp buttons error %s: %s", resp.status_code, resp.text)
                return False
    except Exception as exc:
        logger.error("❌ Meta WhatsApp HTTP Exception: %s", exc)
        return False
