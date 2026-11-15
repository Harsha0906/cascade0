"""
CascadeZero — Environment Configuration Loader
Loads all environment variables with sensible defaults for resilient operation.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the backend/ directory (two levels up from app/config.py)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


class Settings:
    """Centralized configuration with automatic fallback defaults."""

    # ── Supabase ──────────────────────────────────────────────────────────
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

    # ── Google Gemini ─────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    # ── Twilio WhatsApp (Optional) ────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_FROM: str = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    # ── Meta WhatsApp Business Cloud API (Official & Free Tier) ───────────
    META_WA_ACCESS_TOKEN: str = os.getenv("META_WA_ACCESS_TOKEN", "")
    META_WA_PHONE_NUMBER_ID: str = os.getenv("META_WA_PHONE_NUMBER_ID", "")
    META_WA_VERIFY_TOKEN: str = os.getenv("META_WA_VERIFY_TOKEN", "cascadezero_verify_token_2026")

    # ── OpenWeatherMap (Optional) ─────────────────────────────────────────
    OPENWEATHER_API_KEY: str = os.getenv("OPENWEATHER_API_KEY", "")

    # ── Factory Constants (Apex Volt EV Battery Plant) ────────────────────
    FACTORY_NAME: str = "Apex Volt EV Battery Plant (Bengaluru Unit-2)"
    DEFAULT_SLA_HOURS: int = 38
    MONTE_CARLO_ITERATIONS: int = 1000

    # ── Server ────────────────────────────────────────────────────────────
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    @property
    def has_supabase(self) -> bool:
        """Check if Supabase credentials are configured."""
        return bool(self.SUPABASE_URL and self.SUPABASE_ANON_KEY)

    @property
    def has_gemini(self) -> bool:
        """Check if Gemini API key is configured."""
        return bool(self.GEMINI_API_KEY)

    @property
    def has_twilio(self) -> bool:
        """Check if Twilio credentials are configured."""
        return bool(self.TWILIO_ACCOUNT_SID and self.TWILIO_AUTH_TOKEN)

    @property
    def has_weather(self) -> bool:
        """Check if OpenWeatherMap API key is configured."""
        return bool(self.OPENWEATHER_API_KEY)


settings = Settings()
