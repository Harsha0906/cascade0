-- ============================================================================
-- CascadeZero — Round A: learned vendor reliability (delivery_outcomes) and Client Agent coordination
-- Apply after 006_inventory.sql. Safe to re-run.
-- ============================================================================

-- Prerequisite guard: refuse to run unless migration 006 is really applied.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'schema_migrations')
       OR NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 6) THEN
        RAISE EXCEPTION 'Migration 006 not applied (schema_migrations has no version 6); apply 001-006 before 007';
    END IF;
END
$$;

-- One row per purchase-order line sent to a vendor. PENDING until the delivery is recorded.
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
    UNIQUE (po_number, supplier_id)
);

ALTER TABLE delivery_outcomes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS delivery_outcomes_read ON delivery_outcomes;
CREATE POLICY delivery_outcomes_read ON delivery_outcomes FOR SELECT TO anon, authenticated USING (true);

-- execute_plan_tx gains p_outcomes (pending delivery outcomes written in the same transaction).
-- A function with an added parameter is a DIFFERENT signature: drop the 8-argument one so a
-- PostgREST rpc call with named parameters resolves to exactly one function.
DROP FUNCTION IF EXISTS execute_plan_tx(JSONB, TEXT, TEXT, JSONB, TEXT[], JSONB, TEXT, JSONB);

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
    po_rec   purchase_orders;
    upd      JSONB;
    log_item JSONB;
    log_rec  agent_logs;
    outcome  JSONB;
BEGIN
    -- 1. Idempotency guard: duplicate root_run_id -> unique_violation, nothing else written.
    INSERT INTO execution_receipts (root_run_id, run_id, playbook_id, payload)
    VALUES (
        p_root_run_id,
        COALESCE(p_receipt->>'run_id', p_root_run_id),
        COALESCE(p_receipt->>'playbook_id', ''),
        p_receipt
    );

    -- 2. Purchase order (see 004: every column comes from p_po).
    po_rec := jsonb_populate_record(NULL::purchase_orders, p_po);
    INSERT INTO purchase_orders (
        po_number, playbook_id, order_id, vendor_allocations_json, overtime_hours,
        total_cost_inr, net_sla_saved_inr, confidence_pct, tally_xml_payload,
        shift_broadcast_msg, client_sla_notice, status, approved_by, run_id
    ) VALUES (
        po_rec.po_number, po_rec.playbook_id, po_rec.order_id, po_rec.vendor_allocations_json,
        po_rec.overtime_hours, po_rec.total_cost_inr, po_rec.net_sla_saved_inr,
        po_rec.confidence_pct, po_rec.tally_xml_payload, po_rec.shift_broadcast_msg,
        po_rec.client_sla_notice, po_rec.status, po_rec.approved_by, po_rec.run_id
    );

    -- 3. Order status.
    UPDATE orders SET status = p_order_status, updated_at = NOW() WHERE order_id = p_order_id;
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
         WHERE id = upd->>'supplier_id';
    END LOOP;

    -- 5. Overtime lines.
    UPDATE production_lines
       SET status = 'OVERTIME_SCHEDULED', updated_at = NOW()
     WHERE line_id = ANY (COALESCE(p_overtime_line_ids, ARRAY[]::TEXT[]));

    -- 6. Agent log rows (id is SERIAL: omitted so its default applies).
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
            tool_called, tool_output_summary, message, created_at
        ) VALUES (
            log_rec.run_id, log_rec.step_order, log_rec.agent_name, log_rec.agent_role,
            log_rec.badge_color, log_rec.tool_called, log_rec.tool_output_summary,
            log_rec.message, COALESCE(log_rec.created_at, NOW())
        );
    END LOOP;

    -- 7. Pending delivery outcomes: [{factory_id, supplier_id, po_number, units, promised_at}].
    FOR outcome IN SELECT * FROM jsonb_array_elements(COALESCE(p_outcomes, '[]'::jsonb))
    LOOP
        INSERT INTO delivery_outcomes (factory_id, supplier_id, po_number, units, promised_at, status)
        VALUES (
            outcome->>'factory_id', outcome->>'supplier_id', outcome->>'po_number',
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

INSERT INTO schema_migrations (version) VALUES (7) ON CONFLICT DO NOTHING;
