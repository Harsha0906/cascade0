-- ============================================================================
-- CASCADEZERO — Complete PostgreSQL Schema, Realtime Setup & Seed Data
-- Target: Supabase Cloud PostgreSQL (ap-south-1)
-- Fresh install: run this file, then migrations 001, 002, 003, 004, 005, 006, 007, 008 in order.
-- Row-Level Security (end state, see the section before Realtime): anon reads nothing; a signed-in
-- member reads only their factories' rows; every write goes through the backend's service role.
-- Factory: Apex Volt EV Battery Plant (Bengaluru Unit-2)
-- ============================================================================

-- ============================================================================
-- TABLE 0: factories (per-plant constants for the data-driven factory model)
-- ============================================================================
CREATE TABLE IF NOT EXISTS factories (
    id                          TEXT PRIMARY KEY,
    name                        TEXT NOT NULL,
    stock_item_name             TEXT NOT NULL,
    stock_item_code             TEXT,
    qa_dispatch_hours           FLOAT NOT NULL,
    safety_stock_units          INTEGER NOT NULL,
    production_hours_in_window  FLOAT NOT NULL
);

-- ============================================================================
-- TABLE 0b: factory_members (which Supabase Auth user holds which role in which factory)
-- Written only by the backend (`python -m app.admin add-member`).
-- ============================================================================
CREATE TABLE IF NOT EXISTS factory_members (
    user_id     UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    factory_id  TEXT NOT NULL REFERENCES factories (id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('owner', 'approver', 'viewer')),
    email       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, factory_id)
);
CREATE INDEX IF NOT EXISTS idx_factory_members_factory ON factory_members (factory_id);

-- ============================================================================
-- TABLE 0c: user_channels / link_codes (chat identities, migration 008 Part 3; service-only)
-- A WhatsApp number / Telegram chat is linked to a user + factory by a one-time code.
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_channels (
    channel     TEXT NOT NULL CHECK (channel IN ('whatsapp', 'telegram')),
    address     TEXT NOT NULL,              -- WhatsApp number (digits) / Telegram chat id
    user_id     UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    factory_id  TEXT NOT NULL REFERENCES factories (id) ON DELETE CASCADE,
    linked_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (channel, address)
);
CREATE INDEX IF NOT EXISTS idx_user_channels_user ON user_channels (user_id);
CREATE INDEX IF NOT EXISTS idx_user_channels_factory ON user_channels (factory_id);

