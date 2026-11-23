"""
CascadeZero — WhatsApp channel adapter (Meta WhatsApp Business Cloud API).

Wraps the existing send helpers in app/meta_whatsapp.py; behaviour is unchanged. The send
functions are injectable so tests use fakes (and app/main.py binds them late, so patches on
`main.send_whatsapp_text` keep working).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.channels.base import InboundMessage

logger = logging.getLogger("cascadezero.server")

DEFAULT_HEADER = "Disruption detected"
DEFAULT_FOOTER = "Approval requires a linked approver"


def _default_send_text(to: str, text: str) -> bool:
    from app.meta_whatsapp import send_whatsapp_text
    return send_whatsapp_text(to, text)


def _default_send_buttons(to: str, text: str, buttons: List[Dict[str, str]],
                          header: Optional[str] = None, footer: Optional[str] = None) -> bool:
    from app.meta_whatsapp import send_whatsapp_interactive_buttons
    return send_whatsapp_interactive_buttons(to, text, buttons, header, footer)


def normalize_number(number: str) -> str:
    """WhatsApp addresses are stored and compared as digits only (country code, no '+')."""
    return "".join(ch for ch in str(number or "") if ch.isdigit())


class WhatsAppChannel:
    name = "whatsapp"
    source_label = "META_WHATSAPP_CLOUD_API"

    def __init__(self, send_text: Optional[Callable[..., bool]] = None,
                 send_buttons: Optional[Callable[..., bool]] = None) -> None:
        self._send_text = send_text or _default_send_text
        self._send_buttons = send_buttons or _default_send_buttons

    def normalize_address(self, address: str) -> str:
        return normalize_number(address)

    def send_text(self, to: str, text: str) -> bool:
        return self._send_text(to, text)

    def send_buttons(self, to: str, text: str, buttons: Sequence[tuple[str, str]]) -> bool:
        return self._send_buttons(
            to, text, [{"id": bid, "title": title} for bid, title in buttons], DEFAULT_HEADER, DEFAULT_FOOTER,
        )

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        """The first message of a Meta `whatsapp_business_account` payload (Meta sends one per
        delivery). Delivery/read receipts carry no message: they are logged (failures as errors,
        so undelivered replies are visible) and yield nothing."""
        try:
            value: Dict[str, Any] = payload["entry"][0]["changes"][0]["value"]
        except (KeyError, IndexError, TypeError):
            return []
        messages = value.get("messages") or []
        if not messages:
            _log_statuses(value.get("statuses") or [])
            return []
        msg = messages[0]
        button_id: Optional[str] = None
        text = ""
        if msg.get("type") == "interactive":
            button_id = (msg.get("interactive") or {}).get("button_reply", {}).get("id", "") or ""
        else:
            text = ((msg.get("text") or {}).get("body") or "").strip()
        return [InboundMessage(self.name, str(msg.get("from", "")), text, button_id, str(msg.get("id") or ""))]


def _log_statuses(statuses: list) -> None:
    for st in statuses:
        errors = st.get("errors") or []
        if st.get("status") == "failed" or errors:
            for e in errors or [{}]:
                logger.error("WhatsApp delivery FAILED to %s: code %s %s — %s",
                             st.get("recipient_id"), e.get("code"), e.get("title"),
                             (e.get("error_data") or {}).get("details", e.get("message", "")))
        else:
            logger.info("WhatsApp message %s to %s", st.get("status"), st.get("recipient_id"))
