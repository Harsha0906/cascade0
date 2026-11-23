from tests import _offline_env  # noqa: F401  (must precede any app import)

import unittest
from unittest import mock

from app.agents import graph


class _FailingModels:
    def __init__(self):
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        raise TimeoutError("deadline exceeded")


class NarrationCooldownTests(unittest.TestCase):
    def setUp(self):
        graph._narration_down_until = 0.0

    def tearDown(self):
        graph._narration_down_until = 0.0

    def test_failure_switches_to_templates_without_retrying_each_step(self):
        models = _FailingModels()
        client = mock.Mock(models=models)
        with mock.patch.object(graph.settings.__class__, "has_gemini", new_callable=mock.PropertyMock,
                               return_value=True), \
             mock.patch.object(graph, "_get_genai_client", return_value=client):
            first = graph._llm_agent_reason("A", "R", "obj", {}, "fallback one")
            second = graph._llm_agent_reason("A", "R", "obj", {}, "fallback two")
        self.assertEqual(first, ("fallback one", "template"))
        self.assertEqual(second, ("fallback two", "template"))
        self.assertEqual(models.calls, 1)   # the second step did not wait for another timeout

    def test_cooldown_expires(self):
        models = _FailingModels()
        client = mock.Mock(models=models)
        with mock.patch.object(graph.settings.__class__, "has_gemini", new_callable=mock.PropertyMock,
                               return_value=True), \
             mock.patch.object(graph, "_get_genai_client", return_value=client), \
             mock.patch.object(graph.time, "monotonic", side_effect=[0.0, 0.0, 61.0, 61.0]):
            graph._llm_agent_reason("A", "R", "obj", {}, "x")
            graph._llm_agent_reason("A", "R", "obj", {}, "y")
        self.assertEqual(models.calls, 2)


FACTS = {"shortfall_units": 800, "sla_penalty_inr": 180000, "confidence_pct": 94.2,
         "order_id": "EV-402", "delay_hours": 12, "vendors": [{"id": "SUP-HSR-03", "cost": 2450000}]}


class GuardTests(unittest.TestCase):
    def test_accepts_equivalent_formats(self):
        g = graph.narration_is_grounded
        self.assertTrue(g("The penalty is ₹1.8L.", FACTS))
        self.assertTrue(g("The penalty is ₹1,80,000.", FACTS))
        self.assertTrue(g("The penalty is Rs 180,000.", FACTS))
        self.assertTrue(g("Penalty 1.8 lakh on EV-402.", FACTS))
        self.assertTrue(g("Cost ₹24.5 lakh via SUP-HSR-03.", FACTS))
        self.assertTrue(g("Cost ₹0.245 Cr.", FACTS))
        self.assertTrue(g("On-time confidence is 94.2%, rounded 94%.", FACTS))
        self.assertTrue(g("800 units are short after 12 hours.", FACTS))

    def test_rejects_invented_numbers(self):
        g = graph.narration_is_grounded
        self.assertFalse(g("The penalty is ₹2.5L.", FACTS))
        self.assertFalse(g("The penalty is ₹2,50,000.", FACTS))
        self.assertFalse(g("800 units short, 95% confidence.", FACTS))
        self.assertFalse(g("Delay of 13 hours.", FACTS))

    def test_small_integers_must_be_in_facts(self):
        g = graph.narration_is_grounded
        self.assertFalse(g("Choose option 5 now.", FACTS))
        self.assertFalse(g("Delay of 12 hours across 4 lines.", FACTS))
        self.assertTrue(g("Delay of 3 hours.", {"delay_hours": 3}))
        self.assertFalse(g("Delay of 3 hours.", {"delay_hours": 3.4}))

    def test_text_without_numbers_is_grounded(self):
        self.assertTrue(graph.narration_is_grounded("Plan B is the cheapest option.", FACTS))


class _Resp:
    def __init__(self, text, usage=None):
        self.text = text
        self.usage_metadata = usage


def _gemini_client(text, usage=None):
    models = mock.Mock()
    models.generate_content.return_value = _Resp(text, usage)
    return mock.Mock(models=models)


class GuardedNarrationTests(unittest.TestCase):
    def setUp(self):
        graph._narration_down_until = 0.0

    def tearDown(self):
        graph._narration_down_until = 0.0

    def _run(self, text, usage=None):
        with mock.patch.object(graph.settings.__class__, "has_gemini", new_callable=mock.PropertyMock,
                               return_value=True), \
             mock.patch.object(graph, "_get_genai_client", return_value=_gemini_client(text, usage)):
            return graph._llm_agent_reason("A", "R", "obj", FACTS, "template text")

    def test_invented_number_falls_back_to_template(self):
        out = self._run("The SLA penalty of ₹2.5L is at stake on this order.")
        self.assertEqual(out, ("template text", "template-guarded"))

    def test_grounded_narration_is_kept(self):
        text = "The SLA penalty of ₹1.8L is at stake on order EV-402."
        self.assertEqual(self._run(text), (text, "gemini"))

    def test_guard_rejection_does_not_start_the_cooldown(self):
        self._run("The SLA penalty of ₹2.5L is at stake on this order.")
        self.assertEqual(graph._narration_down_until, 0.0)

    def test_template_guarded_counts_as_non_llm(self):
        trace = [{"node": "a", "mode": "template-guarded"}, {"node": "b", "mode": "regex-fallback"}]
        self.assertEqual(graph.summarize_ai_mode(trace)["overall"], "fallback")
        self.assertEqual(graph.summarize_ai_mode(trace + [{"node": "c", "mode": "gemini"}])["overall"], "mixed")


class TraceTimingTests(unittest.TestCase):
    def setUp(self):
        graph._narration_down_until = 0.0

    def test_template_entry_has_latency(self):
        entry = graph._trace({}, "ops_hawk", "template")[-1]
        self.assertIn("latency_ms", entry)
        self.assertEqual(entry["mode"], "template")

    def test_gemini_entry_carries_latency_and_tokens(self):
        usage = mock.Mock(prompt_token_count=120, candidates_token_count=45)
        text = "The SLA penalty of ₹1.8L is at stake on order EV-402."
        with mock.patch.object(graph.settings.__class__, "has_gemini", new_callable=mock.PropertyMock,
                               return_value=True), \
             mock.patch.object(graph, "_get_genai_client", return_value=_gemini_client(text, usage)):
            _, mode = graph._llm_agent_reason("A", "R", "obj", FACTS, "t")
        entry = graph._trace({}, "arbitrator", mode)[-1]
        self.assertGreaterEqual(entry["latency_ms"], 0)
        self.assertEqual((entry["input_tokens"], entry["output_tokens"]), (120, 45))
        # the stats belong to one call: the next trace entry does not reuse them
        self.assertNotIn("input_tokens", graph._trace({}, "next", "template")[-1])

    def test_pipeline_trace_entries_all_carry_latency(self):
        out = graph.run_cascade_pipeline(
            "Chennai Precision Casings delayed by 12 hours. Line 2 at 40%. 800 casings short on EV-402.")
        self.assertTrue(out["llm_trace"])
        for entry in out["llm_trace"]:
            self.assertIn("latency_ms", entry)


if __name__ == "__main__":
    unittest.main()
