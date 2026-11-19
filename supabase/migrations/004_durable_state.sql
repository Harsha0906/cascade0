-- ============================================================================
-- CascadeZero — Phase 2: durable state (runs, sourcing sessions, receipts, webhook dedup)
-- Apply after 003_factory_model.sql. Safe to re-run.
-- All tables are service-role only: RLS enabled, NO anon/authenticated policies,
-- and none are added to the realtime publication.
-- ============================================================================

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

INSERT INTO schema_migrations (version) VALUES (1), (2), (3), (4) ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------------------
-- execute_plan_tx: the atomic execution path. One function call = one transaction;
-- any exception rolls back every write. The receipt insert comes first, so a
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

    -- 2. Purchase order (explicit column list so table defaults are never overridden).
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
    FOR log_item IN SELECT * FROM jsonb_array_elements(COALESCE(p_agent_log, '[]'::jsonb))
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
