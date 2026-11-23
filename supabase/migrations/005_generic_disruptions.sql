-- ============================================================================
-- CascadeZero — Phase 3: generic disruptions + data-driven scenario presets
-- Apply after 004_durable_state.sql. Safe to re-run below level 8 (refuses to run once 008 is applied).
-- ============================================================================

-- Level-8 guard: once 008 (member-only RLS) is applied, re-running this file would reopen
-- anon / USING (true) read policies, so it refuses to run at level 8 or above.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'schema_migrations') THEN
        IF EXISTS (SELECT 1 FROM schema_migrations WHERE version >= 8) THEN
            RAISE EXCEPTION 'database is at level 8+; re-running 005 would reopen anon/USING(true) policies — not allowed';
        END IF;
    END IF;
END
$$;

-- Prerequisite guard: refuse to run unless migration 004 is really applied.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'schema_migrations')
       OR NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 4) THEN
        RAISE EXCEPTION 'Migration 004 not applied (schema_migrations has no version 4); apply 001-004 before 005';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS scenarios (
    factory_id       TEXT NOT NULL,
    scenario_id      INT NOT NULL,
    title            TEXT NOT NULL,
    summary          TEXT NOT NULL DEFAULT '',
    raw_message      TEXT NOT NULL,
    delay_hours      INT NOT NULL,
    shortfall_units  INT NOT NULL,
    line_speeds      JSONB NOT NULL DEFAULT '{}',
    order_id         TEXT NOT NULL,
    PRIMARY KEY (factory_id, scenario_id)
);
ALTER TABLE scenarios ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS scenarios_read ON scenarios;
CREATE POLICY scenarios_read ON scenarios FOR SELECT TO anon, authenticated USING (true);

INSERT INTO scenarios (factory_id, scenario_id, title, summary, raw_message, delay_hours, shortfall_units, line_speeds, order_id)
VALUES
    ('apex-volt-blr2', 1, 'NH48 flood + Line 2 overheat', '48h delay, Line 2 at 50%, 150 casings short',
     'NH48 Chennai-Bengaluru highway flooding near Vellore delayed shipment of 500 aluminum battery casings from Chennai Precision by 48 hours. Simultaneously, Robotic Welding Line 2 overheated to 89.0°C and throttled to 50% speed. Current unit shortfall is 150 casings on Order #EV-402.',
     48, 150, '{"LINE-2": 50}', 'EV-402'),
    ('apex-volt-blr2', 2, 'Minor toll delay', '6h delay, Line 2 at 85%, 25 casings short',
     'Minor toll transit delay on NH48 corridor causing 6 hours shipment delay for 25 units. Welding Line 2 slightly throttled to 85% speed (74°C). Shortfall is 25 battery casings on Order #EV-402.',
     6, 25, '{"LINE-2": 85}', 'EV-402'),
    ('apex-volt-blr2', 3, 'Supplier collapse', '72h delay, Line 2 at 25%, 350 casings short',
     'Severe supplier collapse: Chennai Precision Casings shipment blocked by 72 hours due to bridge damage near Ranipet. Robotic Welding Line 2 overheated to 92°C and dropped to 25% speed. Compound shortfall of 350 battery casings on Order #EV-402.',
     72, 350, '{"LINE-2": 25}', 'EV-402')
ON CONFLICT (factory_id, scenario_id) DO NOTHING;

-- Generic disruption audit columns (line2_speed_pct is kept for old rows).
ALTER TABLE disruption_events ADD COLUMN IF NOT EXISTS factory_id TEXT;
ALTER TABLE disruption_events ADD COLUMN IF NOT EXISTS order_id TEXT;
ALTER TABLE disruption_events ADD COLUMN IF NOT EXISTS affected_supplier_id TEXT;
ALTER TABLE disruption_events ADD COLUMN IF NOT EXISTS line_impacts JSONB NOT NULL DEFAULT '[]';

INSERT INTO schema_migrations (version) VALUES (5) ON CONFLICT DO NOTHING;
