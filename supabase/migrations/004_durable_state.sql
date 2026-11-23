-- ============================================================================
-- CascadeZero — Phase 2: durable state (runs, sourcing sessions, receipts, webhook dedup)
-- Apply after 003_factory_model.sql. Safe to re-run below level 8 (refuses to run once 008 is applied).
-- All tables are service-role only: RLS enabled, NO anon/authenticated policies,
-- and none are added to the realtime publication.
-- ============================================================================

-- Level-8 guard: once 008 (member-only RLS) is applied, re-running this file would reopen
-- anon / USING (true) read policies, so it refuses to run at level 8 or above.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'schema_migrations') THEN
        IF EXISTS (SELECT 1 FROM schema_migrations WHERE version >= 8) THEN
            RAISE EXCEPTION 'database is at level 8+; re-running 004 would reopen anon/USING(true) policies — not allowed';
        END IF;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id         TEXT PRIMARY KEY,
    parent_run_id  TEXT,
    factory_id     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload        JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_created_at ON analysis_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS sourcing_sessions (
    run_id      TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    version     INT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload     JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_receipts (
    root_run_id  TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    playbook_id  TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload      JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
    message_id   TEXT PRIMARY KEY,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE analysis_runs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE sourcing_sessions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_events     ENABLE ROW LEVEL SECURITY;
ALTER TABLE schema_migrations  ENABLE ROW LEVEL SECURITY;

-- Prerequisite guard: this migration claims levels 1-3 as applied, so refuse to run unless
-- 001 (purchase_orders.run_id / approved_by), 002 (suppliers.whatsapp_number) and
-- 003 (factories table) are really present. Re-run safe (read-only check).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'purchase_orders' AND column_name = 'run_id')
       OR NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'purchase_orders' AND column_name = 'approved_by') THEN
        RAISE EXCEPTION 'Migration 001 not applied (purchase_orders.run_id / approved_by missing); apply 001-003 before 004';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'suppliers' AND column_name = 'whatsapp_number') THEN
        RAISE EXCEPTION 'Migration 002 not applied (suppliers.whatsapp_number missing); apply 001-003 before 004';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'factories') THEN
        RAISE EXCEPTION 'Migration 003 not applied (table factories missing); apply 001-003 before 004';
    END IF;
END
$$;

INSERT INTO schema_migrations (version) VALUES (1), (2), (3), (4) ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------------------
-- execute_plan_tx: the atomic execution path. One function call = one transaction;
-- any exception rolls back every write. p_agent_log may be a single agent_logs row object
-- or an array of row objects (NULL/other -> no rows). The receipt insert comes first, so a
-- duplicate root_run_id raises unique_violation before anything else is written.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION execute_plan_tx(
    p_po                 JSONB,
    p_order_id           TEXT,
    p_order_status       TEXT,
    p_supplier_updates   JSONB,
    p_overtime_line_ids  TEXT[],
    p_agent_log          JSONB,
    p_root_run_id        TEXT,
    p_receipt            JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    po_rec   purchase_orders;
    upd      JSONB;
    log_item JSONB;
    log_rec  agent_logs;
BEGIN
    -- 1. Idempotency guard: duplicate root_run_id -> unique_violation, nothing else written.
    INSERT INTO execution_receipts (root_run_id, run_id, playbook_id, payload)
    VALUES (
        p_root_run_id,
        COALESCE(p_receipt->>'run_id', p_root_run_id),
        COALESCE(p_receipt->>'playbook_id', ''),
        p_receipt
    );

    -- 2. Purchase order. Every column is read from p_po: a key missing from it becomes NULL and
    --    violates NOT NULL (the caller always sends them all); only created_at falls back to its default.
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

    RETURN p_receipt;
END;
$$;

REVOKE EXECUTE ON FUNCTION execute_plan_tx(JSONB, TEXT, TEXT, JSONB, TEXT[], JSONB, TEXT, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION execute_plan_tx(JSONB, TEXT, TEXT, JSONB, TEXT[], JSONB, TEXT, JSONB)
    TO service_role;
