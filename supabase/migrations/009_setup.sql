-- ============================================================================
-- CascadeZero — Round S: factory setup and data APIs
-- Apply after 008_identity.sql. Safe to re-run.
--
-- Part 1: suppliers.risk_profile — the explicit low / medium / high risk profile the user picked
--         for a supplier. The derived parameters (lead sigma, shock %, ranges) live in the existing
--         columns; this records which profile produced them so the dashboard can show it.
-- Part 2: contact_invites — single-use deep-link tokens that connect a supplier's or a client's
--         Telegram chat (https://t.me/<bot>?start=<token>). Service-only: RLS on, no policy at
--         all, no privileges for the browser roles. Tokens are stored as SHA-256 hashes.
-- ============================================================================

-- Prerequisite guard: refuse to run unless migration 008 is really applied.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'schema_migrations')
       OR NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 8) THEN
        RAISE EXCEPTION 'Migration 008 not applied (schema_migrations has no version 8); apply 001-008 before 009';
    END IF;
END
$$;

-- Part 1. A plain column on a table that already has member-only RLS and no write grants for the
-- browser roles; nothing here opens access. NULL = a supplier set up before profiles existed.
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS risk_profile TEXT;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'suppliers_risk_profile_check') THEN
        ALTER TABLE suppliers ADD CONSTRAINT suppliers_risk_profile_check
            CHECK (risk_profile IS NULL OR risk_profile IN ('low', 'medium', 'high'));
    END IF;
END
$$;

-- Part 2. Telegram contact invites.
CREATE TABLE IF NOT EXISTS contact_invites (
    token_hash  TEXT PRIMARY KEY,           -- sha256(token), never the token itself
    factory_id  TEXT NOT NULL REFERENCES factories (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('supplier', 'client')),
    target_id   TEXT NOT NULL,              -- suppliers.id (supplier) / orders.order_id (client)
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_contact_invites_factory ON contact_invites (factory_id);
CREATE INDEX IF NOT EXISTS idx_contact_invites_expires ON contact_invites (expires_at);

ALTER TABLE contact_invites ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON contact_invites FROM anon, authenticated;

-- Final RLS check (keep it just above the version insert): refuse to record level 9 if any
-- public-schema policy is USING (true) / WITH CHECK (true) or applies to anon or PUBLIC, or if
-- any known table has RLS disabled. Any failure rolls the whole migration back.
DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(format('%I.%I', tablename, policyname), ', ') INTO bad
      FROM pg_policies
     WHERE schemaname = 'public'
       AND (qual = 'true' OR with_check = 'true' OR 'anon' = ANY (roles) OR 'public' = ANY (roles));
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'RLS check failed: open policies remain: %', bad;
    END IF;
    SELECT string_agg(c.relname, ', ') INTO bad
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
       AND c.relname = ANY (ARRAY['factories', 'factory_members', 'suppliers', 'vendor_history', 'production_lines', 'orders', 'disruption_events', 'agent_logs', 'purchase_orders', 'sourcing_rfqs', 'scenarios', 'items', 'stock_levels', 'inbound_shipments', 'order_lines', 'delivery_outcomes', 'analysis_runs', 'sourcing_sessions', 'execution_receipts', 'webhook_events', 'schema_migrations', 'order_coordination', 'user_channels', 'link_codes', 'contact_invites']);
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'RLS check failed: row level security disabled on: %', bad;
    END IF;
END
$$;

-- Keep this the LAST statement of the file: version 9 is recorded only once every part above
-- has been applied.
INSERT INTO schema_migrations (version) VALUES (9) ON CONFLICT DO NOTHING;
