-- ============================================================================
-- CascadeZero — Row-Level Security + approval audit columns
--
-- Apply AFTER schema.sql (Supabase SQL editor, or `supabase db push`).
-- Before applying, set SUPABASE_SERVICE_ROLE_KEY in backend/.env: once RLS is on,
-- the anon key is read-only and every backend write must use the service-role key
-- (which bypasses RLS). Never put the service-role key in the frontend.
-- Refuses to run once 008 (member-only RLS) is applied: see the level-8 guard below.
-- ============================================================================

-- Level-8 guard: once 008 (member-only RLS) is applied, re-running this file would reopen
-- anon / USING (true) read policies, so it refuses to run at level 8 or above.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'schema_migrations') THEN
        IF EXISTS (SELECT 1 FROM schema_migrations WHERE version >= 8) THEN
            RAISE EXCEPTION 'database is at level 8+; re-running 001 would reopen anon/USING(true) policies — not allowed';
        END IF;
    END IF;
END
$$;

-- 1. Audit columns on the execution ledger
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS approved_by TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS run_id      TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS purchase_orders_run_id_uniq
    ON purchase_orders (run_id) WHERE run_id <> '';   -- one execution per analysis run

-- 2. Enable RLS on every table
ALTER TABLE suppliers         ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_history    ENABLE ROW LEVEL SECURITY;
ALTER TABLE production_lines  ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders            ENABLE ROW LEVEL SECURITY;
ALTER TABLE disruption_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_logs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_orders   ENABLE ROW LEVEL SECURITY;

-- 3. Read-only access for the browser (anon + signed-in users) so the dashboard and
--    Realtime subscriptions keep working. No INSERT/UPDATE/DELETE policies exist,
--    so those are denied for anon/authenticated; only the service role can write.
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['suppliers','vendor_history','production_lines','orders',
                           'disruption_events','agent_logs','purchase_orders']
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', t || '_read', t);
    EXECUTE format('CREATE POLICY %I ON %I FOR SELECT TO anon, authenticated USING (true)', t || '_read', t);
  END LOOP;
END $$;

-- Tighten further for a multi-tenant deployment: add a factory_id column to each table
-- and replace `USING (true)` with a check against the signed-in user's factory.
