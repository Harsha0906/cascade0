"""Round B Task 3: factory_id on every tenant table and member-only Row-Level Security.

Static checks on the SQL text of migration 008 and schema.sql (the live RLS behaviour is verified
by the controller with role-switching after applying 008), plus offline checks that every insert
carries factory_id and that writes keyed by global ids can never overwrite another factory's row.
"""

import re
import unittest
from pathlib import Path
from unittest import mock

from tests import _offline_env  # noqa: F401  (must precede app imports)
from tests._offline_env import dev_client
from tests.factories import seed_second_factory

from app import db, main

ROOT = Path(__file__).resolve().parents[2] / "supabase"
MIGRATIONS = ROOT / "migrations"
APEX = "apex-volt-blr2"
TP = "test-plant"

# Tables a factory member may read (filtered by factory_id); factories is read by its id.
TENANT_TABLES = (
    "suppliers", "vendor_history", "production_lines", "orders", "disruption_events",
    "agent_logs", "purchase_orders", "sourcing_rfqs", "scenarios", "items", "stock_levels",
    "inbound_shipments", "order_lines", "delivery_outcomes",
)
# Written and read only by the backend (service role): RLS on, no policy at all.
SERVICE_ONLY_TABLES = (
    "analysis_runs", "sourcing_sessions", "execution_receipts", "webhook_events",
    "schema_migrations", "order_coordination",
)
# The brief's new factory_id columns (webhook_events stays nullable).
NEW_FACTORY_COLUMNS = (
    "purchase_orders", "agent_logs", "execution_receipts", "sourcing_rfqs", "sourcing_sessions",
    "vendor_history", "order_lines",
)
NOT_NULL_FACTORY_TABLES = tuple(t for t in TENANT_TABLES) + (
    "analysis_runs", "sourcing_sessions", "execution_receipts", "order_coordination",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _part2(sql: str) -> str:
    """The Task 3 part of 008: everything after the delivery_outcomes.recorded_by column (Task 1)."""
    return sql[sql.index("ADD COLUMN IF NOT EXISTS recorded_by"):]


def _policies(sql: str) -> list[tuple[str, str, str]]:
    """(name, table, rest-of-statement) for every CREATE POLICY statement."""
    return [(m.group(1), m.group(2), m.group(3)) for m in
            re.finditer(r"CREATE POLICY\s+(\w+)\s+ON\s+(\w+)\s+([^;]*);", _strip_comments(sql), re.I)]


def _member_policy(table: str) -> str:
    column = "id" if table == "factories" else "factory_id"
    return (rf"CREATE POLICY {table}_member_read ON {table}\s+FOR SELECT TO authenticated\s+"
            rf"USING \({column} IN \(SELECT factory_id FROM factory_members "
            rf"WHERE user_id = \(SELECT auth\.uid\(\)\)\)\);")


def _anon_policies_before_008() -> set[tuple[str, str]]:
    """(policy, table) granting anon in 001-007, including 001's format() loop."""
    found: set[tuple[str, str]] = set()
    for path in sorted(MIGRATIONS.glob("00[1-7]_*.sql")):
        sql = _strip_comments(_read(path))
        for name, table, rest in _policies(sql):
            if re.search(r"\bTO\b[^U]*\banon\b", rest, re.I):
                found.add((name, table))
        loop = re.search(r"FOREACH t IN ARRAY ARRAY\[([^\]]+)\].*?TO anon", sql, re.S)
        if loop:
            for table in re.findall(r"'(\w+)'", loop.group(1)):
                found.add((f"{table}_read", table))
    return found


class Migration008RlsTests(unittest.TestCase):
    sql = _read(MIGRATIONS / "008_identity.sql")

    def test_no_policy_grants_anon(self):
        for name, table, rest in _policies(self.sql):
            with self.subTest(policy=name):
                self.assertNotRegex(rest, r"(?i)\banon\b")
        self.assertNotRegex(_strip_comments(self.sql), r"(?i)\bTO\s+anon\b")

    def test_every_anon_read_policy_of_001_to_007_is_dropped(self):
        before = _anon_policies_before_008()
        self.assertGreaterEqual(len(before), 15)  # 7 from 001's loop + 8 named ones
        for name, table in sorted(before):
            with self.subTest(policy=name):
                self.assertRegex(self.sql, rf"DROP POLICY IF EXISTS {name} ON {table};")

    def test_every_tenant_table_has_a_member_policy(self):
        for table in TENANT_TABLES + ("factories",):
            with self.subTest(table=table):
                self.assertRegex(self.sql, _member_policy(table))

    def test_service_only_tables_have_no_policy(self):
        tables = {t for _, t, _ in _policies(self.sql)}
        for table in SERVICE_ONLY_TABLES:
            with self.subTest(table=table):
                self.assertNotIn(table, tables)
                self.assertRegex(self.sql, rf"REVOKE ALL ON {table} FROM anon, authenticated;")

    def test_policies_use_initplan_auth_uid(self):
        body = _strip_comments(self.sql)
        bare = re.findall(r"(?<!SELECT )auth\.uid\(\)", body)
        self.assertEqual(bare, [], "use (SELECT auth.uid()) so it is evaluated once per statement")

    def test_writes_revoked_from_browser_roles(self):
        for table in TENANT_TABLES + ("factories",):
            with self.subTest(table=table):
                self.assertRegex(self.sql, rf"REVOKE ALL ON {table} FROM anon;")
                self.assertRegex(self.sql, rf"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {table} FROM authenticated;")

    def test_rls_enabled_on_every_table(self):
        for table in TENANT_TABLES + SERVICE_ONLY_TABLES + ("factories", "factory_members"):
            with self.subTest(table=table):
                self.assertRegex(self.sql, rf"ALTER TABLE {table}\s+ENABLE ROW LEVEL SECURITY;")

    def test_factory_id_added_backfilled_then_not_null_before_policies(self):
        part = _part2(self.sql)
        first_policy = part.index("CREATE POLICY")
        for table in NEW_FACTORY_COLUMNS + ("webhook_events",):
            with self.subTest(table=table):
                self.assertRegex(part, rf"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS factory_id TEXT;")
        for table in NOT_NULL_FACTORY_TABLES:
            with self.subTest(table=table):
                backfill = re.search(
                    rf"UPDATE {table} SET factory_id = 'apex-volt-blr2' WHERE factory_id IS NULL;", part)
                not_null = re.search(rf"ALTER TABLE {table} ALTER COLUMN factory_id SET NOT NULL;", part)
                self.assertIsNotNone(backfill)
                self.assertIsNotNone(not_null)
                self.assertLess(backfill.start(), not_null.start())
                self.assertLess(not_null.start(), first_policy)
        self.assertNotRegex(part, r"ALTER TABLE webhook_events ALTER COLUMN factory_id SET NOT NULL")

    def test_factory_members_foreign_keys(self):
        self.assertRegex(self.sql, r"FOREIGN KEY \(factory_id\) REFERENCES factories \(id\) ON DELETE CASCADE")
        self.assertRegex(self.sql, r"FOREIGN KEY \(user_id\) REFERENCES auth\.users \(id\) ON DELETE CASCADE")

    def test_execute_plan_tx_stores_factory_id(self):
        part = _part2(self.sql)
        fn = part[part.index("CREATE OR REPLACE FUNCTION execute_plan_tx("):]
        fn = fn[:fn.index("$$;")]
        self.assertIn("p_outcomes           JSONB DEFAULT '[]'::jsonb", fn)
        receipt = fn.index("INSERT INTO execution_receipts (root_run_id, run_id, playbook_id, factory_id, payload)")
        po = fn.index("INSERT INTO purchase_orders (")
        self.assertLess(receipt, po, "receipt-first idempotency")
        self.assertRegex(fn, r"v_factory\s+TEXT := COALESCE\(p_po->>'factory_id', p_receipt->>'factory_id'\);")
        self.assertRegex(fn, r"shift_broadcast_msg, client_sla_notice, status, approved_by, run_id, factory_id\s*\)")
        self.assertRegex(fn, r"tool_called, tool_output_summary, message, created_at, factory_id\s*\)")
        # The order, supplier and line updates only touch the executing factory's rows.
        self.assertRegex(fn, r"WHERE order_id = p_order_id AND factory_id = v_factory;")
        self.assertRegex(fn, r"WHERE id = upd->>'supplier_id' AND factory_id = v_factory;")
        self.assertRegex(fn, r"AND factory_id = v_factory;\s*\n\s*-- 6\.")
        sig = r"execute_plan_tx\(JSONB, TEXT, TEXT, JSONB, TEXT\[\], JSONB, TEXT, JSONB, JSONB\)"
        self.assertRegex(part, rf"REVOKE EXECUTE ON FUNCTION {sig}\s+FROM PUBLIC, anon, authenticated;")
        self.assertRegex(part, rf"GRANT EXECUTE ON FUNCTION {sig}\s+TO service_role;")

    def test_guard_requires_7_and_version_8_is_last(self):
        self.assertIn("SELECT 1 FROM schema_migrations WHERE version = 7", self.sql)
        self.assertEqual(self.sql.strip().splitlines()[-1],
                         "INSERT INTO schema_migrations (version) VALUES (8) ON CONFLICT DO NOTHING;")
        self.assertLess(self.sql.index("CREATE POLICY suppliers_member_read"), self.sql.index("APPEND their parts HERE"))
        self.assertEqual(sorted(p.name for p in MIGRATIONS.glob("*.sql"))[-1], "009_setup.sql")


    def test_log_rows_and_outcomes_always_get_the_executing_factory(self):
        fn = self.sql[self.sql.index("CREATE OR REPLACE FUNCTION execute_plan_tx("):]
        fn = _strip_comments(fn[:fn.index("$$;")])
        self.assertNotIn("log_rec.factory_id", fn)
        self.assertNotIn("outcome->>'factory_id'", fn)
        self.assertRegex(fn, r"COALESCE\(log_rec\.created_at, NOW\(\)\), v_factory\s*\)")
        self.assertRegex(fn, r"VALUES \(\s*v_factory, outcome->>'supplier_id'")

    def test_owner_inference_precedes_guarded_fallback(self):
        part = _part2(self.sql)
        fallback = part.index("UPDATE suppliers SET factory_id = 'apex-volt-blr2'")
        guard = part.index("IF (SELECT count(*) FROM factories) > 1 THEN")
        for pattern in (
            r"UPDATE purchase_orders po SET factory_id = r\.factory_id\s+FROM analysis_runs r WHERE po\.factory_id IS NULL AND r\.run_id = po\.run_id;",
            r"UPDATE purchase_orders po SET factory_id = o\.factory_id\s+FROM orders o",
            r"UPDATE sourcing_rfqs sr SET factory_id = s\.factory_id\s+FROM suppliers s",
            r"UPDATE agent_logs al SET factory_id = r\.factory_id\s+FROM analysis_runs r",
            r"UPDATE execution_receipts er SET factory_id = r\.factory_id\s+FROM analysis_runs r WHERE er\.factory_id IS NULL AND r\.run_id = er\.run_id;",
            r"UPDATE delivery_outcomes d SET factory_id = s\.factory_id\s+FROM suppliers s",
        ):
            with self.subTest(pattern=pattern):
                m = re.search(pattern, part)
                self.assertIsNotNone(m)
                self.assertLess(m.start(), guard)
        self.assertLess(guard, fallback)
        block = part[guard:fallback]
        self.assertIn("RAISE EXCEPTION 'table % has rows with no factory_id", block)
        for table in NOT_NULL_FACTORY_TABLES:
            if table != "factories":
                self.assertIn(f"'{table}'", block)

    def test_tighter_grants_and_qualified_sweep(self):
        for table in TENANT_TABLES + ("factories", "factory_members"):
            with self.subTest(table=table):
                self.assertRegex(self.sql, rf"REVOKE TRUNCATE, REFERENCES, TRIGGER ON {table} FROM anon, authenticated;")
        self.assertIn("current_setting('server_version_num')::INT >= 170000", self.sql)
        self.assertIn("REVOKE MAINTAIN ON public.%I FROM anon, authenticated", self.sql)
        self.assertIn("format('DROP POLICY IF EXISTS %I ON %I.%I', pol.policyname, pol.schemaname, pol.tablename)",
                      self.sql)

    def test_fk_check_is_bound_to_the_table(self):
        self.assertEqual(self.sql.count("WHERE conrelid = 'public.factory_members'::regclass"), 2)

    def test_final_rls_check_just_before_version_insert(self):
        body = self.sql
        check = body.index("RAISE EXCEPTION 'RLS check failed: open policies remain")
        self.assertLess(body.index("APPEND their parts HERE"), check)
        self.assertLess(check, body.index("INSERT INTO schema_migrations (version) VALUES (8)"))
        self.assertIn("qual = 'true' OR with_check = 'true' OR 'anon' = ANY (roles) OR 'public' = ANY (roles)", body)
        self.assertIn("NOT c.relrowsecurity", body)
        for table in TENANT_TABLES + SERVICE_ONLY_TABLES + ("factories", "factory_members"):
            self.assertIn(f"'{table}'", body[check:])
        self.assertIn("New tables: ENABLE ROW LEVEL SECURITY", body)



class OldMigrationGuardTests(unittest.TestCase):
    """001-007 refuse to run at level 8+: re-running them would reopen anon/USING(true) policies."""

    def test_each_old_migration_refuses_level_8(self):
        paths = sorted(MIGRATIONS.glob("00[1-7]_*.sql"))
        self.assertEqual(len(paths), 7)
        for path in paths:
            n = path.name[:3]
            sql = _read(path)
            with self.subTest(migration=n):
                guard = sql.index("SELECT 1 FROM schema_migrations WHERE version >= 8")
                self.assertIn(f"RAISE EXCEPTION 'database is at level 8+; re-running {n} would reopen "
                              f"anon/USING(true) policies", sql)
                # The guard is the file's first statement.
                first_stmt = re.search(r"^(?!--)(?!\s*$)", sql, re.M)
                self.assertTrue(sql[first_stmt.start():].startswith("DO $$"))
                self.assertLess(guard, sql.index("END\n$$;", first_stmt.start()))
                header = sql[:first_stmt.start()]
                self.assertRegex(header, r"(below level 8|Refuses to run once 008)")


class SchemaSqlTests(unittest.TestCase):
    """schema.sql + migrations 001-008 converge to the same end state; schema.sql shows it."""

    sql = _read(ROOT / "schema.sql")

    def test_header_lists_008(self):
        self.assertIn("001, 002, 003, 004, 005, 006, 007, 008", self.sql)

    def test_no_policy_grants_anon(self):
        for name, _table, rest in _policies(self.sql):
            with self.subTest(policy=name):
                self.assertNotRegex(rest, r"(?i)\banon\b")

    # Created by migrations 002/004 (not by schema.sql); 008 gives them factory_id and policies.
    FROM_MIGRATIONS = ("sourcing_rfqs", "analysis_runs", "sourcing_sessions", "execution_receipts",
                       "webhook_events", "schema_migrations")

    def test_member_policies_and_factory_members(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS factory_members", self.sql)
        self.assertRegex(self.sql, r"CREATE POLICY factory_members_self_read ON factory_members")
        self.assertRegex(self.sql, r"factory_id  TEXT NOT NULL REFERENCES factories \(id\) ON DELETE CASCADE")
        for table in tuple(t for t in TENANT_TABLES if t not in self.FROM_MIGRATIONS) + ("factories",):
            with self.subTest(table=table):
                self.assertRegex(self.sql, _member_policy(table))
        policy_tables = {t for _, t, _ in _policies(self.sql)}
        for table in SERVICE_ONLY_TABLES:
            self.assertNotIn(table, policy_tables)

    def test_every_tenant_table_declares_factory_id(self):
        body = _strip_comments(self.sql)
        for table in (t for t in NOT_NULL_FACTORY_TABLES if t not in self.FROM_MIGRATIONS):
            with self.subTest(table=table):
                create = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", body, re.S)
                self.assertIsNotNone(create, table)
                self.assertRegex(create.group(1), r"\bfactory_id\s+TEXT\b")


class InsertsCarryFactoryIdTests(unittest.TestCase):
    def setUp(self):
        db.reset_to_seed()

    def tearDown(self):
        db.reset_to_seed()

    def test_seed_rows_carry_factory_id(self):
        for table in ("vendor_history", "order_lines"):
            rows = db.fetch_all(table)
            self.assertTrue(rows)
            for row in rows:
                with self.subTest(table=table, row=row):
                    self.assertEqual(row.get("factory_id"), APEX)

    def test_sourcing_rows_carry_factory_id(self):
        client = dev_client(main.app)
        run = client.post("/api/v1/simulate-crisis", json={"scenario_id": 1}).json()
        r = client.post("/api/v1/sourcing/start", json={"run_id": run["run_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        rfqs = db.fetch_all("sourcing_rfqs")
        sessions = db.fetch_all("sourcing_sessions")
        self.assertTrue(rfqs)
        self.assertTrue(sessions)
        for row in rfqs + sessions:
            self.assertEqual(row.get("factory_id"), APEX)

    def test_sales_order_lines_import_writes_factory_id(self):
        r = dev_client(main.app).post("/api/v1/ingest/sales-order-lines", json={
            "filename": "lines.csv", "factory_id": APEX,
            "csv_content": "order_id,item_code,qty\nEV-402,CASING,450\n"})
        self.assertEqual(r.status_code, 200, r.text)
        row = next(x for x in db.fetch_all("order_lines") if x["order_id"] == "EV-402")
        self.assertEqual((row["qty"], row["factory_id"]), (450, APEX))

    def test_live_execute_plan_tx_sends_factory_id_in_payloads(self):
        class Rec:
            params = None

            def rpc(self, name, params):
                Rec.params = params
                return type("Q", (), {"execute": lambda s: type("R", (), {"data": params["p_receipt"]})()})()

        with mock.patch("app.db._get_supabase", return_value=Rec()):
            db.execute_plan_tx(po={"po_number": "P", "factory_id": APEX}, order_id="EV-402",
                               order_status="S", supplier_updates=[], overtime_line_ids=[],
                               agent_log={"run_id": "R-live", "factory_id": APEX},
                               root_run_id="R-live", receipt={"run_id": "R-live"})
        self.assertEqual(Rec.params["p_po"]["factory_id"], APEX)
        self.assertEqual(Rec.params["p_agent_log"]["factory_id"], APEX)

    def test_offline_execute_only_touches_the_executing_factory(self):
        seed_second_factory()
        before = db.fetch_by_id("orders", "order_id", "WO-77")
        with self.assertRaises(db.DatabaseError):
            db.execute_plan_tx(po={"po_number": "P-X", "factory_id": APEX}, order_id="WO-77",
                               order_status="HIJACKED", supplier_updates=[], overtime_line_ids=[],
                               agent_log={}, root_run_id="R-X", receipt={"run_id": "R-X"})
        self.assertEqual(db.fetch_by_id("orders", "order_id", "WO-77")["status"], before["status"])
        self.assertIsNone(db.get_receipt("R-X"))


class OwnedUpsertTests(unittest.TestCase):
    """Writes keyed by a global id never overwrite another factory's row (closes the ERP import
    check-then-upsert race and the live reset's seed upsert collisions)."""

    def setUp(self):
        db.reset_to_seed()
        seed_second_factory()

    def tearDown(self):
        db.reset_to_seed()

    def test_offline_conflict_with_foreign_row_writes_nothing(self):
        before = db.fetch_by_id("orders", "order_id", "WO-77")
        with self.assertRaises(db.OwnershipConflict):
            db.upsert_owned("orders", {"order_id": "WO-77", "factory_id": APEX, "client": "Mallory"},
                            ("order_id",))
        self.assertEqual(db.fetch_by_id("orders", "order_id", "WO-77"), before)

    def test_offline_own_row_updates_and_new_row_inserts(self):
        db.upsert_owned("orders", {"order_id": "WO-77", "factory_id": TP, "client": "Renamed"}, ("order_id",))
        self.assertEqual(db.fetch_by_id("orders", "order_id", "WO-77")["client"], "Renamed")
        db.upsert_owned("orders", {"order_id": "NEW-1", "factory_id": TP, "client": "New"}, ("order_id",))
        self.assertEqual(db.fetch_by_id("orders", "order_id", "NEW-1")["factory_id"], TP)

    def test_erp_import_race_never_overwrites_foreign_order(self):
        """The ownership pre-check passes (the order looked new), but the write itself is conditional."""
        before = db.fetch_by_id("orders", "order_id", "WO-77")
        with mock.patch("app.db.get_order", return_value=None):
            r = dev_client(main.app).post("/api/v1/ingest/erp-csv", json={
                "filename": "o.csv", "factory_id": APEX,
                "csv_content": "order_id,client,required_qty,hours_remaining,sla_penalty_inr,"
                               "partial_delay_penalty_inr\nWO-77,Mallory,1,5,1,1\n"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["success"])
        self.assertEqual(r.json()["imported_count"], 0)
        self.assertEqual(db.fetch_by_id("orders", "order_id", "WO-77"), before)

    def test_live_upsert_is_update_filtered_by_factory_then_insert(self):
        fake = _LiveFake(foreign={("orders", "WO-77")})
        with mock.patch("app.db._get_supabase", return_value=fake):
            with self.assertRaises(db.OwnershipConflict):
                db.upsert_owned("orders", {"order_id": "WO-77", "factory_id": APEX, "client": "M"}, ("order_id",))
        ops = [q for q in fake.queries if q.table == "orders"]
        self.assertFalse(any(op == "upsert" for q in ops for op, _ in q.ops), "no blind upsert")
        updates = [q for q in ops if q.ops and q.ops[0][0] == "update"]
        self.assertTrue(updates)
        for q in updates:
            self.assertIn(("eq", ("factory_id", APEX)), q.ops)

    def test_live_reset_never_overwrites_foreign_seed_keys(self):
        fake = _LiveFake(foreign={("suppliers", "SUP-CHN-01"), ("orders", "EV-402")})
        with mock.patch("app.db._get_supabase", return_value=fake):
            db.reset_to_seed(APEX)   # a collision is skipped, not an error
        for q in fake.queries:
            if q.table in ("suppliers", "production_lines", "orders", "order_lines", "inbound_shipments"):
                with self.subTest(table=q.table):
                    self.assertNotIn("upsert", [op for op, _ in q.ops])
                    if q.ops and q.ops[0][0] == "update":
                        self.assertIn(("eq", ("factory_id", APEX)), q.ops)


class _UniqueViolation(Exception):
    code = "23505"


class _LiveQuery:
    def __init__(self, fake, table):
        self.fake, self.table, self.ops = fake, table, []
        fake.queries.append(self)

    def __getattr__(self, name):
        def call(*args, **kwargs):
            if name == "execute":
                return self._execute()
            self.ops.append((name, args))
            return self
        return call

    def _execute(self):
        first = self.ops[0] if self.ops else ("select", ())
        if first[0] == "insert":
            row = first[1][0]
            key = next(iter(row.values())) if self.table != "order_lines" else row.get("order_id")
            if (self.table, key) in self.fake.foreign:
                raise _UniqueViolation('duplicate key value violates unique constraint')
            return type("R", (), {"data": [row]})()
        return type("R", (), {"data": []})()


class _LiveFake:
    """Every update matches nothing; inserting a key in `foreign` raises a unique violation."""

    def __init__(self, foreign=()):
        self.foreign, self.queries = set(foreign), []

    def table(self, name):
        return _LiveQuery(self, name)


if __name__ == "__main__":
    unittest.main()
