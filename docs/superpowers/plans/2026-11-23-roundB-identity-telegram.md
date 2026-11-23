# Round B — Identity, Multi-Tenancy and the Telegram Channel

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver roadmap Phases 7 and 10 together:
- real logins;
- every user sees and acts only on their own factory's data (enforced by the backend and by Postgres RLS);
- approvers on chat channels map to user accounts;
- a free Telegram bot runs the full alert → plan → vendor confirmation → approval loop through a channel adapter shared with WhatsApp.

**Architecture:**
- **Login and API:** Supabase Auth (email + password) on the dashboard. The browser sends `Authorization: Bearer <access_token>`. The backend verifies the token with Supabase (`auth.get_user`, cached 60 s) and resolves an **Actor**: a user with factory memberships, or a machine key for automation endpoints.
- **Tenant scoping:** every endpoint is scoped to the actor's factory.
- **RLS (migration 008):** gives every table a `factory_id` and replaces the anon read policies with member-only policies.
- **Channels:** a `Channel` adapter interface (`send_text`, `send_buttons`, `parse_inbound`) with WhatsApp and Telegram implementations, and one shared `handle_inbound` flow.
- **Telegram transport:** a long-polling worker, so it is free locally with no tunnel, plus an optional webhook for hosting later. Users link their Telegram chat with a one-time code from the dashboard.

**Tech Stack:** FastAPI, supabase-py (auth admin + `get_user`), Supabase Auth + RLS, Next.js 14 + `@supabase/supabase-js`, Telegram Bot API over HTTPS (httpx), vitest.

**Spec:** `docs/superpowers/plans/2026-11-18-cascadezero-roadmap.md` — Phases 7 and 10; Principles; Definition of Done. The user approved the compressed rounds; Round B = Phases 7 and 10.

## Global Constraints

- **Done when:**
  - **Phase 7:**
    - Two users in two factories cannot see each other's data (tested with RLS, and in the backend).
    - The shared operator API key is no longer needed by the browser path.
  - **Phase 10:**
    - The full disruption → plan → vendor confirmation → approval loop works on Telegram, with the same tests as the WhatsApp path.
- **Security:**
  - Fail closed: a missing or invalid token → 401; a valid user without a membership in the requested factory → 404 (no existence leak).
  - `approved_by` always comes from the verified actor (user email, or `telegram:<user email>` / `whatsapp:<user email>`), never from the request body.
  - In production, `AUTH_MODE=dev` is refused at startup.
  - The Telegram webhook (when used) requires the `X-Telegram-Bot-Api-Secret-Token` header to match `TELEGRAM_WEBHOOK_SECRET`.
  - Secrets (`TELEGRAM_BOT_TOKEN`, keys) are read from env only. The user puts them in `backend/.env`; never log them, and never commit or read `backend/.env`.
- **Auth modes:**
  - `AUTH_MODE=supabase` is the default when Supabase is configured.
  - `AUTH_MODE=dev` is allowed only in offline storage mode. It accepts an `X-Dev-User: <email>` header and a dev membership table seeded in the mirror. Tests use it.
- **Machine endpoints** keep `X-API-Key`; the browser never sends it. These are `/api/v1/ingest/*` and `/api/v1/simulate-crisis` when called by automation. An actor from the API key carries `factory_id` = the factory named in `CASCADE_API_KEY_FACTORY` (env), defaulting to `DEFAULT_FACTORY_ID`.
- **Gate:**
  - backend `cd backend && PYTHONIOENCODING=utf-8 python -W ignore -m unittest discover -s tests -t .`
  - frontend `npm test` and `node_modules/.bin/tsc --noEmit -p .`
  - scenarios 1/2/3 → PLAN_B / PLAN_C / PLAN_B
