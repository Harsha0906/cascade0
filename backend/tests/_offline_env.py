"""
Force the tests to run fully offline: no Supabase, no Gemini, no WhatsApp, no weather API.
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
    "META_APP_ID": "",
    "SOURCING_MODE": "simulated",
    "SOURCING_RFQ_TEMPLATE": "",
}
os.environ.update(OFFLINE)
