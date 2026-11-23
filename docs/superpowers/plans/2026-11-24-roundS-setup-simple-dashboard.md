# Round S — Factory Setup and a Simple Dashboard

**Goal:** A real factory owner can set up their factory entirely in the browser — factory, lines, suppliers, stock, orders, team — and use a simple guided dashboard. Pages exist for factory and lines, suppliers, shipments and stock, orders, and team. Advanced views (Twin, agent logs) move behind an "Advanced" tab.

**Spec:** user requests in conversation (2026-11-24), plus roadmap principles (numbers from data; fail loudly; every UI claim true).

**Constraints:**
- **Tenancy (from Round B):** every endpoint uses `get_actor` and authorises against the resource's factory. Reads need any role; edits need owner or approver; team management needs owner. Cross-factory access → 404.
- **No silent defaults.** Supplier risk parameters come from an explicit risk profile chosen by the user, shown and editable:

  | Profile | lead σ | shock % | shock range (h) | unreliable delay (h) |
  |---|---|---|---|---|
  | `low` | 0.3 | 2 | 1–2 | 1–2 |
  | `medium` | 1.0 | 6 | 1–3 | 2–4 |
  | `high` | 2.0 | 15 | 2–6 | 3–8 |

  `min_lead_hours` = the supplier's stated minimum, else = lead hours. Reliability prior = the stated "past orders / on-time" counts, else 0/0 (uninformative, shown as "no history yet").
- No new migrations unless unavoidable. Writes use existing tables (`factories`, `production_lines`, `suppliers`, `vendor_history`, `orders`, `order_lines`, `factory_members`). Any new column goes in `supabase/migrations/009_setup.sql`, re-run safe, with RLS consistent with 008: a member-read policy, writes revoked from anon/authenticated, a level-8 guard, version 9, and `REQUIRED_MIGRATION_LEVEL = 9`.
- **Gate:**
  - backend `cd backend && PYTHONIOENCODING=utf-8 python -W ignore -m unittest discover -s tests -t .`
  - frontend `npm test` and `node_modules/.bin/tsc --noEmit -p .`
  - scenarios 1/2/3 → PLAN_B / PLAN_C / PLAN_B
