import json
import unittest
from unittest import mock

from tests import _offline_env  # noqa: F401

from app.agents.graph import run_cascade_pipeline
from app.db import _SEED_SUPPLIERS, fetch_all, get_agent_logs, get_all_production_lines, get_all_suppliers
from app.factory_model import FactoryDataError, FactoryModel, load_factory_model
from tests.factories import small_factory


class FactoryModelTests(unittest.TestCase):
    def test_throughput_gap_sums_listed_lines(self):
        self.assertEqual(small_factory().throughput_gap({"L-A": 50}), 50)  # 10*0.5*10
        self.assertEqual(small_factory().throughput_gap({"L-A": 50, "L-B": 80}), 70)
        self.assertEqual(small_factory().throughput_gap({"L-A": 100}), 0)

    def test_primary_suppliers_roundtrip(self):
        m = load_factory_model()
        self.assertEqual([i for i, _ in m.primary_suppliers], ["SUP-CHN-01"])
        self.assertEqual(FactoryModel.from_dict(json.loads(json.dumps(m.to_dict()))).primary_suppliers,
                         m.primary_suppliers)
        old = m.to_dict()
        del old["primary_suppliers"]
        self.assertEqual(FactoryModel.from_dict(old).primary_suppliers, ())

    def test_factory_model_roundtrip(self):
        m = load_factory_model()
        self.assertEqual(FactoryModel.from_dict(json.loads(json.dumps(m.to_dict()))), m)

    def test_unknown_line_rejected(self):
        with self.assertRaises(FactoryDataError):
            small_factory().throughput_gap({"L-Z": 50})

    def test_overtime_lines_and_expedite(self):
        m = small_factory()
        self.assertEqual([l.line_id for l in m.overtime_lines], ["L-B"])
        self.assertEqual(m.expedite_vendor_id, "V3")

    def test_overrides_replace_and_drop(self):
        m = small_factory().with_vendor_overrides(
            {"V1": {"max_units": 40, "unit_cost": 520}, "V3": {"max_units": 0}})
        self.assertEqual((m.vendor("V1").max_units, m.vendor("V1").unit_cost), (40, 520))
        self.assertIsNone(m.expedite_vendor_id)

    def test_override_for_unknown_vendor_rejected(self):
        with self.assertRaises(FactoryDataError):
            small_factory().with_vendor_overrides({"NOPE": {"max_units": 5}})

    def test_demo_factory_loads_and_matches_previous_constants(self):
        m = load_factory_model()  # offline -> in-memory mirror seed
        p = m.vendor("SUP-PNY-02")
        self.assertEqual((p.max_units, p.unit_cost, p.lead_hours, p.lead_sigma, p.delay_shock_pct,
                          p.delay_shock_range, p.reliability_pct, p.min_lead_hours),
                         (200, 600, 4.0, 0.45, 6.0, (1.0, 2.5), 88.2, 2.0))
        self.assertEqual(m.vendor("SUP-AIR-04").flat_cost, 600_000)
        self.assertEqual(m.expedite_vendor_id, "SUP-AIR-04")
        self.assertNotIn("SUP-CHN-01", [v.supplier_id for v in m.vendors])  # PRIMARY excluded
        self.assertEqual(m.throughput_gap({"LINE-2": 50}), 152)
        self.assertEqual(sorted(l.line_id for l in m.overtime_lines), ["LINE-1", "LINE-3"])

    def test_missing_column_names_migration(self):
        with mock.patch("app.factory_model.get_all_suppliers",
                        return_value=[{**_SEED_SUPPLIERS[1], "lead_time_sigma_hours": None}]):
            with self.assertRaisesRegex(FactoryDataError, "lead_time_sigma_hours.*003_factory_model"):
                load_factory_model()

    def test_invalid_values_all_reported(self):
        bad = {**_SEED_SUPPLIERS[1], "max_available_qty": -5,
               "delay_shock_min_hours": 3.0, "delay_shock_max_hours": 1.0,
               "lead_time_hours": 0, "min_lead_hours": 0}
        history = [{**h, "on_time_deliveries": 99} if h["supplier_id"] == bad["id"] else h
                   for h in fetch_all("vendor_history")]
        with mock.patch("app.factory_model.get_all_suppliers", return_value=[bad]),                 mock.patch("app.factory_model.fetch_all", return_value=history):
            with self.assertRaises(FactoryDataError) as ctx:
                load_factory_model()
        msg = str(ctx.exception)
        for field in ("max_available_qty", "delay_shock", "lead_time_hours", "min_lead_hours",
                      "on_time_deliveries"):
            self.assertIn(field, msg)

    def test_row_order_does_not_change_the_model(self):
        forward = load_factory_model()
        extra_air = {**_SEED_SUPPLIERS[3], "id": "SUP-AIR-01", "name": "Another Air Charter"}
        history = fetch_all("vendor_history") + [
            {**next(h for h in fetch_all("vendor_history") if h["supplier_id"] == "SUP-AIR-04"),
             "supplier_id": "SUP-AIR-01"}]
        suppliers = get_all_suppliers() + [extra_air]
        with mock.patch("app.factory_model.fetch_all", return_value=history):
            with mock.patch("app.factory_model.get_all_suppliers", return_value=suppliers):
                a = load_factory_model()
            with mock.patch("app.factory_model.get_all_suppliers", return_value=list(reversed(suppliers))),                     mock.patch("app.factory_model.get_all_production_lines",
                               return_value=list(reversed(get_all_production_lines()))):
                b = load_factory_model()
        self.assertEqual(a, b)
        self.assertEqual(a.expedite_vendor_id, "SUP-AIR-01")  # first EXPEDITE vendor by id
        self.assertEqual([l.line_id for l in b.lines], [l.line_id for l in forward.lines])

    def test_invalid_sourcing_role_reported(self):
        bad = {**_SEED_SUPPLIERS[1], "sourcing_role": "WIZARD"}
        with mock.patch("app.factory_model.get_all_suppliers", return_value=[bad]):
            with self.assertRaisesRegex(FactoryDataError, "sourcing_role.*WIZARD"):
                load_factory_model()

    def test_backup_without_vendor_history_rejected(self):
        with mock.patch("app.factory_model.fetch_all", return_value=[]):
            with self.assertRaisesRegex(FactoryDataError, "SUP-PNY-02.*no vendor_history"):
                load_factory_model()

    def test_unknown_factory_id(self):
        with self.assertRaisesRegex(FactoryDataError, "no-such-plant"):
            load_factory_model("no-such-plant")

    def test_pipeline_runs_for_factory_without_expedite_vendor(self):
        demo = load_factory_model()
        no_air = demo.with_vendor_overrides({"SUP-AIR-04": {"max_units": 0}})
        with mock.patch("app.agents.graph.load_factory_model", return_value=no_air):
            r = run_cascade_pipeline("x", override_shortfall_units=150, override_delay_hours=48,
                                     override_line_speeds={"LINE-2": 50}, order_id="EV-402")
        self.assertIsNone(r["ops_proposal"])
        self.assertNotIn("PLAN_A", [p["id"] for p in r["playbooks"]])
        self.assertIn(r["recommended_plan_id"], {"PLAN_B", "PLAN_C", "PLAN_D"})
        ops = [l for l in get_agent_logs(r["run_id"])
               if l["agent_name"] == "Operations Hawk" and l["tool_called"] == "factory_model.expedite_vendor_id"]
        self.assertEqual(len(ops), 1)
        self.assertIn("no vendor with role EXPEDITE", ops[0]["message"])


if __name__ == "__main__":
    unittest.main()
