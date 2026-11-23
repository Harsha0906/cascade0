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
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

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

    # ── Telegram Bot API ──────────────────────────────────────────────────
    # Bot token (BotFather). Secret: env only, never logged. Unset: nothing is sent to Telegram.
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    # Shared secret Telegram echoes in X-Telegram-Bot-Api-Secret-Token (setWebhook secret_token).
    # Unset: the Telegram webhook refuses every update (fail closed).
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    # `python -m app.telegram_poll` remembers the next getUpdates offset here (a local file).
    TELEGRAM_POLL_OFFSET_FILE: str = os.getenv(
        "TELEGRAM_POLL_OFFSET_FILE",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".telegram_poll_offset"))

    # ── Security ──────────────────────────────────────────────────────────
    # "production" makes the API key, webhook secret and explicit CORS origins mandatory.
    CASCADE_ENV: str = os.getenv("CASCADE_ENV", "development").lower()
    # Machine key (X-API-Key) for automation on /api/v1/ingest/* and /api/v1/simulate-crisis.
    # The browser never sends it. Unset: no machine access at all (fail closed).
    CASCADE_API_KEY: str = os.getenv("CASCADE_API_KEY", "")
    # The factory a machine actor acts on (as an approver); defaults to DEFAULT_FACTORY_ID.
    CASCADE_API_KEY_FACTORY: str = os.getenv("CASCADE_API_KEY_FACTORY", "")
    # "supabase" (default): users authenticate with a Supabase access token (Authorization: Bearer).
    # "dev": offline storage only, never in production; X-Dev-User: <email> picks a seeded dev user.
    AUTH_MODE: str = os.getenv("AUTH_MODE", "").strip().lower() or "supabase"
    ALLOWED_ORIGINS: list[str] = [
        o.strip() for o in os.getenv(
            "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",") if o.strip()
    ]

    # ── Sourcing Agent ────────────────────────────────────────────────────
    # "simulated": enquiries are recorded and vendor replies are entered on the dashboard.
    # "whatsapp":  enquiries go to suppliers.whatsapp_number via the Meta Cloud API.
    # "telegram":  enquiries go to suppliers.telegram_chat_id via the Telegram Bot API.
    SOURCING_MODE: str = os.getenv("SOURCING_MODE", "simulated").lower()
    SOURCING_REPLY_TIMEOUT_MIN: int = int(os.getenv("SOURCING_REPLY_TIMEOUT_MIN", "30"))
    SOURCING_MAX_ROUNDS: int = int(os.getenv("SOURCING_MAX_ROUNDS", "3"))
    # Approved WhatsApp template for first-contact enquiries (outside the 24h window).
    # Body params: {{1}} vendor name, {{2}} units, {{3}} hours, {{4}} price, {{5}} reference.
    SOURCING_RFQ_TEMPLATE: str = os.getenv("SOURCING_RFQ_TEMPLATE", "")
    SOURCING_RFQ_TEMPLATE_LANG: str = os.getenv("SOURCING_RFQ_TEMPLATE_LANG", "en")

    # ── OpenWeatherMap (Optional) ─────────────────────────────────────────
    OPENWEATHER_API_KEY: str = os.getenv("OPENWEATHER_API_KEY", "")

    # ── Factory Constants ─────────────────────────────────────────────────
    DEFAULT_FACTORY_ID: str = os.getenv("FACTORY_ID", "apex-volt-blr2")
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

    @property
    def api_key_factory(self) -> str:
        return self.CASCADE_API_KEY_FACTORY or self.DEFAULT_FACTORY_ID

    def auth_problems(self) -> list[str]:
        """Authentication misconfigurations that refuse startup in every environment (fail closed)."""
        problems = []
        if self.AUTH_MODE not in ("supabase", "dev"):
            problems.append(f"AUTH_MODE={self.AUTH_MODE!r} is not one of 'supabase', 'dev'")
        if self.AUTH_MODE == "dev":
            if self.is_production:
                problems.append("AUTH_MODE=dev is not allowed in production")
            if self.storage_mode != "offline":
                problems.append("AUTH_MODE=dev is allowed only in offline storage mode (Supabase is configured)")
        return problems

    def security_problems(self) -> list[str]:
        """Configuration gaps that must be fixed before running in production."""
        problems = []
        if not self.META_APP_SECRET:
            if self.storage_mode == "offline":
                problems.append("META_APP_SECRET is not set: unsigned WhatsApp webhooks are accepted "
                                "(offline storage only)")
            else:
                problems.append("META_APP_SECRET is not set: WhatsApp webhooks are refused (unsigned "
                                "payloads are refused with live storage)")
        if not self.META_WA_VERIFY_TOKEN:
            problems.append("META_WA_VERIFY_TOKEN is not set: Meta webhook verification handshake will fail")
        if "*" in self.ALLOWED_ORIGINS:
            problems.append("ALLOWED_ORIGINS contains '*'")
        if self.has_supabase and not self.SUPABASE_SERVICE_ROLE_KEY:
            problems.append("SUPABASE_SERVICE_ROLE_KEY is not set: backend writes use the anon key (incompatible with RLS)")
        if self.is_production and self.storage_mode == "offline":
            problems.append("offline storage in production: Supabase is not configured, so state would be lost on restart")
        return problems

    @property
    def storage_mode(self) -> str:
        """'supabase' when credentials are configured, otherwise 'offline' (in-memory mirror)."""
        return "supabase" if self.has_supabase else "offline"

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