CREATE TABLE IF NOT EXISTS link_codes (
    code        TEXT PRIMARY KEY,           -- sha256(code), never the code itself
    user_id     UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    factory_id  TEXT NOT NULL REFERENCES factories (id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_link_codes_expires ON link_codes (expires_at);

-- ============================================================================
-- TABLE 1: suppliers
-- Tracks inbound logistics suppliers across tiers and emergency channels
-- ============================================================================
CREATE TABLE IF NOT EXISTS suppliers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    tier            TEXT NOT NULL,
    route           TEXT NOT NULL,
    part_name       TEXT NOT NULL DEFAULT 'Aluminum Battery Casings',
    inbound_qty     INTEGER NOT NULL DEFAULT 0,
    max_available_qty INTEGER NOT NULL DEFAULT 0,
    extra_cost_per_unit_inr INTEGER NOT NULL DEFAULT 0,
    flat_charter_cost_inr INTEGER NOT NULL DEFAULT 0,
    lead_time_hours INTEGER NOT NULL DEFAULT 0,
    traffic_risk_pct FLOAT NOT NULL DEFAULT 0.0,
    weather_risk_pct FLOAT NOT NULL DEFAULT 0.0,
    status          TEXT NOT NULL DEFAULT 'ON_TIME',
    delay_hours     INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    factory_id      TEXT NOT NULL,
    telegram_chat_id TEXT,                  -- vendor RFQ chat (SOURCING_MODE=telegram)
    sourcing_role   TEXT,
    lead_time_sigma_hours FLOAT,
    delay_shock_min_hours FLOAT,
    delay_shock_max_hours FLOAT,
    unreliable_delay_min_hours FLOAT,
    unreliable_delay_max_hours FLOAT,
    min_lead_hours  FLOAT
);

-- ============================================================================
-- TABLE 2: vendor_history (Episodic Memory for Agents)
-- Historical reliability & quality records (the prior for learned vendor reliability)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vendor_history (
    id                      SERIAL PRIMARY KEY,
    supplier_id             TEXT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    past_orders_count       INTEGER NOT NULL DEFAULT 0,
    on_time_deliveries      INTEGER NOT NULL DEFAULT 0,
    reliability_score_pct   FLOAT NOT NULL DEFAULT 0.0,
    quality_rejection_rate_pct FLOAT NOT NULL DEFAULT 0.0,
    last_incident_note      TEXT NOT NULL DEFAULT '',
    factory_id              TEXT NOT NULL
);

-- ============================================================================
-- TABLE 3: production_lines
-- Shop-floor welding line status, speed, thermal, and overtime capacity
-- ============================================================================
CREATE TABLE IF NOT EXISTS production_lines (
    line_id                 TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'NORMAL',
    speed_pct               INTEGER NOT NULL DEFAULT 100,
    temp_celsius            FLOAT NOT NULL DEFAULT 60.0,
    daily_capacity_units    INTEGER NOT NULL DEFAULT 0,
    overtime_cost_per_hour_inr INTEGER NOT NULL DEFAULT 0,
    extra_units_per_ot_hour INTEGER NOT NULL DEFAULT 0,
    max_ot_hours            INTEGER NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    factory_id              TEXT NOT NULL,
    rated_units_per_hour    FLOAT
);

-- ============================================================================
-- TABLE 4: orders
-- Active client orders with SLA penalty exposure
-- ============================================================================
CREATE TABLE IF NOT EXISTS orders (
    order_id                TEXT PRIMARY KEY,
    client                  TEXT NOT NULL,
    required_qty            INTEGER NOT NULL DEFAULT 0,
    deadline_label          TEXT NOT NULL DEFAULT '',
    hours_remaining         INTEGER NOT NULL DEFAULT 0,
    sla_penalty_inr         INTEGER NOT NULL DEFAULT 0,
    partial_delay_penalty_inr INTEGER NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'ON_TRACK',
    shortfall_units         INTEGER NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    factory_id              TEXT NOT NULL,
    priority                INT NOT NULL DEFAULT 100,
    due_at                  TIMESTAMPTZ,  -- absolute deadline; hours_remaining is display only
    client_contact          TEXT                    -- '<channel>:<address>' the Client Agent messages
);

-- ============================================================================
-- TABLE 5: disruption_events
-- Raw and structured crisis payloads from all ingestion channels
-- ============================================================================
CREATE TABLE IF NOT EXISTS disruption_events (
    id                  SERIAL PRIMARY KEY,
    source_channel      TEXT NOT NULL DEFAULT 'MANUAL',
    raw_message         TEXT NOT NULL DEFAULT '',
    delay_hours         INTEGER NOT NULL DEFAULT 0,
    line2_speed_pct     INTEGER NOT NULL DEFAULT 100,
    shortfall_units     INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    factory_id          TEXT NOT NULL,
    order_id            TEXT,
    affected_supplier_id TEXT,
    line_impacts        JSONB NOT NULL DEFAULT '[]'
);

-- ============================================================================
-- TABLE 5b: scenarios (data-driven preset disruptions per factory; seeded below)
-- ============================================================================
CREATE TABLE IF NOT EXISTS scenarios (
    factory_id       TEXT NOT NULL,
    scenario_id      INT NOT NULL,
    title            TEXT NOT NULL,
    summary          TEXT NOT NULL DEFAULT '',
    raw_message      TEXT NOT NULL,
    delay_hours      INT NOT NULL,
    shortfall_units  INT,
    line_speeds      JSONB NOT NULL DEFAULT '{}',
    order_id         TEXT NOT NULL,
    PRIMARY KEY (factory_id, scenario_id)
);

-- ============================================================================
-- TABLE 5c: inventory (Phase 4) - items, stock levels, inbound shipments, order lines
-- ============================================================================
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
    order_id    TEXT NOT NULL,
    item_code   TEXT NOT NULL,
    qty         INT NOT NULL CHECK (qty > 0),
    -- Nullable here only because 006's seed insert predates the column; 008 sets NOT NULL.
    factory_id  TEXT,
    PRIMARY KEY (order_id, item_code)
);

