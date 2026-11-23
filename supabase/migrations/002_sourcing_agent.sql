-- ============================================================================
-- CascadeZero — Sourcing Agent: vendor contact numbers + enquiry (RFQ) audit log
-- Apply after 001_rls_and_audit.sql. Safe to re-run below level 8 (refuses to run once 008 is applied).
-- ============================================================================

-- Level-8 guard: once 008 (member-only RLS) is applied, re-running this file would reopen
-- anon / USING (true) read policies, so it refuses to run at level 8 or above.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'schema_migrations') THEN
        IF EXISTS (SELECT 1 FROM schema_migrations WHERE version >= 8) THEN
            RAISE EXCEPTION 'database is at level 8+; re-running 002 would reopen anon/USING(true) policies — not allowed';
        END IF;
    END IF;
END
$$;

-- WhatsApp number per supplier (country code + digits, e.g. 919800000000).
-- Used only when SOURCING_MODE=whatsapp. Note: the Meta Cloud API only allows free-form
-- business-initiated messages inside a 24h customer-service window; outside it an approved
-- message template is required, otherwise the send fails and the agent drops that vendor.
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS whatsapp_number TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS sourcing_rfqs (
    id                      TEXT PRIMARY KEY,
    run_id                  TEXT NOT NULL,
    round                   INTEGER NOT NULL DEFAULT 1,
    supplier_id             TEXT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    supplier_name           TEXT NOT NULL DEFAULT '',
    units_requested         INTEGER NOT NULL DEFAULT 0,
    expected_unit_price_inr INTEGER NOT NULL DEFAULT 0,
    needed_within_hours     FLOAT NOT NULL DEFAULT 0,
    channel                 TEXT NOT NULL DEFAULT 'simulated',
    status                  TEXT NOT NULL DEFAULT 'SENT',  -- SENT|CONFIRMED|PARTIAL|DECLINED|NO_REPLY|SEND_FAILED
    message                 TEXT NOT NULL DEFAULT '',
    offered_units           INTEGER,
    offered_unit_price_inr  INTEGER,
    offered_eta_hours       FLOAT,
    reply_text              TEXT NOT NULL DEFAULT '',
    parsed_by               TEXT NOT NULL DEFAULT '',
    reply_source            TEXT NOT NULL DEFAULT '',
    sent_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    replied_at              TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS sourcing_rfqs_run_idx ON sourcing_rfqs (run_id);

ALTER TABLE sourcing_rfqs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sourcing_rfqs_read ON sourcing_rfqs;
CREATE POLICY sourcing_rfqs_read ON sourcing_rfqs FOR SELECT TO anon, authenticated USING (true);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication_tables WHERE pubname = 'supabase_realtime' AND tablename = 'sourcing_rfqs') THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE sourcing_rfqs;
    END IF;
END $$;
