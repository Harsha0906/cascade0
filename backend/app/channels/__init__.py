"""Channel adapters: Telegram (Bot API)."""

from app.channels.base import Channel, InboundMessage
from app.channels.telegram import TelegramChannel

__all__ = ["Channel", "InboundMessage", "TelegramChannel"]
