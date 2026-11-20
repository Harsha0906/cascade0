-- ============================================================================
-- CascadeZero — Phase 4: inventory-based shortfall (items, stock, inbound shipments, order lines)
-- Apply after 005_generic_disruptions.sql. Safe to re-run.
-- ============================================================================

-- Prerequisite guard: refuse to run unless migration 005 is really applied.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'schema_migrations')
       OR NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 5) THEN
        RAISE EXCEPTION 'Migration 005 not applied (schema_migrations has no version 5); apply 001-005 before 006';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS items (
    factory_id  TEXT NOT NULL,
    item_code   TEXT NOT NULL,
    name        TEXT NOT NULL,
    unit        TEXT NOT NULL DEFAULT 'pcs',
    PRIMARY KEY (factory_id, item_code)
);

CREATE TABLE IF NOT EXISTS stock_levels (
    factory_id   TEXT NOT NULL,
    item_code    TEXT NOT NULL,
    on_hand_qty  INT NOT NULL CHECK (on_hand_qty >= 0),
    as_of        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (factory_id, item_code)
);

CREATE TABLE IF NOT EXISTS inbound_shipments (
    shipment_id  TEXT PRIMARY KEY,
    factory_id   TEXT NOT NULL,
    item_code    TEXT NOT NULL,
    supplier_id  TEXT NOT NULL,
    qty          INT NOT NULL CHECK (qty > 0),
    eta          TIMESTAMPTZ NOT NULL,
    status       TEXT NOT NULL DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_id   TEXT NOT NULL,
    item_code  TEXT NOT NULL,
    qty        INT NOT NULL CHECK (qty > 0),
    PRIMARY KEY (order_id, item_code)
);

ALTER TABLE items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS items_read ON items;
CREATE POLICY items_read ON items FOR SELECT TO anon, authenticated USING (true);

ALTER TABLE stock_levels ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS stock_levels_read ON stock_levels;
CREATE POLICY stock_levels_read ON stock_levels FOR SELECT TO anon, authenticated USING (true);

ALTER TABLE inbound_shipments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS inbound_shipments_read ON inbound_shipments;
CREATE POLICY inbound_shipments_read ON inbound_shipments FOR SELECT TO anon, authenticated USING (true);

ALTER TABLE order_lines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS order_lines_read ON order_lines;
CREATE POLICY order_lines_read ON order_lines FOR SELECT TO anon, authenticated USING (true);

ALTER TABLE orders ADD COLUMN IF NOT EXISTS priority INT NOT NULL DEFAULT 100;
ALTER TABLE factories ADD COLUMN IF NOT EXISTS stock_item_code TEXT;
-- Scenario shortfall may now be computed from inventory instead of typed in.
ALTER TABLE scenarios ALTER COLUMN shortfall_units DROP NOT NULL;

-- Demo seed: Apex Volt casings.
INSERT INTO items (factory_id, item_code, name, unit)
VALUES ('apex-volt-blr2', 'CASING', 'Aluminium Battery Casing', 'pcs')
ON CONFLICT (factory_id, item_code) DO NOTHING;

INSERT INTO stock_levels (factory_id, item_code, on_hand_qty)
VALUES ('apex-volt-blr2', 'CASING', 350)
ON CONFLICT (factory_id, item_code) DO NOTHING;

INSERT INTO inbound_shipments (shipment_id, factory_id, item_code, supplier_id, qty, eta, status)
VALUES ('SHP-CHN-0001', 'apex-volt-blr2', 'CASING', 'SUP-CHN-01', 500, NOW() + INTERVAL '20 hours', 'OPEN')
ON CONFLICT (shipment_id) DO NOTHING;

INSERT INTO order_lines (order_id, item_code, qty)
VALUES ('EV-402', 'CASING', 500), ('EV-405', 'CASING', 300)
ON CONFLICT (order_id, item_code) DO NOTHING;

UPDATE orders SET priority = 10 WHERE order_id = 'EV-402';
UPDATE orders SET priority = 20 WHERE order_id = 'EV-405';
UPDATE factories SET stock_item_code = 'CASING' WHERE id = 'apex-volt-blr2';
UPDATE scenarios SET shortfall_units = NULL WHERE factory_id = 'apex-volt-blr2' AND scenario_id = 1;

INSERT INTO schema_migrations (version) VALUES (6) ON CONFLICT DO NOTHING;
