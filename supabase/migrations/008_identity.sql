-- ============================================================================
-- CascadeZero — Round B: identity and tenancy
-- Apply after 007_learning_and_coordination.sql. Safe to re-run.
--
-- Part 1 (Task 1): factory_members — which Supabase Auth user holds which role in which factory.
-- Part 2 (Task 3): factory_id on every tenant table and member-only Row-Level Security (anon reads
--                  nothing; a signed-in member reads only their factories' rows).
-- Part 3 (Task 5): user_channels and link_codes (chat identities; service-only).
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

-- ============================================================================
-- Part 2 (Task 3): factory_id on every tenant table, member-only Row-Level Security.
-- Order matters on a live database at level 7: add the columns (nullable), backfill,
-- SET NOT NULL, and only then replace the policies.
-- ============================================================================

-- Memberships point at real factories and real Auth users; deleting either removes the membership.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.factory_members'::regclass
                      AND conname = 'factory_members_factory_id_fkey') THEN
        ALTER TABLE factory_members ADD CONSTRAINT factory_members_factory_id_fkey
            FOREIGN KEY (factory_id) REFERENCES factories (id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.factory_members'::regclass
                      AND conname = 'factory_members_user_id_fkey') THEN
        ALTER TABLE factory_members ADD CONSTRAINT factory_members_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE CASCADE;
    END IF;
END
$$;

-- 2a. New factory_id columns (nullable first so existing rows can be backfilled).
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS factory_id TEXT;
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS factory_id TEXT;
ALTER TABLE execution_receipts ADD COLUMN IF NOT EXISTS factory_id TEXT;
ALTER TABLE sourcing_rfqs ADD COLUMN IF NOT EXISTS factory_id TEXT;
ALTER TABLE sourcing_sessions ADD COLUMN IF NOT EXISTS factory_id TEXT;
ALTER TABLE vendor_history ADD COLUMN IF NOT EXISTS factory_id TEXT;
ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS factory_id TEXT;
-- Inbound webhook ids are recorded before the tenant is known: stays nullable, service-only.
ALTER TABLE webhook_events ADD COLUMN IF NOT EXISTS factory_id TEXT;

-- 2b. Backfill, step 1: infer each row's owner from the row it belongs to (run, order, supplier).
UPDATE vendor_history vh SET factory_id = s.factory_id
  FROM suppliers s WHERE vh.factory_id IS NULL AND s.id = vh.supplier_id AND s.factory_id IS NOT NULL;
UPDATE order_lines ol SET factory_id = o.factory_id
  FROM orders o WHERE ol.factory_id IS NULL AND o.order_id = ol.order_id AND o.factory_id IS NOT NULL;
UPDATE disruption_events de SET factory_id = o.factory_id
  FROM orders o WHERE de.factory_id IS NULL AND o.order_id = de.order_id AND o.factory_id IS NOT NULL;
UPDATE purchase_orders po SET factory_id = r.factory_id
  FROM analysis_runs r WHERE po.factory_id IS NULL AND r.run_id = po.run_id;
UPDATE purchase_orders po SET factory_id = o.factory_id
  FROM orders o WHERE po.factory_id IS NULL AND o.order_id = po.order_id AND o.factory_id IS NOT NULL;
UPDATE agent_logs al SET factory_id = r.factory_id
  FROM analysis_runs r WHERE al.factory_id IS NULL AND r.run_id = al.run_id;
UPDATE execution_receipts er SET factory_id = r.factory_id
  FROM analysis_runs r WHERE er.factory_id IS NULL AND r.run_id = er.root_run_id;
UPDATE execution_receipts er SET factory_id = r.factory_id
  FROM analysis_runs r WHERE er.factory_id IS NULL AND r.run_id = er.run_id;
UPDATE sourcing_rfqs sr SET factory_id = r.factory_id
  FROM analysis_runs r WHERE sr.factory_id IS NULL AND r.run_id = sr.run_id;
UPDATE sourcing_rfqs sr SET factory_id = s.factory_id
  FROM suppliers s WHERE sr.factory_id IS NULL AND s.id = sr.supplier_id AND s.factory_id IS NOT NULL;
UPDATE sourcing_sessions ss SET factory_id = r.factory_id
  FROM analysis_runs r WHERE ss.factory_id IS NULL AND r.run_id = ss.run_id;
