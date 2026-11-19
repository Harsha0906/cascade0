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
    # Server-only key. Required once Row-Level Security is enabled (supabase/migrations/001_rls.sql).
    # Never expose this to the frontend.
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    # ── Google Gemini ─────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # ── Twilio WhatsApp (Optional) ────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_FROM: str = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    # ── Meta WhatsApp Business Cloud API (Official & Free Tier) ───────────
    META_WA_ACCESS_TOKEN: str = os.getenv("META_WA_ACCESS_TOKEN", "")
    META_WA_PHONE_NUMBER_ID: str = os.getenv("META_WA_PHONE_NUMBER_ID", "")
    META_WA_VERIFY_TOKEN: str = os.getenv("META_WA_VERIFY_TOKEN", "")
    META_APP_ID: str = os.getenv("META_APP_ID", "")  # not secret; used by the WhatsApp health check
    # App secret used to verify X-Hub-Signature-256 on incoming webhooks.
    META_APP_SECRET: str = os.getenv("META_APP_SECRET", "")
    # Comma-separated WhatsApp numbers (digits only, with country code) allowed to approve plans.
    WA_APPROVER_NUMBERS: list[str] = [
        n.strip().lstrip("+") for n in os.getenv("WA_APPROVER_NUMBERS", "").split(",") if n.strip()
    ]

    # ── Security ──────────────────────────────────────────────────────────
    # "production" makes the API key, webhook secret and explicit CORS origins mandatory.
    CASCADE_ENV: str = os.getenv("CASCADE_ENV", "development").lower()
    # Shared operator key required on mutating endpoints (sent as X-API-Key).
    CASCADE_API_KEY: str = os.getenv("CASCADE_API_KEY", "")
    ALLOWED_ORIGINS: list[str] = [
        o.strip() for o in os.getenv(
            "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",") if o.strip()
    ]

    # ── Sourcing Agent ────────────────────────────────────────────────────
    # "simulated": enquiries are recorded and vendor replies are entered on the dashboard.
    # "whatsapp":  enquiries go to suppliers.whatsapp_number via the Meta Cloud API.
    SOURCING_MODE: str = os.getenv("SOURCING_MODE", "simulated").lower()
    SOURCING_REPLY_TIMEOUT_MIN: int = int(os.getenv("SOURCING_REPLY_TIMEOUT_MIN", "30"))
    SOURCING_MAX_ROUNDS: int = int(os.getenv("SOURCING_MAX_ROUNDS", "3"))
    # Approved WhatsApp template for first-contact enquiries (outside the 24h window).
    # Body params: {{1}} vendor name, {{2}} units, {{3}} hours, {{4}} price, {{5}} reference.
    SOURCING_RFQ_TEMPLATE: str = os.getenv("SOURCING_RFQ_TEMPLATE", "")
    SOURCING_RFQ_TEMPLATE_LANG: str = os.getenv("SOURCING_RFQ_TEMPLATE_LANG", "en")

    # ── OpenWeatherMap (Optional) ─────────────────────────────────────────
    OPENWEATHER_API_KEY: str = os.getenv("OPENWEATHER_API_KEY", "")

    # ── Factory Constants (Apex Volt EV Battery Plant) ────────────────────
    DEFAULT_FACTORY_ID: str = os.getenv("FACTORY_ID", "apex-volt-blr2")
    DEFAULT_SLA_HOURS: int = 38
    MONTE_CARLO_ITERATIONS: int = 1000

    # ── Server ────────────────────────────────────────────────────────────
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    @property
    def is_production(self) -> bool:
        return self.CASCADE_ENV == "production"

    @property
    def supabase_server_key(self) -> str:
        """Prefer the service-role key (bypasses RLS server-side); fall back to anon for local dev."""
        return self.SUPABASE_SERVICE_ROLE_KEY or self.SUPABASE_ANON_KEY

    def security_problems(self) -> list[str]:
        """Configuration gaps that must be fixed before running in production."""
        problems = []
        if not self.CASCADE_API_KEY:
            problems.append("CASCADE_API_KEY is not set: mutating endpoints are unauthenticated")
        if not self.META_APP_SECRET:
            problems.append("META_APP_SECRET is not set: WhatsApp webhook signatures are not verified")
        if not self.META_WA_VERIFY_TOKEN:
            problems.append("META_WA_VERIFY_TOKEN is not set: Meta webhook verification handshake will fail")
        if "*" in self.ALLOWED_ORIGINS:
            problems.append("ALLOWED_ORIGINS contains '*'")
        if self.has_supabase and not self.SUPABASE_SERVICE_ROLE_KEY:
            problems.append("SUPABASE_SERVICE_ROLE_KEY is not set: backend writes use the anon key (incompatible with RLS)")
        return problems

    @property
    def has_supabase(self) -> bool:
        """Check if Supabase credentials are configured."""
        return bool(self.SUPABASE_URL and self.supabase_server_key)

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