-- Recorded vendor deliveries (Round A): reliability is learned from DELIVERED rows.
CREATE TABLE IF NOT EXISTS delivery_outcomes (
    id            BIGSERIAL PRIMARY KEY,
    factory_id    TEXT NOT NULL,
    supplier_id   TEXT NOT NULL,
    po_number     TEXT NOT NULL,
    units         INT NOT NULL CHECK (units > 0),
    promised_at   TIMESTAMPTZ NOT NULL,
    delivered_at  TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DELIVERED')),
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recorded_by   TEXT,
    UNIQUE (po_number, supplier_id)
);

-- Client Agent coordination (Task 3): one record per root analysis run, shared by the Client
-- and Sourcing agents. Optimistic concurrency like sourcing_sessions: every save is a
-- compare-and-set on `version`. Service-role only (RLS on, no anon/authenticated policy).
CREATE TABLE IF NOT EXISTS order_coordination (
    root_run_id  TEXT PRIMARY KEY,
    order_id     TEXT NOT NULL,
    factory_id   TEXT NOT NULL,
    status       TEXT NOT NULL,
    version      INT NOT NULL,
    payload      JSONB NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_order_coordination_order ON order_coordination (order_id);
ALTER TABLE order_coordination ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- TABLE 6: agent_logs (Realtime streamed to Agent Debate Terminal)
-- Every agent step, tool call, and reasoning trace
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_logs (
    id              SERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL DEFAULT '',
    step_order      INTEGER NOT NULL DEFAULT 0,
    agent_name      TEXT NOT NULL DEFAULT '',
    agent_role      TEXT NOT NULL DEFAULT '',
    badge_color     TEXT NOT NULL DEFAULT '',
    tool_called     TEXT NOT NULL DEFAULT '',
    tool_output_summary TEXT NOT NULL DEFAULT '',
    message         TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    factory_id      TEXT NOT NULL
);

-- ============================================================================
-- TABLE 7: purchase_orders (HITL Execution Ledger)
-- Committed recovery playbooks with Tally PO, WhatsApp, and SLA notice
-- ============================================================================
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number               TEXT PRIMARY KEY,
    playbook_id             TEXT NOT NULL DEFAULT '',
    order_id                TEXT NOT NULL DEFAULT '',
    vendor_allocations_json JSONB NOT NULL DEFAULT '{}',
    overtime_hours          INTEGER NOT NULL DEFAULT 0,
    total_cost_inr          INTEGER NOT NULL DEFAULT 0,
    net_sla_saved_inr       INTEGER NOT NULL DEFAULT 0,
    confidence_pct          FLOAT NOT NULL DEFAULT 0.0,
    tally_xml_payload       TEXT NOT NULL DEFAULT '',
    shift_broadcast_msg     TEXT NOT NULL DEFAULT '',
    client_sla_notice       TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'DRAFT',
    approved_by             TEXT NOT NULL DEFAULT '',
    run_id                  TEXT NOT NULL DEFAULT '',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    factory_id              TEXT NOT NULL
);

-- ============================================================================
-- SEED DATA: Apex Volt EV Battery Plant (Bengaluru Unit-2)
-- ============================================================================

-- Factory
INSERT INTO factories (id, name, stock_item_name, stock_item_code, qa_dispatch_hours, safety_stock_units, production_hours_in_window)
VALUES ('apex-volt-blr2', 'Apex Volt EV Battery Plant (Bengaluru Unit-2)', 'Aluminium Battery Casing', 'CASING', 2.5, 50, 16);

