-- ============================================================================
-- CASCADEZERO — Complete PostgreSQL Schema, Realtime Setup & Seed Data
-- Target: Supabase Cloud PostgreSQL (ap-south-1)
-- Factory: Apex Volt EV Battery Plant (Bengaluru Unit-2)
-- ============================================================================

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
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- TABLE 2: vendor_history (Episodic Memory for Agents)
-- Historical reliability & quality records used by CFO Watchdog agent
-- ============================================================================
CREATE TABLE IF NOT EXISTS vendor_history (
    id                      SERIAL PRIMARY KEY,
    supplier_id             TEXT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    past_orders_count       INTEGER NOT NULL DEFAULT 0,
    on_time_deliveries      INTEGER NOT NULL DEFAULT 0,
    reliability_score_pct   FLOAT NOT NULL DEFAULT 0.0,
    quality_rejection_rate_pct FLOAT NOT NULL DEFAULT 0.0,
    last_incident_note      TEXT NOT NULL DEFAULT ''
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
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- SEED DATA: Apex Volt EV Battery Plant (Bengaluru Unit-2)
-- ============================================================================

-- Suppliers
INSERT INTO suppliers (id, name, tier, route, part_name, inbound_qty, max_available_qty, extra_cost_per_unit_inr, flat_charter_cost_inr, lead_time_hours, traffic_risk_pct, weather_risk_pct, status, delay_hours)
VALUES
    ('SUP-CHN-01', 'Chennai Precision Casings Ltd', 'TIER-1', 'NH48 Chennai-Bengaluru Highway', 'Aluminum Battery Casings', 500, 500, 0, 0, 12, 5.0, 0.0, 'ON_TIME', 0),
    ('SUP-PNY-02', 'Peenya Rapid Metals (Local SME Vendor)', 'TIER-2', 'Peenya Industrial Area (14 km)', 'Aluminum Battery Casings', 0, 200, 600, 0, 4, 6.0, 0.0, 'STANDBY', 0),
    ('SUP-HSR-03', 'Hosur Precision Castings', 'TIER-3', 'Hosur Industrial Corridor (42 km)', 'Aluminum Battery Casings', 0, 180, 850, 0, 8, 8.0, 0.0, 'STANDBY', 0),
    ('SUP-AIR-04', 'BlueDart Aviation Charter', 'EMERGENCY-AIR', 'HAL/KEMPEGOWDA Air Cargo Corridor', 'Aluminum Battery Casings', 0, 500, 0, 600000, 6, 0.0, 2.0, 'STANDBY', 0);

-- Vendor History (Episodic Memory)
INSERT INTO vendor_history (supplier_id, past_orders_count, on_time_deliveries, reliability_score_pct, quality_rejection_rate_pct, last_incident_note)
VALUES
    ('SUP-CHN-01', 50, 48, 96.0, 0.5, 'Vulnerable to NE Monsoon flooding near Vellore/Ambur.'),
    ('SUP-PNY-02', 15, 14, 93.3, 0.8, 'Consistent 4h delivery via Tumkur Road; max batch 200 units.'),
    ('SUP-HSR-03', 11, 9, 81.8, 2.1, 'Border toll bottleneck at Attibele during peak hours.'),
    ('SUP-AIR-04', 5, 5, 98.5, 0.0, 'Guaranteed priority airfreight slot; high flat charter fee.');

-- Production Lines
INSERT INTO production_lines (line_id, name, status, speed_pct, temp_celsius, daily_capacity_units, overtime_cost_per_hour_inr, extra_units_per_ot_hour, max_ot_hours)
VALUES
    ('LINE-1', 'Robotic Welding Line 1', 'NORMAL', 100, 61.0, 200, 22500, 38, 8),
    ('LINE-2', 'Robotic Welding Line 2', 'NORMAL', 100, 62.0, 200, 0, 0, 0),
    ('LINE-3', 'Robotic Welding Line 3', 'NORMAL', 100, 60.0, 150, 22500, 38, 8);

-- Orders
INSERT INTO orders (order_id, client, required_qty, deadline_label, hours_remaining, sla_penalty_inr, partial_delay_penalty_inr, status, shortfall_units)
VALUES
    ('EV-402', 'Ather-Grid Mobility Corp', 500, 'Friday 17:00 IST (38 Hours Remaining)', 38, 2500000, 500000, 'ON_TRACK', 0),
    ('EV-405', 'Deccan E-Fleet Logistics', 300, 'Monday 12:00 IST (110 Hours Remaining)', 110, 1000000, 200000, 'ON_TRACK', 0);

-- ============================================================================
-- SUPABASE REALTIME: Enable postgres_changes on all 7 tables
-- ============================================================================
ALTER PUBLICATION supabase_realtime ADD TABLE suppliers;
ALTER PUBLICATION supabase_realtime ADD TABLE vendor_history;
ALTER PUBLICATION supabase_realtime ADD TABLE production_lines;
ALTER PUBLICATION supabase_realtime ADD TABLE orders;
ALTER PUBLICATION supabase_realtime ADD TABLE disruption_events;
ALTER PUBLICATION supabase_realtime ADD TABLE agent_logs;
ALTER PUBLICATION supabase_realtime ADD TABLE purchase_orders;
