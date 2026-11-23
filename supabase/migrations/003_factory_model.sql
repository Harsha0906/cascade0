-- ============================================================================
-- CascadeZero — Phase 1: data-driven factory model
-- Apply after 002_sourcing_agent.sql. Safe to re-run below level 8 (refuses to run once 008 is applied): no step fails on a second run;
-- re-running restores the demo factory's seed values (factory row, supplier and line columns).
-- ============================================================================

-- Level-8 guard: once 008 (member-only RLS) is applied, re-running this file would reopen
-- anon / USING (true) read policies, so it refuses to run at level 8 or above.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'schema_migrations') THEN
        IF EXISTS (SELECT 1 FROM schema_migrations WHERE version >= 8) THEN
            RAISE EXCEPTION 'database is at level 8+; re-running 003 would reopen anon/USING(true) policies — not allowed';
        END IF;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS factories (
    id                          TEXT PRIMARY KEY,
    name                        TEXT NOT NULL,
    stock_item_name             TEXT NOT NULL,
    qa_dispatch_hours           FLOAT NOT NULL,
    safety_stock_units          INTEGER NOT NULL,
    production_hours_in_window  FLOAT NOT NULL
);

INSERT INTO factories (id, name, stock_item_name, qa_dispatch_hours, safety_stock_units, production_hours_in_window)
VALUES ('apex-volt-blr2', 'Apex Volt EV Battery Plant (Bengaluru Unit-2)', 'Aluminium Battery Casing', 2.5, 50, 16)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    stock_item_name = EXCLUDED.stock_item_name,
    qa_dispatch_hours = EXCLUDED.qa_dispatch_hours,
    safety_stock_units = EXCLUDED.safety_stock_units,
    production_hours_in_window = EXCLUDED.production_hours_in_window;

ALTER TABLE factories ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS factories_read ON factories;
CREATE POLICY factories_read ON factories FOR SELECT TO anon, authenticated USING (true);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication_tables WHERE pubname = 'supabase_realtime' AND tablename = 'factories') THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE factories;
    END IF;
END $$;

-- Suppliers
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS factory_id TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS sourcing_role TEXT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS lead_time_sigma_hours FLOAT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS delay_shock_min_hours FLOAT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS delay_shock_max_hours FLOAT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS unreliable_delay_min_hours FLOAT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS unreliable_delay_max_hours FLOAT;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS min_lead_hours FLOAT;

UPDATE suppliers SET factory_id = 'apex-volt-blr2', sourcing_role = 'PRIMARY',
    lead_time_sigma_hours = 1.0, delay_shock_min_hours = 1.0, delay_shock_max_hours = 3.0,
    unreliable_delay_min_hours = 2.0, unreliable_delay_max_hours = 4.0, min_lead_hours = 8.0
    WHERE id = 'SUP-CHN-01';
UPDATE suppliers SET factory_id = 'apex-volt-blr2', sourcing_role = 'BACKUP',
    lead_time_sigma_hours = 0.45, delay_shock_min_hours = 1.0, delay_shock_max_hours = 2.5,
    unreliable_delay_min_hours = 1.5, unreliable_delay_max_hours = 3.0, min_lead_hours = 2.0
    WHERE id = 'SUP-PNY-02';
UPDATE suppliers SET factory_id = 'apex-volt-blr2', sourcing_role = 'BACKUP',
    lead_time_sigma_hours = 1.1, delay_shock_min_hours = 2.0, delay_shock_max_hours = 4.0,
    unreliable_delay_min_hours = 2.5, unreliable_delay_max_hours = 5.0, min_lead_hours = 4.0
    WHERE id = 'SUP-HSR-03';
UPDATE suppliers SET factory_id = 'apex-volt-blr2', sourcing_role = 'EXPEDITE',
    lead_time_sigma_hours = 0.25, delay_shock_min_hours = 1.0, delay_shock_max_hours = 2.0,
    unreliable_delay_min_hours = 1.0, unreliable_delay_max_hours = 2.0, min_lead_hours = 4.5
    WHERE id = 'SUP-AIR-04';

-- Production lines
ALTER TABLE production_lines ADD COLUMN IF NOT EXISTS factory_id TEXT;
ALTER TABLE production_lines ADD COLUMN IF NOT EXISTS rated_units_per_hour FLOAT;

UPDATE production_lines SET factory_id = 'apex-volt-blr2', rated_units_per_hour = 19,
    overtime_cost_per_hour_inr = 11250, extra_units_per_ot_hour = 19, max_ot_hours = 8 WHERE line_id = 'LINE-1';
UPDATE production_lines SET factory_id = 'apex-volt-blr2', rated_units_per_hour = 19,
    overtime_cost_per_hour_inr = 0, extra_units_per_ot_hour = 0, max_ot_hours = 0 WHERE line_id = 'LINE-2';
UPDATE production_lines SET factory_id = 'apex-volt-blr2', rated_units_per_hour = 14,
    overtime_cost_per_hour_inr = 11250, extra_units_per_ot_hour = 19, max_ot_hours = 8 WHERE line_id = 'LINE-3';

-- Orders (unused until Phase 7; added now so tenancy needs no second data migration)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS factory_id TEXT;
UPDATE orders SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