-- Suppliers
INSERT INTO suppliers (id, name, tier, route, part_name, inbound_qty, max_available_qty, extra_cost_per_unit_inr, flat_charter_cost_inr, lead_time_hours, traffic_risk_pct, weather_risk_pct, status, delay_hours, factory_id, sourcing_role, lead_time_sigma_hours, delay_shock_min_hours, delay_shock_max_hours, unreliable_delay_min_hours, unreliable_delay_max_hours, min_lead_hours)
VALUES
    ('SUP-CHN-01', 'Chennai Precision Casings Ltd', 'TIER-1', 'NH48 Chennai-Bengaluru Highway', 'Aluminum Battery Casings', 500, 500, 0, 0, 12, 5.0, 0.0, 'ON_TIME', 0, 'apex-volt-blr2', 'PRIMARY', 1.0, 1.0, 3.0, 2.0, 4.0, 8.0),
    ('SUP-PNY-02', 'Peenya Rapid Metals (Local SME Vendor)', 'TIER-2', 'Peenya Industrial Area (14 km)', 'Aluminum Battery Casings', 0, 200, 600, 0, 4, 6.0, 0.0, 'STANDBY', 0, 'apex-volt-blr2', 'BACKUP', 0.45, 1.0, 2.5, 1.5, 3.0, 2.0),
    ('SUP-HSR-03', 'Hosur Precision Castings', 'TIER-3', 'Hosur Industrial Corridor (42 km)', 'Aluminum Battery Casings', 0, 180, 850, 0, 8, 8.0, 0.0, 'STANDBY', 0, 'apex-volt-blr2', 'BACKUP', 1.1, 2.0, 4.0, 2.5, 5.0, 4.0),
    ('SUP-AIR-04', 'BlueDart Aviation Charter', 'EMERGENCY-AIR', 'HAL/KEMPEGOWDA Air Cargo Corridor', 'Aluminum Battery Casings', 0, 500, 0, 600000, 6, 0.0, 2.0, 'STANDBY', 0, 'apex-volt-blr2', 'EXPEDITE', 0.25, 1.0, 2.0, 1.0, 2.0, 4.5);

-- Vendor History (Episodic Memory)
INSERT INTO vendor_history (supplier_id, past_orders_count, on_time_deliveries, reliability_score_pct, quality_rejection_rate_pct, last_incident_note, factory_id)
VALUES
    ('SUP-CHN-01', 50, 48, 96.0, 0.5, 'Vulnerable to NE Monsoon flooding near Vellore/Ambur.', 'apex-volt-blr2'),
    ('SUP-PNY-02', 15, 14, 93.3, 0.8, 'Consistent 4h delivery via Tumkur Road; max batch 200 units.', 'apex-volt-blr2'),
    ('SUP-HSR-03', 11, 9, 81.8, 2.1, 'Border toll bottleneck at Attibele during peak hours.', 'apex-volt-blr2'),
    ('SUP-AIR-04', 5, 5, 98.5, 0.0, 'Guaranteed priority airfreight slot; high flat charter fee.', 'apex-volt-blr2');

-- Production Lines
INSERT INTO production_lines (line_id, name, status, speed_pct, temp_celsius, daily_capacity_units, overtime_cost_per_hour_inr, extra_units_per_ot_hour, max_ot_hours, factory_id, rated_units_per_hour)
VALUES
    ('LINE-1', 'Robotic Welding Line 1', 'NORMAL', 100, 61.0, 200, 11250, 19, 8, 'apex-volt-blr2', 19),
    ('LINE-2', 'Robotic Welding Line 2', 'NORMAL', 100, 62.0, 200, 0, 0, 0, 'apex-volt-blr2', 19),
    ('LINE-3', 'Robotic Welding Line 3', 'NORMAL', 100, 60.0, 150, 11250, 19, 8, 'apex-volt-blr2', 14);

