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


if __name__ == "__main__":
    unittest.main()
