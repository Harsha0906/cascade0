from tests import _offline_env  # noqa: F401  (must precede any app import)

import os
import subprocess
import sys
import unittest
from pathlib import Path

from app import evals

BACKEND = Path(__file__).resolve().parent.parent


class DatasetTests(unittest.TestCase):
    def test_datasets_are_large_enough_and_well_formed(self):
        rows = evals.load_jsonl(evals.DISRUPTIONS_PATH)
        self.assertGreaterEqual(len(rows), 50)
        for r in rows:
            self.assertEqual(set(r["expected"]),
                             {"delay_hours", "lines", "supplier_id", "order_id", "shortfall_units", "error"})
        self.assertGreaterEqual(len(evals.load_jsonl(evals.VENDOR_PATH)), 20)


class RunEvalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = evals.run_evals("regex")

    def test_reports_per_field_metrics_offline(self):
        d = self.result["disruptions"]
        self.assertGreaterEqual(d["rows"], 50)
        for field in ("delay_hours", "lines", "supplier_id", "order_id", "shortfall_units", "error"):
            m = d["fields"][field]
            for k in ("correct", "wrong", "missed", "spurious", "precision", "recall"):
                self.assertIn(k, m)
        v = self.result["vendor_replies"]
        self.assertGreaterEqual(v["rows"], 20)
        for field in ("accepted", "units", "unit_price_inr", "eta_hours"):
            self.assertIn(field, v["fields"])

    def test_regex_baselines_do_not_regress(self):
        # Recorded baselines (order_id recall 0.82 on this dataset, which deliberately includes rows
        # the regex cannot read): a drop below them means the regex got worse.
        f = self.result["disruptions"]["fields"]
        for field, floor in evals.BASELINE_RECALL.items():
            self.assertGreaterEqual(f[field]["recall"], floor, field)

    def test_gemini_path_refuses_without_live(self):
        with self.assertRaises(evals.LiveRequiredError):
            evals.run_evals("gemini")
        with self.assertRaises(evals.LiveRequiredError):
            evals.run_evals("both")


class CliTests(unittest.TestCase):
    def _run(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, "-W", "ignore", "-m", "app.evals", *args], cwd=BACKEND,
                              capture_output=True, text=True, env=env, timeout=120)

    def test_cli_prints_table_and_exits_zero(self):
        p = self._run("--path", "regex")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("order_id", p.stdout)
        self.assertIn("precision", p.stdout)

    def test_cli_gemini_without_live_is_refused_without_network(self):
        p = self._run("--path", "gemini")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--live", p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