UPDATE delivery_outcomes d SET factory_id = s.factory_id
  FROM suppliers s WHERE d.factory_id IS NULL AND s.id = d.supplier_id AND s.factory_id IS NOT NULL;

-- 2b, step 2: rows still unowned predate tenancy. With exactly one factory they are the demo
--     factory's; with several factories nobody can tell, so stop and let the operator assign them.
DO $$
DECLARE
    t TEXT;
    unowned BOOLEAN;
BEGIN
    IF (SELECT count(*) FROM factories) > 1 THEN
        FOREACH t IN ARRAY ARRAY['suppliers', 'vendor_history', 'production_lines', 'orders', 'disruption_events', 'agent_logs', 'purchase_orders', 'sourcing_rfqs', 'scenarios', 'items', 'stock_levels', 'inbound_shipments', 'order_lines', 'delivery_outcomes', 'analysis_runs', 'sourcing_sessions', 'execution_receipts', 'order_coordination']
        LOOP
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM public.%I WHERE factory_id IS NULL)', t) INTO unowned;
            IF unowned THEN
                RAISE EXCEPTION 'table % has rows with no factory_id and more than one factory exists: assign them (UPDATE % SET factory_id = ...) before applying 008', t, t;
            END IF;
        END LOOP;
    END IF;
END
$$;


UPDATE suppliers SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE vendor_history SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE production_lines SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE orders SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE disruption_events SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE agent_logs SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE purchase_orders SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE sourcing_rfqs SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE scenarios SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE items SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE stock_levels SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE inbound_shipments SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE order_lines SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE delivery_outcomes SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE analysis_runs SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE sourcing_sessions SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE execution_receipts SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;
UPDATE order_coordination SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;

-- 2c. Every tenant row now has an owner. (webhook_events stays nullable.)
ALTER TABLE suppliers ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE vendor_history ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE production_lines ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE orders ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE disruption_events ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE agent_logs ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE purchase_orders ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE sourcing_rfqs ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE scenarios ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE items ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE stock_levels ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE inbound_shipments ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE order_lines ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE delivery_outcomes ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE analysis_runs ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE sourcing_sessions ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE execution_receipts ALTER COLUMN factory_id SET NOT NULL;
ALTER TABLE order_coordination ALTER COLUMN factory_id SET NOT NULL;

