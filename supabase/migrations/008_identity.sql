-- ============================================================================
-- CascadeZero — Round B: identity and tenancy
-- Apply after 007_learning_and_coordination.sql. Safe to re-run.
--
-- Part 1 (Task 1): factory_members — which Supabase Auth user holds which role in which factory.
-- ============================================================================

-- Prerequisite guard: refuse to run unless migration 007 is really applied.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'schema_migrations')
       OR NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 7) THEN
        RAISE EXCEPTION 'Migration 007 not applied (schema_migrations has no version 7); apply 001-007 before 008';
    END IF;
END
$$;

-- Memberships are written only by the backend (service role) via `python -m app.admin add-member`.
CREATE TABLE IF NOT EXISTS factory_members (
    user_id     UUID NOT NULL,
    factory_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('owner', 'approver', 'viewer')),
    email       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, factory_id)
);
CREATE INDEX IF NOT EXISTS idx_factory_members_factory ON factory_members (factory_id);

ALTER TABLE factory_members ENABLE ROW LEVEL SECURITY;
-- A signed-in member reads only their own rows. No anon access; no write policies.
DROP POLICY IF EXISTS factory_members_self_read ON factory_members;
CREATE POLICY factory_members_self_read ON factory_members
    FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));
REVOKE ALL ON factory_members FROM anon;
REVOKE INSERT, UPDATE, DELETE ON factory_members FROM authenticated;

-- Who recorded a delivery (the verified actor's email); it moves learned vendor reliability.
ALTER TABLE delivery_outcomes ADD COLUMN IF NOT EXISTS recorded_by TEXT;

-- ----------------------------------------------------------------------------
-- >>> Later Round B tasks (Task 3 onward) APPEND their parts HERE, above the version insert. <<<
-- ----------------------------------------------------------------------------

-- Keep this the LAST statement of the file: version 8 is recorded only once every part above
-- has been applied.
INSERT INTO schema_migrations (version) VALUES (8) ON CONFLICT DO NOTHING;