- **Safety:** `backend/.env` points at live services; probes import `tests._offline_env` first; never read `.env`.
- **Review:** the user asked for speed and low cost — one final review only. Commits end `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: Backend setup and data APIs

**Files:** `backend/app/setup_api.py` (FastAPI router included by `main.py`), `backend/app/db.py` helpers, `backend/app/importers.py` (supplier and line CSV parsers), tests `backend/tests/test_setup_api.py`

**Endpoints:**
- **Factory**
  - `POST /api/v1/factories` — any signed-in user (no membership needed). Body `{id?, name, stock_item_code, stock_item_name, qa_dispatch_hours, safety_stock_units, production_hours_in_window}`. The id is a slug from the name if absent; must be unique, else 409. The caller becomes owner (a `factory_members` row). Also creates the `items` row for the stock item and a `stock_levels` row with 0.
  - `GET|PATCH /api/v1/factory/settings`
- **Lines:** `GET|POST /api/v1/lines`, `PATCH|DELETE /api/v1/lines/{line_id}`. Fields: `name`, `rated_units_per_hour`, `ot_units_per_hour`, `ot_cost_per_hour`, `max_ot_hours`. DELETE is refused (409) if referenced by an active run.
- **Suppliers:** `GET|POST /api/v1/suppliers`, `PATCH|DELETE /api/v1/suppliers/{id}`.
  - Fields: `name`, `sourcing_role` (PRIMARY / BACKUP / EXPEDITE), `unit_cost`, `flat_cost`, `max_units`, `lead_hours`, `min_lead_hours?`, `route`, `risk_profile` (low / medium / high), `past_orders?`, `on_time?`, `telegram_chat_id?`.
  - The response includes the derived parameters and the learned reliability.
- **Orders:** `GET|POST /api/v1/orders`, `PATCH /api/v1/orders/{order_id}`. Fields: `client`, `required_qty`, `due_at` (ISO) or `hours_remaining`, `sla_penalty_inr`, `partial_delay_penalty_inr`, `priority`, plus an order line for the planning item = `required_qty`.
- **Read-only lists:** `GET /api/v1/stock` (items, stock levels, open shipments with ETA hours) and `GET /api/v1/shipments`.
- **Telegram contact invites (deep links):**
  - **Problem:** Telegram bots cannot message a phone number, and the person must press Start once.
  - **Endpoints:** `POST /api/v1/suppliers/{id}/telegram-invite` and `POST /api/v1/orders/{order_id}/telegram-invite` (owner/approver). Each returns `{link: "https://t.me/<bot_username>?start=<token>", expires_at}`. `bot_username` comes from env `TELEGRAM_BOT_USERNAME`; if unset → 409 with a clear message.
  - **Token:** URL-safe random of about 24 chars; only a SHA-256 hash is stored; single-use; 7-day expiry. Stored in a new table `contact_invites(token_hash PK, factory_id, kind 'supplier'|'client', target_id, expires_at, used_at)` (migration 009: service-only, RLS on, no policy, REVOKE ALL from anon/authenticated).
  - **Inbound:** the Telegram flow handles `/start <token>`:
    - **Valid:** set `suppliers.telegram_chat_id` (kind supplier) or `orders.client_contact = telegram:<chat_id>` (kind client), scoped to the invite's factory, and reply "You're connected to <factory name> as <supplier name / client of order X>."
    - **Invalid, used or expired:** a polite refusal.
  - **Then:** sourcing in `SOURCING_MODE=telegram` and the Client Agent reach them automatically.
  - **Tests:** a full invite → start → RFQ delivered to that chat flow, plus expired, reused and cross-factory tokens.
- **CSV import:** `POST /api/v1/ingest/suppliers-csv` and `POST /api/v1/ingest/lines-csv` — row-level errors, like the existing importers.
- **Team (owner only):**
  - `GET /api/v1/team` lists members (email, role) and linked chats.
  - `POST /api/v1/team` `{email, role}` adds an existing signed-up user (Supabase admin lookup) or → 404 "ask them to sign up first".
  - `PATCH`/`DELETE /api/v1/team/{user_id}`. An owner can't remove the last owner (409).
- Validation: every number ≥ 0 with sensible bounds; missing required → 422 naming the field. After writes, `load_factory_model(factory_id)` must still load, else the write is rejected with 422 naming the problem.

- [ ] **Tests first:**
  - create factory → owner → add 2 lines and 3 suppliers via API → `load_factory_model` loads with the profile-derived parameters;
  - a pipeline run on the new factory with a free-text alert works end to end;
  - a viewer can't edit (403); another factory → 404;
  - CSV supplier import with a bad row → row error;
  - the last-owner guard.
- [ ] Commit `feat: factory setup and data APIs`

### Task 2: Frontend — navigation, setup wizard, data pages

**Files:**
- `frontend/src/components/AppNav.tsx` (top-level tabs: Home · Factory · Suppliers · Shipments & Stock · Orders · Team · Advanced)
- `frontend/src/app/setup/page.tsx` (wizard)
- pages `frontend/src/app/factory/page.tsx`, `suppliers/page.tsx`, `stock/page.tsx`, `orders/page.tsx`, `team/page.tsx`, `advanced/page.tsx` (hosts the existing Twin canvas and agent stream)
- `frontend/src/lib/forms.ts` (pure validators, vitest)

**Behaviour:**
- A user with no factory (404 on `/factory`) is redirected to `/setup`. The wizard has 4 steps:
  1. factory basics;
  2. lines (add rows or upload CSV);
  3. suppliers (rows or CSV, with the risk profile dropdown explained in one sentence);
  4. "import your Tally files" (stock, open POs, orders — existing importers) or "add orders by hand".

  Then "Done → Home". Every step can be skipped and finished later from the pages.
- Pages show tables with Add / Edit / Delete (edit hidden for viewers) and API errors verbatim. The Suppliers page shows reliability, with "no history yet" when the prior is 0/0 and no outcomes. The Stock page shows stock, open shipments with ETA, and the import buttons. The Team page shows members, invite by email plus role, and the Link Telegram button. Each row on the Suppliers page, and each order on the Orders page, has a "Telegram invite link" button: it shows the link with a Copy button and says "Send this to them; they tap Start once". A "Connected ✓" badge shows when a chat id is set.
- Plain language everywhere: "on-time chance", "cheapest safe plan", "expected cost (incl. penalty risk)". No "MILP", "Monte Carlo", "E[cost]" in Home or the data pages (they stay in Advanced).

- [ ] vitest for the validators; tsc 0
- [ ] Commit `feat: setup wizard and factory data pages`

### Task 3: Simple guided Home screen

**Files:** `frontend/src/app/page.tsx`, a new `frontend/src/components/GuidedFlow.tsx`, plus a slimmed `ExecutiveStoryView`

**Behaviour:** Home is 4 steps on one screen.
1. **Report a problem:** a text box ("e.g. Chennai shipment delayed 48h"), the scenario buttons, and "Use sliders" (the existing sandbox).
2. **Impact:** the at-risk order, units short with the shortfall explanation, the penalty, and which lines and suppliers are affected.
3. **Plans:** the 4 plan cards with cost, on-time chance, a one-line summary, and a "Recommended" badge, plus "Why?" expanding to the existing detail.
4. **Act:** "Ask suppliers first" (Sourcing panel), "Ask customer for more time" (Client panel), "Approve plan".

When nothing is wrong, Home shows "All good — no order at risk" with the report box. The Twin and agent logs live under Advanced.
- [ ] vitest for any new pure helper; `npm test`, tsc 0
- [ ] Browser check (controller): Home flow with scenario 1; the setup wizard on a fresh test account
- [ ] Commit `feat: guided home screen`

### Task 4: Docs, final review

- [ ] README: onboarding guide for a factory owner (sign up → wizard → imports → team → Telegram), the page tour, and the risk profiles table.
- [ ] Final review (one, most capable model) and a fix wave; then ask the user to merge.