-- Orders
INSERT INTO orders (order_id, client, required_qty, deadline_label, hours_remaining, sla_penalty_inr, partial_delay_penalty_inr, status, shortfall_units, factory_id, priority)
VALUES
    ('EV-402', 'Ather-Grid Mobility Corp', 500, 'Friday 17:00 IST (38 Hours Remaining)', 38, 2500000, 500000, 'ON_TRACK', 0, 'apex-volt-blr2', 10),
    ('EV-405', 'Deccan E-Fleet Logistics', 300, 'Monday 12:00 IST (110 Hours Remaining)', 110, 1000000, 200000, 'ON_TRACK', 0, 'apex-volt-blr2', 20);
UPDATE orders SET due_at = NOW() + hours_remaining * INTERVAL '1 hour' WHERE due_at IS NULL;

-- Inventory (Phase 4)
INSERT INTO items (factory_id, item_code, name, unit)
VALUES ('apex-volt-blr2', 'CASING', 'Aluminium Battery Casing', 'pcs');
INSERT INTO stock_levels (factory_id, item_code, on_hand_qty)
VALUES ('apex-volt-blr2', 'CASING', 350);
INSERT INTO inbound_shipments (shipment_id, factory_id, item_code, supplier_id, qty, eta, status)
VALUES ('SHP-CHN-0001', 'apex-volt-blr2', 'CASING', 'SUP-CHN-01', 500, NOW() + INTERVAL '20 hours', 'OPEN');
INSERT INTO order_lines (order_id, item_code, qty, factory_id)
VALUES ('EV-402', 'CASING', 500, 'apex-volt-blr2'), ('EV-405', 'CASING', 300, 'apex-volt-blr2');

-- Scenario presets
INSERT INTO scenarios (factory_id, scenario_id, title, summary, raw_message, delay_hours, shortfall_units, line_speeds, order_id)
VALUES
    ('apex-volt-blr2', 1, 'NH48 flood + Line 2 overheat', '48h delay, Line 2 at 50%, 150 casings short',
     'NH48 Chennai-Bengaluru highway flooding near Vellore delayed shipment of 500 aluminum battery casings from Chennai Precision by 48 hours. Simultaneously, Robotic Welding Line 2 overheated to 89.0°C and throttled to 50% speed. Current unit shortfall is 150 casings on Order #EV-402.',
     48, NULL, '{"LINE-2": 50}', 'EV-402'),
    ('apex-volt-blr2', 2, 'Minor toll delay', '6h delay, Line 2 at 85%, 25 casings short',
     'Minor toll transit delay on NH48 corridor causing 6 hours shipment delay for 25 units. Welding Line 2 slightly throttled to 85% speed (74°C). Shortfall is 25 battery casings on Order #EV-402.',
     6, 25, '{"LINE-2": 85}', 'EV-402'),
    ('apex-volt-blr2', 3, 'Supplier collapse', '72h delay, Line 2 at 25%, 350 casings short',
     'Severe supplier collapse: Chennai Precision Casings shipment blocked by 72 hours due to bridge damage near Ranipet. Robotic Welding Line 2 overheated to 92°C and dropped to 25% speed. Compound shortfall of 350 battery casings on Order #EV-402.',
     72, 350, '{"LINE-2": 25}', 'EV-402')
ON CONFLICT (factory_id, scenario_id) DO NOTHING;

-- ============================================================================
-- ROW-LEVEL SECURITY (end state; migrations 001-008 converge to the same)
-- anon: no policy and no privileges. authenticated: SELECT only, filtered to the factories the
-- user is a member of (RLS also filters Realtime). No INSERT/UPDATE/DELETE policies: the backend
-- writes with the service role. order_coordination, user_channels and link_codes are
-- service-only (RLS on, no policy). The
-- tables of 002/004 (sourcing_rfqs, analysis_runs, ...) get theirs from those migrations and 008.
-- ============================================================================
ALTER TABLE factories ENABLE ROW LEVEL SECURITY;
ALTER TABLE factory_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE production_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE disruption_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE scenarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_levels ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_shipments ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_coordination ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE link_codes ENABLE ROW LEVEL SECURITY;

-- A signed-in member reads only their own memberships.
DROP POLICY IF EXISTS factory_members_self_read ON factory_members;
CREATE POLICY factory_members_self_read ON factory_members
    FOR SELECT TO authenticated USING (user_id = (SELECT auth.uid()));