- **Safety:** `backend/.env` points at the live Supabase/Gemini (and Telegram once the user adds a token). Every probe imports `tests._offline_env` first. Never call the live Telegram API from tests; use a fake transport.
- **Hygiene:** raw-string regexes; control-char/BOM scan `[]`; commits end `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Review policy:** one review per task scaled to risk (Tasks 1–3 and 5 are security-sensitive: full review), plus a final review and one fix wave.

## Review Focus

1. A token for user A requesting factory B's run, sourcing session, client record, receipt, scenario or import → 404, and nothing written. *(Task 2)*
2. A token that is expired, malformed or signed for another project → 401. The cache never serves a revoked token for more than 60 s. *(Task 1)*
3. A Telegram message from an unlinked chat, or from a linked user without the approver role, pressing Approve → refused with a reply, and no execution. *(Task 5)*
4. A Telegram update delivered twice (same `update_id`) → processed once. *(Task 5)*
5. RLS: the anon role reads nothing, and an authenticated member reads only their factory's rows, including `purchase_orders`, `agent_logs` and `analysis_runs`. *(Task 3, verified live by the controller)*

---

### Task 1: Auth core — actors, memberships, verified approver

**Files:**
- Create: `supabase/migrations/008_identity.sql` (first part)
- Create: `backend/app/auth.py`, `backend/app/admin.py` (CLI)
- Modify: `backend/app/config.py`, `backend/app/db.py`, `backend/app/main.py` (dependencies on every endpoint), `frontend/src/middleware.ts` (stop injecting `X-API-Key`)
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- **SQL:**
  - `factory_members(user_id UUID NOT NULL, factory_id TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('owner','approver','viewer')), email TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (user_id, factory_id))`
  - RLS: a member reads their own rows.
  - The guard requires version 7; version 8 is inserted at the end of the file, once Task 3 has appended its part.
- **`auth.py`:**
  - `@dataclass(frozen=True) Actor(kind: Literal["user","machine"], user_id: Optional[str], email: Optional[str], memberships: Mapping[str, str])`, mapping factory_id → role.
  - `def factory_for(self, requested: Optional[str] = None) -> str`:
    - With a requested factory: return it if the actor is a member, else raise 404.
    - Without one: the only membership, or `DEFAULT_FACTORY_ID` if the actor is a member of it, else 404.
  - `def require_role(self, factory_id, *roles) -> None` → 403 if the role is missing.
  - `get_actor(authorization: Optional[str] = Header(None), x_api_key: Optional[str] = Header(None), x_dev_user: Optional[str] = Header(None)) -> Actor` is the FastAPI dependency:
    - A Bearer token → Supabase `auth.get_user(token)` (cached 60 s by token hash) → load memberships from `factory_members`.
    - A valid `X-API-Key` → machine actor with `{CASCADE_API_KEY_FACTORY: "approver"}`.
    - `AUTH_MODE=dev` (offline only) with `X-Dev-User` → memberships from the mirror's `factory_members` seed.
    - Otherwise 401.
- **Mirror seed (dev/tests):**
  - `dev-owner@example.test` owns apex-volt-blr2;
  - `dev-viewer@example.test` is a viewer of apex-volt-blr2;
  - `other@example.test` owns test-plant (used by `seed_second_factory`).
- **`app/admin.py` CLI:** `python -m app.admin add-member --email E --factory F --role R` looks up the user via the Supabase admin API (`auth.admin.list_users` filtered by email) and upserts `factory_members`. It errors clearly if the user doesn't exist ("sign up on the dashboard first").
- **Endpoints:**
  - Every route depends on `get_actor`, except `/healthz`, the WhatsApp/Telegram webhooks (signature- or secret-checked), and `GET /` health.
  - Reads need any role; mutations need `owner` or `approver`; `/reset` needs `owner`.
  - `ExecutePlanRequest.approved_by` is removed; it is derived from the actor.
- **`middleware.ts`:** no longer adds `X-API-Key`. It passes `Authorization` through untouched.

- [ ] **Tests first:**
  - no credentials → 401;
  - a bad bearer (patched `get_user` raising) → 401;
  - a dev user owner → 200;
  - a viewer posting execute → 403;
  - API key → machine actor works on `/ingest/*`;
  - `approved_by` in a receipt equals the actor's email even if the body tries to set it;
  - production + `AUTH_MODE=dev` → startup refuses;
  - the token cache expires after 60 s (patched clock).
  - Existing tests are updated to send `X-Dev-User: dev-owner@example.test` (a test helper adds the header).
- [ ] Commit `feat: verified actors, factory memberships, approver from session`

### Task 2: Tenant scoping in the backend

**Files:** `backend/app/main.py`, `backend/app/db.py` (factory-filtered helpers), `backend/app/run_store.py`, `backend/app/agents/sourcing.py`, `backend/app/agents/client.py`, `backend/app/importers.py` call sites
**Test:** `backend/tests/test_tenancy.py`

**Interfaces:**
- **State:**
  - `get_full_state(factory_id)` filters every table by factory: suppliers, lines, orders, vendor_history (via the factory's supplier ids), disruption_events, agent_logs (via run ids of the factory's runs, or a new `agent_logs.factory_id` column — see Task 3; use the column), purchase_orders (`factory_id` column, Task 3).
  - `/api/v1/state`, `/factory`, `/scenarios`, `/runs/latest`, `/runs/{id}` all use `actor.factory_for(query factory_id?)`.
- **Runs and receipts:** `run_store.get_run(run_id)` returns the run; endpoints compare `run["factory_id"]` with the actor's memberships and return 404 on a mismatch. The same applies to sourcing sessions, client records, receipts and deliveries.
- **Writes:**
  - simulate-crisis, imports, reset and deliveries act on `actor.factory_for(body factory_id?)`.
  - The pipeline receives that factory id, so the second factory works end to end.
  - `/reset` resets only that factory's demo seed; for the demo factory that is current behaviour. A factory without seed data → 409 "no demo seed for this factory".

- [ ] **Tests first:** using `seed_second_factory()` and the dev users, each of the following for a foreign factory → 404 with no rows changed (Review Focus 1):
  - simulate on test-plant as dev-owner;
  - reading test-plant state;
  - reading a test-plant run;
  - starting sourcing;
  - drafting or answering for the client;
  - executing;
  - recording a delivery;
  - importing CSVs.

  `other@example.test` gets 200 on its own factory, and its `/state` contains only test-plant rows.
- [ ] Commit `feat: every endpoint scoped to the caller's factory`

### Task 3: RLS and factory_id everywhere (migration 008, second part)

**Files:** `supabase/migrations/008_identity.sql` (append), `supabase/schema.sql`, `backend/app/db.py` (write `factory_id` on inserts)
**Test:** `backend/tests/test_rls_sql.py` (static checks on the SQL text); live verification by the controller.

**Interfaces:**
- Add a `factory_id TEXT` column, backfilled to `apex-volt-blr2` where NULL, then `SET NOT NULL`, to: `purchase_orders`, `agent_logs`, `execution_receipts`, `sourcing_rfqs`, `sourcing_sessions`, `vendor_history`, `order_lines`, `webhook_events` (nullable: inbound before tenant resolution — keep it service-only).
- Python writes `factory_id` on every insert into these tables, including inside `execute_plan_tx` via `p_po`/`p_agent_log` payloads. The SQL function inserts `factory_id` from the payloads. Re-create the function in 008 with the same 9-arg signature, revoke and grant.
- **Policies:**
  - Drop every `*_read` policy granting `anon`.
  - For each tenant table, create `<t>_member_read`: `FOR SELECT TO authenticated USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = auth.uid()))`.
  - `factories`: members read their own rows by `id`.
  - Service-only tables keep no policies.
  - No INSERT/UPDATE/DELETE policies: all writes go through the backend with the service role.
- The guard requires version 7; insert version 8; `REQUIRED_MIGRATION_LEVEL = 8`.

- [ ] **Tests first:**
  - a static test parses 008 and asserts no `TO anon` remains for tenant tables;
  - every tenant table has a member policy;
  - offline: inserts carry `factory_id`; migration-level tests 7 → 8.
- [ ] Commit `feat: factory_id on every table; member-only RLS`

### Task 4: Dashboard login

**Files:**
- Create: `frontend/src/app/login/page.tsx`, `frontend/src/lib/session.ts`
- Modify: `frontend/src/store/useFactoryStore.ts` (all fetches via `apiFetch` with the bearer; 401 → redirect to `/login`), `frontend/src/lib/supabase.ts` (realtime with the session), `TopKpiBar.tsx` (user email + Sign out + "Link Telegram" button showing a one-time code from Task 6's endpoint), `app/mobile/page.tsx`
- Test: vitest for the pure helpers `authHeaders(session)` and `isAuthError(res)`

**Interfaces:**
- `apiFetch(path, init) -> Response` adds `Authorization: Bearer <access_token>` from the current Supabase session.
- `/login` signs in or signs up with email and password via `supabase.auth`, showing errors verbatim. After sign-up, the page says: "Ask the factory owner to add you (python -m app.admin add-member …)" when the user has no membership (the backend returns 404 on `/factory`).
- No component sends `X-API-Key`.

- [ ] vitest first; `npm test`, tsc 0
- [ ] Commit `feat: dashboard login; requests carry the user's session`

### Task 5: Channel adapters and the shared inbound flow (WhatsApp and Telegram)

**Files:**
- Create: `backend/app/channels/__init__.py`, `channels/base.py`, `channels/whatsapp.py`, `channels/telegram.py`, `backend/app/inbound.py`
- Modify: `backend/app/main.py` (the Meta webhook delegates to `inbound.handle`; new `POST /api/v1/telegram/webhook`), `backend/app/config.py` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`)
- Modify: migration 008 (append `user_channels`, `link_codes`)
- Test: `backend/tests/test_channels.py` (the existing WhatsApp webhook tests become channel-parametrised)

**Interfaces:**
- **`base.py`:**
  - `@dataclass(frozen=True) InboundMessage(channel: str, sender: str, text: str, button_id: Optional[str], message_id: str)`
  - `class Channel(Protocol): name: str; def send_text(self, to: str, text: str) -> bool; def send_buttons(self, to: str, text: str, buttons: Sequence[tuple[str, str]]) -> bool; def parse_inbound(self, payload: dict) -> list[InboundMessage]`
- **`telegram.py`:**
  - `TelegramChannel(token, transport=httpx)` uses `sendMessage` with `reply_markup.inline_keyboard` for buttons.
  - `parse_inbound` handles `message.text` and `callback_query.data` (it also answers the callback via `answerCallbackQuery`).
  - `message_id = f"tg:{update_id}"`; the sender is the chat id.
  - The transport is injectable, so tests use a fake.
- **`whatsapp.py`:** wraps the existing `meta_whatsapp` send and parse code. Behaviour is unchanged.
- **SQL:**
  - `user_channels(channel TEXT, address TEXT, user_id UUID NOT NULL, factory_id TEXT NOT NULL, PRIMARY KEY (channel, address))`
  - `link_codes(code TEXT PRIMARY KEY, user_id UUID, factory_id TEXT, expires_at TIMESTAMPTZ, used_at TIMESTAMPTZ)`
  - Both service-only.
- **`inbound.handle(channel: Channel, msg: InboundMessage) -> dict`** is the shared flow, moved from the Meta handler:
  - dedupe via `record_webhook_event(msg.message_id)`, releasing the event on failure;
  - `/link <code>` binds the chat to the user (the code is single-use and expires after 15 min);
  - `/start` or help;
  - "status";
  - a vendor reply when the sender matches an open RFQ's vendor address for that channel;
  - a disruption alert → run the pipeline for the sender's factory → plan summary with an Approve button;
  - the Approve button → `execute` with `approved_by=f"{channel}:{email}"`, only if the sender is linked and has the approver or owner role (Review Focus 3).
  - An unlinked sender gets a reply explaining `/link`. The WhatsApp allowlist (`WA_APPROVER_NUMBERS`) keeps working only as a fallback when `user_channels` has no WhatsApp rows (documented).
- **Endpoints:**
  - `POST /api/v1/telegram/webhook` checks the secret header → `inbound.handle`.
  - `POST /api/v1/channels/link-code` (user actor) returns `{code, expires_at}`.

- [ ] **Tests first:**
  - The existing WhatsApp webhook tests are parametrised over `[whatsapp, telegram]` with fake transports:
    - alert → plan with an Approve button;
    - Approve by a linked approver → executed once;
    - an unlinked user → refused;
    - a viewer → refused;
    - the duplicate `update_id` → processed once;
    - a failure releases the event.
  - `/link` with an expired or used code → refused.
  - The Telegram webhook with a wrong secret → 401.
- [ ] Commit `feat: channel adapters; Telegram inbound loop with linked approvers`

### Task 6: Telegram outbound for vendors and clients; polling worker

**Files:**
- Modify: `backend/app/agents/sourcing.py` (send through the channel: `SOURCING_MODE` ∈ {simulated, whatsapp, telegram}), `backend/app/agents/client.py` (client messages through the channel; orders gain an optional `client_contact` (channel:address) column in 008)
- Modify: `suppliers` gains `telegram_chat_id TEXT` (008)
- Modify: `backend/app/admin.py` (`set-vendor-contact --supplier S --channel telegram --address <chat_id>`, `set-client-contact --order O --channel telegram --address <chat_id>`)
- Create: `backend/app/telegram_poll.py` (`python -m app.telegram_poll`: a `getUpdates` long-poll loop with offset persistence in a small table or file, feeding `inbound.handle`; Ctrl-C safe)
- Test: `backend/tests/test_telegram_loop.py`

**Interfaces:**
- Vendor RFQs go out via `channel.send_text` to the vendor's address for the active mode. A vendor with no address on that channel → that RFQ is `SEND_FAILED` with a clear reason (existing behaviour).
- `find_open_rfq_by_number` is generalised to `find_open_rfq_by_address(channel, address)`.
- Client Agent approval sends via the order's `client_contact` channel. A missing contact → 409 "no client contact" (existing behaviour, now satisfiable).
- **`telegram_poll`:**
  - `poll_once(channel, offset) -> int` is testable with a fake transport.
  - The loop calls `deleteWebhook` once at start (polling and webhook are exclusive), then `getUpdates(timeout=30)`.

- [ ] **Done-when test** (fake Telegram transport, `SOURCING_MODE=telegram`):
  1. an approver's alert creates a plan;
  2. the bot replies with a summary and an Approve button;
  3. the operator starts sourcing, and RFQs go to the vendor chat ids;
  4. a vendor chat replies "YES 150 @600 in 4h" → confirmed;
  5. the approver presses Approve → executed once, `approved_by=telegram:<email>`;
  6. the receipt is sent back.

  The same flow is run with the WhatsApp fake to prove parity.
- [ ] Commit `feat: Telegram vendor/client messaging and polling worker`

### Task 7: Docs, live migration, gate, final review

- [ ] README:
  - login, roles and the admin CLI;
  - tenant isolation;
  - API key only for automation;
  - the Telegram setup (BotFather token in `backend/.env`, `python -m app.telegram_poll`, `/link` from the dashboard, setting vendor/client chat ids);
  - the channel adapter;
  - migration 008.
- [ ] Roadmap: Phases 7 and 10 marked done.
- [ ] Gate per Global Constraints.
- [ ] **Controller:**
  - apply 008 live; `/healthz` level 8;
  - live RLS check via SQL role-switching in a rolled-back transaction (anon sees 0 rows; a member sees only their factory);
  - once the user has signed up and been added as owner, a browser login check;
  - a Telegram smoke test once the user confirms the token is in `.env`.
- [ ] Final review (most capable model) and one fix wave.
