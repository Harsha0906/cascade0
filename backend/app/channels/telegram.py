"""
CascadeZero — Telegram channel adapter (Bot API).

  sendMessage          {chat_id, text, reply_markup: {inline_keyboard: [[{text, callback_data}]]}}
  answerCallbackQuery  {callback_query_id}   (stops the client's button spinner)

Only private chats are served: in a group every member shares the chat id, so a linked group
would let anyone in it press Approve. A button press is accepted only from the chat's own user.
The bot token is part of the API URL, so URLs (and exceptions that may echo them) are never
logged. The HTTP transport is injectable (tests use a fake; nothing reaches Telegram).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence

import httpx

from app.channels.base import InboundMessage

logger = logging.getLogger("cascadezero.telegram")

API_BASE = "https://api.telegram.org"
CALLBACK_DATA_MAX_BYTES = 64     # Bot API limit for inline-button callback_data
TEXT_MAX_CHARS = 4096            # Bot API limit for a message


class TelegramChannel:
    name = "telegram"
    source_label = "TELEGRAM_BOT_API"

    def __init__(self, token: str, transport: Any = httpx) -> None:
        self._token = token or ""
        self._transport = transport

    def normalize_address(self, address: str) -> str:
        return str(address or "").strip()

    # ── outbound ──
    def _call(self, method: str, body: Dict[str, Any]) -> bool:
        if not self._token:
            logger.warning("TELEGRAM_BOT_TOKEN not set; %s not sent", method)
            return False
        try:
            resp = self._transport.post(f"{API_BASE}/bot{self._token}/{method}", json=body, timeout=10.0)
        except Exception as exc:
            # The exception text can contain the request URL (and so the token): log its type only.
            logger.error("Telegram %s failed: %s", method, type(exc).__name__)
            return False
        status = getattr(resp, "status_code", 0)
        if status == 200:
            return True
        description = ""
        try:
            description = str((resp.json() or {}).get("description", ""))[:200]
        except Exception:
            pass
        logger.error("Telegram %s error %s: %s", method, status, description)
        return False

    def send_text(self, to: str, text: str) -> bool:
        return self._call("sendMessage", {"chat_id": str(to), "text": text[:TEXT_MAX_CHARS]})

    def send_buttons(self, to: str, text: str, buttons: Sequence[tuple[str, str]]) -> bool:
        rows = []
        for button_id, title in buttons:
            if len(button_id.encode("utf-8")) > CALLBACK_DATA_MAX_BYTES:
                logger.error("Telegram button %r dropped: callback_data over %d bytes",
                             title, CALLBACK_DATA_MAX_BYTES)
                continue
            rows.append([{"text": title, "callback_data": button_id}])
        body: Dict[str, Any] = {"chat_id": str(to), "text": text[:TEXT_MAX_CHARS]}
        if rows:
            body["reply_markup"] = {"inline_keyboard": rows}
        return self._call("sendMessage", body)

    def answer_callback(self, callback_query_id: str) -> bool:
        return self._call("answerCallbackQuery", {"callback_query_id": callback_query_id})

    # ── inbound ──
    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        if not isinstance(payload, dict):
            return []
        update_id = payload.get("update_id")
        if update_id is None:
            return []
        message_id = f"tg:{update_id}"

        message = payload.get("message")
        if isinstance(message, dict):
            chat = message.get("chat") or {}
            if chat.get("type") != "private" or chat.get("id") is None:
                return []
            text = message.get("text")
            if not isinstance(text, str):
                return []
            return [InboundMessage(self.name, str(chat["id"]), text.strip(), None, message_id)]

        query = payload.get("callback_query")
        if isinstance(query, dict):
            if query.get("id"):
                self.answer_callback(str(query["id"]))
            chat = ((query.get("message") or {}).get("chat")) or {}
            from_id = (query.get("from") or {}).get("id")
            if chat.get("type") != "private" or chat.get("id") is None or from_id != chat.get("id"):
                return []
            data: Optional[str] = query.get("data")
            if not isinstance(data, str) or not data:
                return []
            return [InboundMessage(self.name, str(chat["id"]), "", data, message_id)]
        return []