DROP POLICY IF EXISTS factories_member_read ON factories;
CREATE POLICY factories_member_read ON factories
    FOR SELECT TO authenticated
    USING (id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS suppliers_member_read ON suppliers;
CREATE POLICY suppliers_member_read ON suppliers
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS vendor_history_member_read ON vendor_history;
CREATE POLICY vendor_history_member_read ON vendor_history
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS production_lines_member_read ON production_lines;
CREATE POLICY production_lines_member_read ON production_lines
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS orders_member_read ON orders;
CREATE POLICY orders_member_read ON orders
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS disruption_events_member_read ON disruption_events;
CREATE POLICY disruption_events_member_read ON disruption_events
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS agent_logs_member_read ON agent_logs;
CREATE POLICY agent_logs_member_read ON agent_logs
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS purchase_orders_member_read ON purchase_orders;
CREATE POLICY purchase_orders_member_read ON purchase_orders
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS scenarios_member_read ON scenarios;
CREATE POLICY scenarios_member_read ON scenarios
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS items_member_read ON items;
CREATE POLICY items_member_read ON items
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS stock_levels_member_read ON stock_levels;
CREATE POLICY stock_levels_member_read ON stock_levels
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS inbound_shipments_member_read ON inbound_shipments;
CREATE POLICY inbound_shipments_member_read ON inbound_shipments
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS order_lines_member_read ON order_lines;
CREATE POLICY order_lines_member_read ON order_lines
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));
DROP POLICY IF EXISTS delivery_outcomes_member_read ON delivery_outcomes;
CREATE POLICY delivery_outcomes_member_read ON delivery_outcomes
    FOR SELECT TO authenticated
    USING (factory_id IN (SELECT factory_id FROM factory_members WHERE user_id = (SELECT auth.uid())));

REVOKE ALL ON factories FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON factories FROM authenticated;
REVOKE ALL ON suppliers FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON suppliers FROM authenticated;
REVOKE ALL ON vendor_history FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON vendor_history FROM authenticated;
REVOKE ALL ON production_lines FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON production_lines FROM authenticated;
REVOKE ALL ON orders FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON orders FROM authenticated;
REVOKE ALL ON disruption_events FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON disruption_events FROM authenticated;
REVOKE ALL ON agent_logs FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON agent_logs FROM authenticated;
REVOKE ALL ON purchase_orders FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON purchase_orders FROM authenticated;
REVOKE ALL ON scenarios FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON scenarios FROM authenticated;
REVOKE ALL ON items FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON items FROM authenticated;
REVOKE ALL ON stock_levels FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON stock_levels FROM authenticated;
REVOKE ALL ON inbound_shipments FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON inbound_shipments FROM authenticated;
REVOKE ALL ON order_lines FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON order_lines FROM authenticated;
REVOKE ALL ON delivery_outcomes FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON delivery_outcomes FROM authenticated;
REVOKE ALL ON factory_members FROM anon;
REVOKE INSERT, UPDATE, DELETE ON factory_members FROM authenticated;
REVOKE ALL ON order_coordination FROM anon, authenticated;
REVOKE ALL ON user_channels FROM anon, authenticated;
REVOKE ALL ON link_codes FROM anon, authenticated;

-- ============================================================================
-- SUPABASE REALTIME: Enable postgres_changes on all 7 tables
-- ============================================================================
ALTER PUBLICATION supabase_realtime ADD TABLE factories;
ALTER PUBLICATION supabase_realtime ADD TABLE suppliers;
ALTER PUBLICATION supabase_realtime ADD TABLE vendor_history;
ALTER PUBLICATION supabase_realtime ADD TABLE production_lines;
ALTER PUBLICATION supabase_realtime ADD TABLE orders;
ALTER PUBLICATION supabase_realtime ADD TABLE disruption_events;
ALTER PUBLICATION supabase_realtime ADD TABLE agent_logs;
ALTER PUBLICATION supabase_realtime ADD TABLE purchase_orders;
