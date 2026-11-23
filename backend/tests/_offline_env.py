"""
Force the tests to run fully offline: no Supabase, no Gemini, no Telegram, no weather API.
Import this before anything from `app`. Empty env vars win over backend/.env because
python-dotenv never overrides variables that are already set.
"""

import os

OFFLINE = {
    "SUPABASE_URL": "",
    "SUPABASE_ANON_KEY": "",
    "SUPABASE_SERVICE_ROLE_KEY": "",
    "GEMINI_API_KEY": "",
    "OPENWEATHER_API_KEY": "",
    "CASCADE_ENV": "development",
    "CASCADE_API_KEY": "test-operator-key",
    # Telegram: never the real bot token from backend/.env; tests use fake transports.
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_WEBHOOK_SECRET": "",
    "SOURCING_MODE": "simulated",
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
