"""Verified actors: Supabase bearer tokens, the machine API key, dev users, roles (Round B Task 1)."""

import unittest
from types import SimpleNamespace
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import DEV_OWNER, DEV_VIEWER, OTHER_OWNER, dev_client
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth, db, main
from app.config import Settings
from supabase_auth.errors import AuthApiError

KEY = {"X-API-Key": "test-operator-key"}
OWNER_ID = "00000000-0000-4000-8000-000000000001"


def _fake_supabase(get_user):
    return SimpleNamespace(auth=SimpleNamespace(get_user=get_user))


def _user_response(user_id, email):
    return SimpleNamespace(user=SimpleNamespace(id=user_id, email=email))


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()
        auth.clear_token_cache()
        self.anon = TestClient(main.app)
        self.owner = dev_client(main.app)
        self.viewer = dev_client(main.app, user=DEV_VIEWER)

    def tearDown(self):
        db.reset_to_seed()
        auth.clear_token_cache()

    def _simulate(self, client=None):
        r = (client or self.owner).post("/api/v1/simulate-crisis", json={"scenario_id": 1})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── 401: no or bad credentials ──
    def test_no_credentials_is_401(self):
        for method, path, body in [
            ("get", "/api/v1/state", None),
            ("get", "/api/v1/factory", None),
            ("get", "/api/v1/runs/latest", None),
            ("get", "/api/v1/scenarios", None),
            ("get", "/api/v1/deliveries", None),
            ("post", "/api/v1/simulate-crisis", {"scenario_id": 1}),
            ("post", "/api/v1/execute-plan", {"run_id": "x", "playbook_id": "PLAN_B"}),
            ("post", "/api/v1/reset", None),
            ("post", "/api/v1/ingest/live-highway-check", {}),
        ]:
            with self.subTest(path=path):
                r = getattr(self.anon, method)(path, **({"json": body} if body is not None else {}))
                self.assertEqual(r.status_code, 401, r.text)

    def test_open_routes_need_no_credentials(self):
        self.assertEqual(self.anon.get("/").status_code, 200)
        self.assertEqual(self.anon.get("/healthz").status_code, 200)

    def test_bad_bearer_is_401(self):
        def boom(token):
            raise AuthApiError("invalid JWT: signature mismatch", 401, "bad_jwt")
        with mock.patch.object(auth, "_auth_client", lambda: _fake_supabase(boom)):
            r = self.anon.get("/api/v1/state", headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual(r.status_code, 401)

    def test_bearer_without_user_is_401(self):
        with mock.patch.object(auth, "_auth_client", lambda: _fake_supabase(lambda t: SimpleNamespace(user=None))):
            r = self.anon.get("/api/v1/state", headers={"Authorization": "Bearer t"})
        self.assertEqual(r.status_code, 401)

    def test_bearer_without_supabase_is_401(self):
        # Offline storage: there is nothing to verify a token against, so it is refused.
        r = self.anon.get("/api/v1/state", headers={"Authorization": "Bearer t"})
        self.assertEqual(r.status_code, 401)

    def test_non_bearer_authorization_is_401(self):
        r = self.owner.get("/api/v1/state", headers={"Authorization": "Basic abc"})
        self.assertEqual(r.status_code, 401)

    def test_valid_bearer_loads_memberships(self):
        fake = _fake_supabase(lambda t: _user_response(OWNER_ID, DEV_OWNER))
        with mock.patch.object(auth, "_auth_client", lambda: fake):
            r = self.anon.get("/api/v1/state", headers={"Authorization": "Bearer good"})
            self.assertEqual(r.status_code, 200, r.text)
            actor = auth.get_actor(authorization="Bearer good", x_api_key=None, x_dev_user=None)
        self.assertEqual((actor.kind, actor.email, dict(actor.memberships)),
                         ("user", DEV_OWNER, {"apex-volt-blr2": "owner"}))

    def test_bearer_user_without_membership_gets_404(self):
        fake = _fake_supabase(lambda t: _user_response("99999999-0000-4000-8000-000000000000", "new@example.test"))
        with mock.patch.object(auth, "_auth_client", lambda: fake):
            r = self.anon.get("/api/v1/state", headers={"Authorization": "Bearer good"})
        self.assertEqual(r.status_code, 404)

    def test_wrong_api_key_is_401(self):
        r = self.anon.post("/api/v1/ingest/plc-telemetry", json={}, headers={"X-API-Key": "wrong"})
        self.assertEqual(r.status_code, 401)

    def test_unknown_dev_user_is_401(self):
        r = dev_client(main.app, user="nobody@example.test").get("/api/v1/state")
        self.assertEqual(r.status_code, 401)

    def test_dev_header_ignored_outside_dev_mode(self):
        with mock.patch.object(auth.settings, "AUTH_MODE", "supabase"):
            self.assertEqual(self.owner.get("/api/v1/state").status_code, 401)

    def test_dev_header_refused_with_live_storage(self):
        with mock.patch.object(type(auth.settings), "storage_mode", property(lambda s: "supabase")):
            with self.assertRaises(HTTPException) as cm:
                auth.get_actor(authorization=None, x_api_key=None, x_dev_user=DEV_OWNER)
        self.assertEqual(cm.exception.status_code, 401)

    # ── roles ──
    def test_dev_owner_reads_and_writes(self):
        self.assertEqual(self.owner.get("/api/v1/state").status_code, 200)
        self._simulate()

    def test_viewer_reads_but_cannot_mutate(self):
        self.assertEqual(self.viewer.get("/api/v1/state").status_code, 200)
        sim = self._simulate()
        r = self.viewer.post("/api/v1/execute-plan",
                             json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(db.get_receipt(sim["run_id"]))
        for path, body in [
            ("/api/v1/simulate-crisis", {"scenario_id": 1}),
            ("/api/v1/reset", None),
            ("/api/v1/ingest/plc-telemetry", {"line_id": "LINE-2", "speed_pct": 50, "temp_celsius": 70, "status": "DEGRADED"}),
            ("/api/v1/client/approve", {"run_id": sim["run_id"]}),
            ("/api/v1/sourcing/start", {"run_id": sim["run_id"]}),
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.viewer.post(path, json=body).status_code, 403)

    def test_reset_needs_owner(self):
        self.assertEqual(self.owner.post("/api/v1/reset").status_code, 200)
        self.assertEqual(self.anon.post("/api/v1/reset", headers=KEY).status_code, 403)  # machine: approver

    # ── machine actor ──
    def test_api_key_machine_actor_on_ingest(self):
        r = self.anon.post("/api/v1/ingest/plc-telemetry", headers=KEY,
                           json={"line_id": "LINE-2", "speed_pct": 55, "temp_celsius": 71.0, "status": "DEGRADED"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.anon.post("/api/v1/ingest/erp-csv", headers=KEY,
                           json={"filename": "a.csv", "csv_content": "order_id,required_qty,sla_penalty_inr\nEV-402,10,5"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.anon.post("/api/v1/simulate-crisis", json={"scenario_id": 1}, headers=KEY).status_code, 200)
        actor = auth.get_actor(authorization=None, x_api_key="test-operator-key", x_dev_user=None)
        self.assertEqual((actor.kind, actor.email, dict(actor.memberships)),
                         ("machine", None, {"apex-volt-blr2": "approver"}))

    def test_machine_actor_cannot_approve(self):
        sim = self._simulate()
        r = self.anon.post("/api/v1/execute-plan", headers=KEY,
                           json={"run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"]})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(db.get_receipt(sim["run_id"]))

    def test_api_key_disabled_when_unset(self):
        with mock.patch.object(auth.settings, "CASCADE_API_KEY", ""):
            r = self.anon.post("/api/v1/ingest/plc-telemetry", json={}, headers={"X-API-Key": ""})
            self.assertEqual(r.status_code, 401)

    # ── approved_by comes from the verified actor ──
    def test_approved_by_is_the_actor_email(self):
        sim = self._simulate()
        r = self.owner.post("/api/v1/execute-plan", json={
            "run_id": sim["run_id"], "playbook_id": sim["recommended_plan_id"], "approved_by": "mallory"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["approved_by"], DEV_OWNER)
        self.assertEqual(db.get_receipt(sim["run_id"])["approved_by"], DEV_OWNER)
        po = next(p for p in db.fetch_all("purchase_orders") if p["run_id"] == sim["run_id"])
        self.assertEqual(po["approved_by"], DEV_OWNER)

    def test_client_approval_is_the_actor_email(self):
        from app.agents import client as client_agent
        sim = self._simulate()
        r = self.owner.post("/api/v1/client/draft", json={"run_id": sim["run_id"], "extension_hours": 12})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.owner.post("/api/v1/client/approve", json={"run_id": sim["run_id"], "approved_by": "mallory"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(client_agent.view(sim["run_id"])["approved_by"], DEV_OWNER)

    # ── token cache ──
    def test_token_cache_expires_after_60s(self):
        calls = []
        fake = _fake_supabase(lambda t: calls.append(t) or _user_response(OWNER_ID, DEV_OWNER))
        clock = [1000.0]
        with mock.patch.object(auth, "_auth_client", lambda: fake), \
                mock.patch.object(auth, "_clock", lambda: clock[0]):
            for _ in range(3):
                auth.get_actor(authorization="Bearer tok", x_api_key=None, x_dev_user=None)
            self.assertEqual(len(calls), 1)
            clock[0] += 59
            auth.get_actor(authorization="Bearer tok", x_api_key=None, x_dev_user=None)
            self.assertEqual(len(calls), 1)
            clock[0] += 2   # 61 s after the first verification
            auth.get_actor(authorization="Bearer tok", x_api_key=None, x_dev_user=None)
            self.assertEqual(len(calls), 2)

    def test_failed_verification_is_not_cached(self):
        state = {"ok": False}

        def get_user(token):
            if not state["ok"]:
                raise AuthApiError("token is expired", 401, "bad_jwt")
            return _user_response(OWNER_ID, DEV_OWNER)
        with mock.patch.object(auth, "_auth_client", lambda: _fake_supabase(get_user)):
            with self.assertRaises(HTTPException):
                auth.get_actor(authorization="Bearer tok", x_api_key=None, x_dev_user=None)
            state["ok"] = True
            self.assertEqual(auth.get_actor(authorization="Bearer tok", x_api_key=None, x_dev_user=None).email,
                             DEV_OWNER)

    def test_cache_is_keyed_by_token_hash(self):
        fake = _fake_supabase(lambda t: _user_response(OWNER_ID, DEV_OWNER))
        with mock.patch.object(auth, "_auth_client", lambda: fake):
            auth.get_actor(authorization="Bearer secret-token-value", x_api_key=None, x_dev_user=None)
        self.assertNotIn("secret-token-value", repr(auth._token_cache))


class ActorTests(unittest.TestCase):
    def test_factory_for(self):
        one = auth.Actor("user", "u", "a@x", {"test-plant": "owner"})
        self.assertEqual(one.factory_for(), "test-plant")
        self.assertEqual(one.factory_for("test-plant"), "test-plant")
        with self.assertRaises(HTTPException) as cm:
            one.factory_for("apex-volt-blr2")
        self.assertEqual(cm.exception.status_code, 404)
        two = auth.Actor("user", "u", "a@x", {"test-plant": "owner", "apex-volt-blr2": "viewer"})
        self.assertEqual(two.factory_for(), "apex-volt-blr2")
        two_no_default = auth.Actor("user", "u", "a@x", {"test-plant": "owner", "f3": "viewer"})
        with self.assertRaises(HTTPException) as cm:
            two_no_default.factory_for()
        self.assertEqual(cm.exception.status_code, 409)
        with self.assertRaises(HTTPException) as cm:
            auth.Actor("user", "u", "a@x", {}).factory_for()
        self.assertEqual(cm.exception.status_code, 404)

    def test_require_role(self):
        a = auth.Actor("user", "u", "a@x", {"f": "viewer"})
        a.require_role("f", "viewer", "owner")
        with self.assertRaises(HTTPException) as cm:
            a.require_role("f", "owner", "approver")
        self.assertEqual(cm.exception.status_code, 403)
        with self.assertRaises(HTTPException) as cm:
            a.require_role("other", "viewer")
        self.assertEqual(cm.exception.status_code, 403)

    def test_dev_seed_memberships(self):
        db.reset_to_seed()
        self.assertEqual(db.get_dev_user(DEV_OWNER), (OWNER_ID, {"apex-volt-blr2": "owner"}))
        self.assertEqual(db.get_dev_user(DEV_VIEWER)[1], {"apex-volt-blr2": "viewer"})
        self.assertEqual(db.get_dev_user(OTHER_OWNER.upper())[1], {"test-plant": "owner"})
        self.assertIsNone(db.get_dev_user("nobody@example.test"))
        self.assertEqual(db.get_memberships(OWNER_ID), {"apex-volt-blr2": "owner"})


class StartupTests(unittest.TestCase):
    def _cfg(self, **attrs):
        cfg = Settings()
        for k, v in attrs.items():
            setattr(cfg, k, v)
        return cfg

    def test_production_with_dev_auth_refuses_to_start(self):
        cfg = self._cfg(CASCADE_ENV="production", AUTH_MODE="dev")
        with self.assertRaises(RuntimeError) as cm:
            main._enforce_startup_security(cfg)
        self.assertIn("AUTH_MODE=dev", str(cm.exception))

    def test_dev_auth_with_live_storage_refuses_to_start(self):
        cfg = self._cfg(AUTH_MODE="dev", SUPABASE_URL="https://x.supabase.co", SUPABASE_SERVICE_ROLE_KEY="k")
        with self.assertRaises(RuntimeError):
            main._enforce_startup_security(cfg)

    def test_unknown_auth_mode_refuses_to_start(self):
        with self.assertRaises(RuntimeError):
            main._enforce_startup_security(self._cfg(AUTH_MODE="none"))

    def test_dev_auth_offline_starts(self):
        main._enforce_startup_security(self._cfg(AUTH_MODE="dev"))


class AdminCliTests(unittest.TestCase):
    def test_add_member_requires_existing_user(self):
        from app import admin
        fake = SimpleNamespace(auth=SimpleNamespace(admin=SimpleNamespace(
            list_users=lambda **kw: [])))
        with mock.patch.object(admin, "_client", lambda: fake):
            with self.assertRaises(admin.AdminError) as cm:
                admin.add_member("ghost@example.test", "apex-volt-blr2", "owner")
        self.assertIn("sign up on the dashboard first", str(cm.exception))

    def test_add_member_upserts_membership(self):
        from app import admin
        users = [SimpleNamespace(id="u-1", email="Alice@Example.test")]
        fake = SimpleNamespace(auth=SimpleNamespace(admin=SimpleNamespace(
            list_users=lambda **kw: users if kw.get("page", 1) == 1 else [])))
        written = []
        with mock.patch.object(admin, "_client", lambda: fake), \
                mock.patch.object(admin.db, "upsert_row", lambda t, r, key_columns=None: written.append((t, r, key_columns)) or r):
            admin.add_member("alice@example.test", "apex-volt-blr2", "approver")
        self.assertEqual(written, [("factory_members",
                                    {"user_id": "u-1", "factory_id": "apex-volt-blr2", "role": "approver",
                                     "email": "alice@example.test"},
                                    ("user_id", "factory_id"))])

    def test_add_member_rejects_bad_role(self):
        from app import admin
        with self.assertRaises(admin.AdminError):
            admin.add_member("a@x", "apex-volt-blr2", "superuser")


if __name__ == "__main__":
    unittest.main()
