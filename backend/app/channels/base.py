"""
CascadeZero — the channel adapter interface.

A channel turns a platform's webhook payload into `InboundMessage`s and sends text and button
replies. The shared inbound flow (app/inbound.py) only ever talks to this interface, so WhatsApp
and Telegram behave identically: same commands, same authorisation, same de-duplication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class InboundMessage:
    channel: str              # "whatsapp" | "telegram"
    sender: str               # the address replies go to (WhatsApp number digits / Telegram chat id)
    text: str                 # message text, stripped ("" for a button press)
    button_id: Optional[str]  # the pressed button's id (WhatsApp button_reply.id / callback_data)
    message_id: str           # platform id used for de-duplication ("" when the platform sent none)


@runtime_checkable
class Channel(Protocol):
    name: str

    def send_text(self, to: str, text: str) -> bool: ...

    def send_buttons(self, to: str, text: str, buttons: Sequence[tuple[str, str]]) -> bool:
        """`buttons` is a sequence of (button_id, title)."""
        ...

    def parse_inbound(self, payload: dict) -> list[InboundMessage]: ...
