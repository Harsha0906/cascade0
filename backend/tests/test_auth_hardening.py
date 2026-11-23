"""Round B Task 1, review fixes: auth outages are 503, unsigned webhooks only offline, hardening."""

import base64
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_OWNER, dev_client
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from supabase_auth.errors import (
    AuthApiError,
    AuthInvalidJwtError,
    AuthRetryableError,
    AuthUnknownError,
)

from app import auth, db, main
from app.config import Settings

OWNER_ID = "00000000-0000-4000-8000-000000000001"


def _fake(get_user):
    return SimpleNamespace(auth=SimpleNamespace(get_user=get_user))


def _ok(token):
    return SimpleNamespace(user=SimpleNamespace(id=OWNER_ID, email=DEV_OWNER))


def _raiser(exc):
    def get_user(token):
        raise exc
    return get_user


def _jwt(payload: dict) -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64(payload)}.c2lnbmF0dXJl"


def _status(exc):
    with mock.patch.object(auth, "_auth_client", lambda: _fake(_raiser(exc))):
        try:
            auth.get_actor(authorization="Bearer tok", x_api_key=None, x_dev_user=None)
        except HTTPException as e:
            return e
    raise AssertionError("no HTTPException")


class AuthOutageTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        auth.clear_token_cache()

    def tearDown(self):
        auth.clear_token_cache()

    def test_auth_rejections_are_401(self):
        for exc in (AuthApiError("invalid JWT", 401, "bad_jwt"), AuthApiError("forbidden", 403, None),
                    AuthApiError("user not found", 404, "user_not_found"), AuthApiError("bad", 400, None),
                    AuthInvalidJwtError("malformed")):
            with self.subTest(exc=repr(exc)):
                self.assertEqual(_status(exc).status_code, 401)

    def test_outages_are_503_with_retry_after(self):
        req = httpx.Request("GET", "https://example.supabase.co/auth/v1/user")
        for exc in (httpx.ConnectError("refused", request=req), httpx.ReadTimeout("slow", request=req),
                    AuthRetryableError("gateway", 502), AuthApiError("boom", 500, None),
                    AuthApiError("rate limited", 429, "over_request_rate_limit"),
                    AuthUnknownError("odd", ValueError("x")), RuntimeError("library changed")):
            with self.subTest(exc=repr(exc)):
                e = _status(exc)
                self.assertEqual(e.status_code, 503)
                self.assertEqual(e.headers.get("Retry-After"), "5")
                self.assertNotIn("WWW-Authenticate", e.headers)

    def test_outage_over_http_is_503(self):
        req = httpx.Request("GET", "https://example.supabase.co/auth/v1/user")
        with mock.patch.object(auth, "_auth_client",
                               lambda: _fake(_raiser(httpx.ConnectError("refused", request=req)))):
            r = TestClient(main.app).get("/api/v1/state", headers={"Authorization": "Bearer tok"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.headers.get("retry-after"), "5")

    def test_failures_are_never_cached(self):
        calls = []

        def get_user(token):
            calls.append(token)
            if len(calls) == 1:
                raise AuthRetryableError("gateway", 502)
            if len(calls) == 2:
                raise AuthApiError("invalid", 401, None)
            return _ok(token)
        with mock.patch.object(auth, "_auth_client", lambda: _fake(get_user)):
            for expected in (503, 401):
                with self.assertRaises(HTTPException) as cm:
                    auth.get_actor(authorization="Bearer tok", x_api_key=None, x_dev_user=None)
                self.assertEqual(cm.exception.status_code, expected)
            self.assertEqual(auth.get_actor(authorization="Bearer tok", x_api_key=None, x_dev_user=None).email,
                             DEV_OWNER)
        self.assertEqual(len(calls), 3)


class TokenExpiryCacheTests(unittest.TestCase):
    def setUp(self):
        auth.clear_token_cache()

    def tearDown(self):
        auth.clear_token_cache()

    def _run(self, token, steps):
        auth.clear_token_cache()
        calls = []
        mono, wall = [1000.0], [1_800_000_000.0]
        fake = _fake(lambda t: calls.append(t) or _ok(t))
        with mock.patch.object(auth, "_auth_client", lambda: fake), \
                mock.patch.object(auth, "_clock", lambda: mono[0]), \
                mock.patch.object(auth, "_wall_clock", lambda: wall[0]):
            for advance in steps:
                mono[0] += advance
                wall[0] += advance
                auth.get_actor(authorization=f"Bearer {token}", x_api_key=None, x_dev_user=None)
        return len(calls)

    def test_entry_expires_at_token_exp_when_sooner(self):
        token = _jwt({"sub": OWNER_ID, "exp": 1_800_000_000 + 10})
        self.assertEqual(self._run(token, [0, 9]), 1)       # still within exp
        self.assertEqual(self._run(token, [0, 11]), 2)      # past exp (< 60 s): verified again

    def test_entry_capped_at_60s_when_exp_is_later(self):
        token = _jwt({"sub": OWNER_ID, "exp": 1_800_000_000 + 3600})
        self.assertEqual(self._run(token, [0, 59]), 1)
        self.assertEqual(self._run(token, [0, 61]), 2)

    def test_unreadable_payload_falls_back_to_60s(self):
        self.assertEqual(self._run("opaque-token", [0, 59]), 1)
        self.assertEqual(self._run("opaque-token", [0, 61]), 2)

    def test_already_expired_exp_is_not_cached(self):
        token = _jwt({"sub": OWNER_ID, "exp": 1_800_000_000 - 1})
        self.assertEqual(self._run(token, [0, 0]), 2)


class UnsignedWebhookTests(unittest.TestCase):
    """Unsigned Meta payloads and the Twilio sandbox work only with offline storage."""

    def setUp(self):
        db.reset_to_seed()
        self.anon = TestClient(main.app)
        self.sent = []
        self._p = [mock.patch.object(main, "send_whatsapp_text", lambda *a, **k: self.sent.append(a) or True)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        db.reset_to_seed()

    def _status_payload(self):
        return json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
            "messages": [{"from": "919800000000", "id": "wamid.unsigned-1", "type": "interactive",
                          "interactive": {"button_reply": {"id": "VIEW_STATUS"}}}]}}]}]}).encode()

    def test_unsigned_meta_accepted_offline_without_secret(self):
        with mock.patch.object(main.settings, "META_APP_SECRET", ""):
            r = self.anon.post("/api/v1/webhooks/whatsapp", content=self._status_payload(),
                               headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_unsigned_meta_refused_with_live_storage(self):
        with mock.patch.object(main.settings, "META_APP_SECRET", ""), \
                mock.patch.object(type(main.settings), "storage_mode", property(lambda s: "supabase")):
            r = self.anon.post("/api/v1/webhooks/whatsapp", content=self._status_payload(),
                               headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.sent, [])

    def test_twilio_sandbox_only_offline(self):
        with mock.patch.object(main, "_run_pipeline") as pipeline, \
                mock.patch.object(type(main.settings), "storage_mode", property(lambda s: "supabase")):
            r = self.anon.post("/api/v1/webhooks/whatsapp", data={"Body": "Flood, 48h delay", "From": "x"})
        self.assertEqual(r.status_code, 404)
        pipeline.assert_not_called()
        r = self.anon.post("/api/v1/webhooks/whatsapp", data={"Body": "hello", "From": "x"})
        self.assertEqual(r.status_code, 200)   # offline sandbox still works

    def test_startup_flags_unsigned_webhooks_with_live_storage(self):
        cfg = Settings()
        cfg.META_APP_SECRET = ""
        cfg.SUPABASE_URL, cfg.SUPABASE_SERVICE_ROLE_KEY, cfg.AUTH_MODE = "https://x.supabase.co", "k", "supabase"
        problems = cfg.security_problems()
        self.assertTrue(any("META_APP_SECRET" in p and "refused" in p for p in problems), problems)
        with self.assertLogs("cascadezero.server", level="WARNING") as logs:
            main._enforce_startup_security(cfg)
        self.assertTrue(any("META_APP_SECRET" in line for line in logs.output))


class DocsTests(unittest.TestCase):
    def test_docs_open_in_development(self):
        self.assertEqual(TestClient(main.app).get("/openapi.json").status_code, 200)

    def test_docs_disabled_in_production(self):
        cfg = Settings()
        cfg.CASCADE_ENV = "production"
        self.assertEqual(main._docs_kwargs(cfg), {"docs_url": None, "redoc_url": None, "openapi_url": None})
        self.assertEqual(main._docs_kwargs(Settings()), {})


class AdminKeyTests(unittest.TestCase):
    def test_admin_requires_service_role_key(self):
        from app import admin
        with mock.patch.object(admin.settings, "SUPABASE_URL", "https://x.supabase.co"), \
                mock.patch.object(admin.settings, "SUPABASE_ANON_KEY", "anon"), \
                mock.patch.object(admin.settings, "SUPABASE_SERVICE_ROLE_KEY", ""), \
                mock.patch.object(admin.db, "_get_supabase") as get_client:
            with self.assertRaises(admin.AdminError) as cm:
                admin._client()
        self.assertIn("SUPABASE_SERVICE_ROLE_KEY", str(cm.exception))
        get_client.assert_not_called()

    def test_admin_auth_errors_are_clean(self):
        from app import admin
        fake = SimpleNamespace(auth=SimpleNamespace(admin=SimpleNamespace(
            list_users=lambda **kw: _raiser(AuthApiError("User not allowed", 403, "not_admin"))(None))))
        with mock.patch.object(admin, "_client", lambda: fake), \
                mock.patch.object(admin.db, "get_factory_row", lambda f: {"id": f}):
            with mock.patch("sys.stderr") as err:
                code = admin.main(["add-member", "--email", "a@x.test", "--factory", "apex-volt-blr2",
                                   "--role", "owner"])
        self.assertEqual(code, 1)
        self.assertIn("User not allowed", "".join(str(c) for c in err.write.call_args_list))

    def test_add_member_checks_factory(self):
        from app import admin
        with mock.patch.object(admin.db, "get_factory_row", lambda f: None):
            with self.assertRaises(admin.AdminError) as cm:
                admin.add_member("a@x.test", "nope", "owner")
        self.assertIn("Unknown factory", str(cm.exception))


class DeliveryAttributionTests(unittest.TestCase):
    def test_delivery_records_actor(self):
        from datetime import datetime, timedelta, timezone
        db.reset_to_seed()
        client = dev_client(main.app)
        try:
            sim = client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}).json()
            r = client.post("/api/v1/execute-plan", json={"run_id": sim["run_id"],
                                                           "playbook_id": sim["recommended_plan_id"]})
            self.assertEqual(r.status_code, 200, r.text)
            o = db.get_delivery_outcomes(status="PENDING")[0]
            delivered = datetime.fromisoformat(o["promised_at"]) - timedelta(hours=1)
            delivered = min(delivered, datetime.now(timezone.utc))
            r = client.post("/api/v1/deliveries", json={
                "po_number": o["po_number"], "supplier_id": o["supplier_id"], "delivered_at": delivered.isoformat(),
                "recorded_by": "mallory"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["outcome"]["recorded_by"], DEV_OWNER)
            row = next(x for x in db.get_delivery_outcomes(status="DELIVERED") if x["po_number"] == o["po_number"])
            self.assertEqual(row["recorded_by"], DEV_OWNER)
        finally:
            db.reset_to_seed()

    def test_migration_adds_recorded_by_before_version_insert(self):
        import pathlib
        sql = (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "008_identity.sql").read_text()
        add = sql.index("ADD COLUMN IF NOT EXISTS recorded_by")
        marker = sql.index("APPEND their parts HERE")
        version = sql.index("INSERT INTO schema_migrations (version) VALUES (8)")
        self.assertLess(add, marker)
        self.assertLess(marker, version)
        self.assertEqual(sql.strip().splitlines()[-1], "INSERT INTO schema_migrations (version) VALUES (8) ON CONFLICT DO NOTHING;")


if __name__ == "__main__":
    unittest.main()
