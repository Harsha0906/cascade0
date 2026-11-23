"""
Force the tests to run fully offline: no Supabase, no Gemini, no WhatsApp, no Telegram, no weather API.
Import this before anything from `app`. Empty env vars win over backend/.env because
python-dotenv never overrides variables that are already set.
"""

import os

OFFLINE = {
    "SUPABASE_URL": "",
    "SUPABASE_ANON_KEY": "",
    "SUPABASE_SERVICE_ROLE_KEY": "",
    "GEMINI_API_KEY": "",
    "META_WA_ACCESS_TOKEN": "",
    "META_WA_PHONE_NUMBER_ID": "",
    "TWILIO_ACCOUNT_SID": "",
    "TWILIO_AUTH_TOKEN": "",
    "OPENWEATHER_API_KEY": "",
    "CASCADE_ENV": "development",
    "CASCADE_API_KEY": "test-operator-key",
    "META_APP_SECRET": "test-app-secret",
    "META_WA_VERIFY_TOKEN": "test-verify-token",
    "WA_APPROVER_NUMBERS": "919800000000",
    # Telegram: never the real bot token from backend/.env; tests use fake transports.
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_WEBHOOK_SECRET": "",
    "META_APP_ID": "",
    "SOURCING_MODE": "simulated",
    "SOURCING_RFQ_TEMPLATE": "",
    # Dev auth (offline only): requests identify themselves with X-Dev-User; memberships come
    # from the mirror's factory_members seed.
    "AUTH_MODE": "dev",
    "CASCADE_API_KEY_FACTORY": "",
}
os.environ.update(OFFLINE)

DEV_OWNER = "dev-owner@example.test"      # owner of apex-volt-blr2
DEV_VIEWER = "dev-viewer@example.test"    # viewer of apex-volt-blr2
OTHER_OWNER = "other@example.test"        # owner of test-plant (seed_second_factory)
DEV_HEADERS = {"X-Dev-User": DEV_OWNER}


def dev_client(app, user: str = DEV_OWNER, **kwargs):
    """A TestClient that sends `X-Dev-User: <user>` on every request (dev auth mode)."""
    from fastapi.testclient import TestClient

    return TestClient(app, headers={"X-Dev-User": user}, **kwargs)
