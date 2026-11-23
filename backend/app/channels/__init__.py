"""Channel adapters: WhatsApp (Meta Cloud API) and Telegram (Bot API)."""

from app.channels.base import Channel, InboundMessage
from app.channels.telegram import TelegramChannel
from app.channels.whatsapp import WhatsAppChannel

__all__ = ["Channel", "InboundMessage", "TelegramChannel", "WhatsAppChannel"]