-- Indexes behind the member policies and the backend's tenant filters.
CREATE INDEX IF NOT EXISTS idx_suppliers_factory ON suppliers (factory_id);
CREATE INDEX IF NOT EXISTS idx_vendor_history_factory ON vendor_history (factory_id);
CREATE INDEX IF NOT EXISTS idx_production_lines_factory ON production_lines (factory_id);
CREATE INDEX IF NOT EXISTS idx_orders_factory ON orders (factory_id);
CREATE INDEX IF NOT EXISTS idx_disruption_events_factory ON disruption_events (factory_id);
CREATE INDEX IF NOT EXISTS idx_agent_logs_factory ON agent_logs (factory_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_factory ON purchase_orders (factory_id);
CREATE INDEX IF NOT EXISTS idx_sourcing_rfqs_factory ON sourcing_rfqs (factory_id);
CREATE INDEX IF NOT EXISTS idx_inbound_shipments_factory ON inbound_shipments (factory_id);
CREATE INDEX IF NOT EXISTS idx_order_lines_factory ON order_lines (factory_id);
CREATE INDEX IF NOT EXISTS idx_delivery_outcomes_factory ON delivery_outcomes (factory_id);
CREATE INDEX IF NOT EXISTS idx_execution_receipts_factory ON execution_receipts (factory_id);
CREATE INDEX IF NOT EXISTS idx_sourcing_sessions_factory ON sourcing_sessions (factory_id);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_factory ON analysis_runs (factory_id);

-- 2d. RLS on every table (idempotent).
ALTER TABLE factories ENABLE ROW LEVEL SECURITY;
ALTER TABLE factory_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE production_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE disruption_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE sourcing_rfqs ENABLE ROW LEVEL SECURITY;
ALTER TABLE scenarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_levels ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_shipments ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE sourcing_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_coordination ENABLE ROW LEVEL SECURITY;

-- 2e. Drop the old public-read policies (001-007 granted anon + authenticated USING (true)).
DROP POLICY IF EXISTS factories_read ON factories;
DROP POLICY IF EXISTS suppliers_read ON suppliers;
DROP POLICY IF EXISTS vendor_history_read ON vendor_history;
DROP POLICY IF EXISTS production_lines_read ON production_lines;
DROP POLICY IF EXISTS orders_read ON orders;
DROP POLICY IF EXISTS disruption_events_read ON disruption_events;
DROP POLICY IF EXISTS agent_logs_read ON agent_logs;
DROP POLICY IF EXISTS purchase_orders_read ON purchase_orders;
DROP POLICY IF EXISTS sourcing_rfqs_read ON sourcing_rfqs;
DROP POLICY IF EXISTS scenarios_read ON scenarios;
DROP POLICY IF EXISTS items_read ON items;
DROP POLICY IF EXISTS stock_levels_read ON stock_levels;
DROP POLICY IF EXISTS inbound_shipments_read ON inbound_shipments;
DROP POLICY IF EXISTS order_lines_read ON order_lines;
DROP POLICY IF EXISTS delivery_outcomes_read ON delivery_outcomes;
-- Belt and braces: any other public-schema policy still applying to the anon role, directly or
-- through PUBLIC (a policy created without a TO clause), is dropped too (e.g. one added by hand in
-- the dashboard). After this, anon has no policy anywhere in the public schema.
DO $$
DECLARE pol RECORD;
BEGIN
    FOR pol IN SELECT policyname, schemaname, tablename FROM pg_policies
                WHERE schemaname = 'public' AND ('anon' = ANY (roles) OR 'public' = ANY (roles))
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I.%I', pol.policyname, pol.schemaname, pol.tablename);
    END LOOP;
END
$$;

-- 2f. Members read their own factories' rows. Reads only: there are no INSERT/UPDATE/DELETE
--     policies, all writes go through the backend with the service role. RLS also filters what
--     Realtime (postgres_changes) delivers, so subscriptions keep working for signed-in members.
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
DROP POLICY IF EXISTS sourcing_rfqs_member_read ON sourcing_rfqs;
CREATE POLICY sourcing_rfqs_member_read ON sourcing_rfqs
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
-- Service-only tables (analysis_runs, sourcing_sessions, execution_receipts, webhook_events,
-- schema_migrations, order_coordination) keep RLS on with no policy at all.

-- 2g. Table privileges: the browser roles never write; anon reads nothing; service-only tables
--     are closed to both browser roles. (service_role bypasses RLS and keeps its grants.)
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
REVOKE ALL ON sourcing_rfqs FROM anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON sourcing_rfqs FROM authenticated;
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
REVOKE ALL ON analysis_runs FROM anon, authenticated;
REVOKE ALL ON sourcing_sessions FROM anon, authenticated;
REVOKE ALL ON execution_receipts FROM anon, authenticated;
REVOKE ALL ON webhook_events FROM anon, authenticated;
REVOKE ALL ON schema_migrations FROM anon, authenticated;
REVOKE ALL ON order_coordination FROM anon, authenticated;

-- Privileges that bypass or sidestep RLS (TRUNCATE ignores it; REFERENCES/TRIGGER/MAINTAIN are
-- never needed by the browser) are revoked from both browser roles on every tenant table.
REVOKE TRUNCATE, REFERENCES, TRIGGER ON factories FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON factory_members FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON suppliers FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON vendor_history FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON production_lines FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON orders FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON disruption_events FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON agent_logs FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON purchase_orders FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON sourcing_rfqs FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON scenarios FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON items FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON stock_levels FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON inbound_shipments FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON order_lines FROM anon, authenticated;
REVOKE TRUNCATE, REFERENCES, TRIGGER ON delivery_outcomes FROM anon, authenticated;
DO $$
DECLARE t TEXT;
BEGIN
    IF current_setting('server_version_num')::INT >= 170000 THEN   -- MAINTAIN exists from PostgreSQL 17
        FOREACH t IN ARRAY ARRAY['factories', 'factory_members', 'suppliers', 'vendor_history', 'production_lines', 'orders', 'disruption_events', 'agent_logs', 'purchase_orders', 'sourcing_rfqs', 'scenarios', 'items', 'stock_levels', 'inbound_shipments', 'order_lines', 'delivery_outcomes']
        LOOP
            EXECUTE format('REVOKE MAINTAIN ON public.%I FROM anon, authenticated', t);
        END LOOP;
    END IF;
END
$$;

-- 2h. execute_plan_tx stores factory_id (same 9-argument signature as 007). The factory comes
--     from p_po (falling back to p_receipt); the order, supplier and line updates only touch that
--     factory's rows, so a plan can never move another tenant's data. The receipt insert is still
--     first: a duplicate root_run_id raises unique_violation before anything else is written.
CREATE OR REPLACE FUNCTION execute_plan_tx(
    p_po                 JSONB,
    p_order_id           TEXT,
    p_order_status       TEXT,
    p_supplier_updates   JSONB,
    p_overtime_line_ids  TEXT[],
    p_agent_log          JSONB,
    p_root_run_id        TEXT,
    p_receipt            JSONB,
    p_outcomes           JSONB DEFAULT '[]'::jsonb
) RETURNS JSONB
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_factory TEXT := COALESCE(p_po->>'factory_id', p_receipt->>'factory_id');
    po_rec   purchase_orders;
    upd      JSONB;
    log_item JSONB;
    log_rec  agent_logs;
    outcome  JSONB;
BEGIN
    -- 1. Idempotency guard: duplicate root_run_id -> unique_violation, nothing else written.
    --    (A NULL factory violates execution_receipts.factory_id NOT NULL: nothing is written.)
    INSERT INTO execution_receipts (root_run_id, run_id, playbook_id, factory_id, payload)
    VALUES (
        p_root_run_id,
        COALESCE(p_receipt->>'run_id', p_root_run_id),
        COALESCE(p_receipt->>'playbook_id', ''),
        v_factory,
        p_receipt
    );

    -- 2. Purchase order (see 004: every column comes from p_po; factory_id is the executing factory).
    po_rec := jsonb_populate_record(NULL::purchase_orders, p_po);
    INSERT INTO purchase_orders (
        po_number, playbook_id, order_id, vendor_allocations_json, overtime_hours,
        total_cost_inr, net_sla_saved_inr, confidence_pct, tally_xml_payload,
        shift_broadcast_msg, client_sla_notice, status, approved_by, run_id, factory_id
    ) VALUES (
        po_rec.po_number, po_rec.playbook_id, po_rec.order_id, po_rec.vendor_allocations_json,
        po_rec.overtime_hours, po_rec.total_cost_inr, po_rec.net_sla_saved_inr,
        po_rec.confidence_pct, po_rec.tally_xml_payload, po_rec.shift_broadcast_msg,
        po_rec.client_sla_notice, po_rec.status, po_rec.approved_by, po_rec.run_id, v_factory
    );

    -- 3. Order status (only the executing factory's order).
    UPDATE orders SET status = p_order_status, updated_at = NOW()
     WHERE order_id = p_order_id AND factory_id = v_factory;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'order % not found', p_order_id;  -- rolls back the receipt and PO too
    END IF;

    -- 4. Suppliers: [{supplier_id, inbound_qty}] -> PO_DRAFTED.
    FOR upd IN SELECT * FROM jsonb_array_elements(COALESCE(p_supplier_updates, '[]'::jsonb))
    LOOP
        UPDATE suppliers
           SET status = 'PO_DRAFTED',
               inbound_qty = (upd->>'inbound_qty')::INTEGER,
               updated_at = NOW()
         WHERE id = upd->>'supplier_id' AND factory_id = v_factory;
    END LOOP;

    -- 5. Overtime lines.
    UPDATE production_lines
       SET status = 'OVERTIME_SCHEDULED', updated_at = NOW()
     WHERE line_id = ANY (COALESCE(p_overtime_line_ids, ARRAY[]::TEXT[]))
       AND factory_id = v_factory;

    -- 6. Agent log rows (id is SERIAL: omitted so its default applies); always the executing factory's.
    FOR log_item IN SELECT * FROM jsonb_array_elements(
        CASE jsonb_typeof(p_agent_log)
            WHEN 'object' THEN jsonb_build_array(p_agent_log)
            WHEN 'array'  THEN p_agent_log
            ELSE '[]'::jsonb
        END)
    LOOP
        log_rec := jsonb_populate_record(NULL::agent_logs, log_item);
        INSERT INTO agent_logs (
            run_id, step_order, agent_name, agent_role, badge_color,
            tool_called, tool_output_summary, message, created_at, factory_id
        ) VALUES (
            log_rec.run_id, log_rec.step_order, log_rec.agent_name, log_rec.agent_role,
            log_rec.badge_color, log_rec.tool_called, log_rec.tool_output_summary,
            log_rec.message, COALESCE(log_rec.created_at, NOW()), v_factory   -- payload factory_id ignored
        );
    END LOOP;

    -- 7. Pending delivery outcomes: [{supplier_id, po_number, units, promised_at}] of the executing factory.
    FOR outcome IN SELECT * FROM jsonb_array_elements(COALESCE(p_outcomes, '[]'::jsonb))
    LOOP
        INSERT INTO delivery_outcomes (factory_id, supplier_id, po_number, units, promised_at, status)
        VALUES (
            v_factory, outcome->>'supplier_id', outcome->>'po_number',   -- payload factory_id ignored
            (outcome->>'units')::INTEGER, (outcome->>'promised_at')::TIMESTAMPTZ, 'PENDING'
        );
    END LOOP;

    RETURN p_receipt;
END;
$$;

REVOKE EXECUTE ON FUNCTION execute_plan_tx(JSONB, TEXT, TEXT, JSONB, TEXT[], JSONB, TEXT, JSONB, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION execute_plan_tx(JSONB, TEXT, TEXT, JSONB, TEXT[], JSONB, TEXT, JSONB, JSONB)
    TO service_role;

-- ============================================================================
-- Part 3 (Task 5): chat identities. A WhatsApp number / Telegram chat is linked to a Supabase
-- user and one factory with a one-time code (`/link <code>`); approvals from a chat need that
-- user's owner/approver role in the RUN's factory. Both tables are service-only: RLS on, no
-- policy at all, no privileges for the browser roles. Codes are stored as SHA-256 hashes.
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

ALTER TABLE user_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE link_codes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON user_channels FROM anon, authenticated;
REVOKE ALL ON link_codes FROM anon, authenticated;

-- ============================================================================
-- Part 4 (Task 6): Telegram contacts. Plain columns on tables that already have member-only
-- RLS and no write grants for browser roles; nothing here opens access.
--   suppliers.telegram_chat_id : where a vendor receives RFQs when SOURCING_MODE=telegram
--   orders.client_contact      : "<channel>:<address>" the Client Agent messages (telegram/whatsapp)
-- Set both with `python -m app.admin set-vendor-contact` / `set-client-contact`.
-- ============================================================================
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS telegram_chat_id TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_contact TEXT;

-- ----------------------------------------------------------------------------
-- >>> Later Round B tasks (Task 3 onward) APPEND their parts HERE, above the version insert. <<<
-- New tables: ENABLE ROW LEVEL SECURITY, give them a factory_id (NOT NULL) and either a
-- `<t>_member_read` policy (TO authenticated, never anon, never USING (true)) or no policy at all
-- (service-only), and REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER from anon and
-- authenticated (REVOKE ALL for service-only tables). Add the table to the RLS check below.
-- ----------------------------------------------------------------------------

-- Final RLS check (keep it just above the version insert): refuse to record level 8 if any
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
       AND c.relname = ANY (ARRAY['factories', 'factory_members', 'suppliers', 'vendor_history', 'production_lines', 'orders', 'disruption_events', 'agent_logs', 'purchase_orders', 'sourcing_rfqs', 'scenarios', 'items', 'stock_levels', 'inbound_shipments', 'order_lines', 'delivery_outcomes', 'analysis_runs', 'sourcing_sessions', 'execution_receipts', 'webhook_events', 'schema_migrations', 'order_coordination', 'user_channels', 'link_codes']);
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'RLS check failed: row level security disabled on: %', bad;
    END IF;
END
$$;

-- Keep this the LAST statement of the file: version 8 is recorded only once every part above
-- has been applied.
INSERT INTO schema_migrations (version) VALUES (8) ON CONFLICT DO NOTHING;
