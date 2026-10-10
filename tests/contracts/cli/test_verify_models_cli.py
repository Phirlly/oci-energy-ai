from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
import io
import json
import logging
import unittest
from unittest.mock import patch

from deployment.verify_models import main
from energy_ai.agents.analysis import AnalysisError
from tests.fixtures.agent_responses import ScriptedModel, message, tool_call
from tests.fixtures.office_responses import office_outputs


class VerifyModelsCliTests(unittest.TestCase):
    def invoke(self, provider="configured", environment=None):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(["--provider", provider], environment={} if environment is None else environment)
        return code, json.loads(output.getvalue()), errors.getvalue()

    @patch("deployment.verify_models.load_oci_model_context", return_value={})
    @patch("deployment.verify_models.open_model")
    def test_oci_only_skips_missing_optional_keys_and_checks_actual_tool_execution(self, factory, context):
        @asynccontextmanager
        async def opened(*args, **kwargs):
            outputs = office_outputs()
            answer = json.loads(outputs[-1][0].content[0].text)
            outputs[-1] = [message(answer | {'baseline_total_usd': '6710.800'})]
            yield ScriptedModel([[tool_call()], [message()]] + outputs)
        factory.side_effect = opened
        code, report, errors = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual([item["status"] for item in report["providers"]], ["passed", "skipped", "skipped"])
        self.assertEqual(report["providers"][0]["amounts"]["modeled_cost_difference_usd"], "366.69")
        self.assertEqual(report["providers"][0]["tool_calls"], 1)
        self.assertEqual(report['providers'][0]['office']['tool_calls'], 2)
        self.assertEqual(report['providers'][0]['office']['model_requests'], 4)
        self.assertEqual(report['providers'][0]['office']['amounts']['scenario_total_usd'], '6344.11')
        self.assertNotIn("explanation", str(report))
        self.assertEqual(errors, "")

    @patch("deployment.verify_models.load_oci_model_context")
    @patch("deployment.verify_models.open_model")
    def test_explicit_provider_needs_its_key_but_not_oci(self, factory, context):
        code, report, _ = self.invoke("openai")
        self.assertEqual(code, 1)
        self.assertEqual(report["providers"][0]["category"], "configuration")
        factory.assert_not_called()
        context.assert_not_called()

    @patch("deployment.verify_models.open_model")
    def test_configured_provider_failure_is_not_skipped_or_fallback(self, factory):
        @asynccontextmanager
        async def opened(*args, **kwargs):
            yield ScriptedModel([RuntimeError("private-marker")])
        factory.side_effect = opened
        code, report, errors = self.invoke("anthropic", {"ANTHROPIC_API_KEY": "secret-marker"})
        self.assertEqual(code, 1)
        self.assertEqual(report["providers"][0]["status"], "failed")
        self.assertEqual(report["providers"][0]["category"], "provider_error")
        self.assertNotIn("private-marker", str(report) + errors)
        self.assertNotIn("secret-marker", str(report) + errors)
        self.assertEqual(factory.call_count, 1)

    @patch("deployment.verify_models.open_model")
    @patch("deployment.verify_models.load_oci_model_context", side_effect=RuntimeError("private-marker"))
    def test_one_provider_failure_does_not_prevent_remaining_configured_checks(self, context, factory):
        @asynccontextmanager
        async def opened(*args, **kwargs):
            yield ScriptedModel([[tool_call()], [message()]] + office_outputs())
        factory.side_effect = opened
        code, report, errors = self.invoke(environment={"OPENAI_API_KEY": "fixture", "ANTHROPIC_API_KEY": "fixture"})
        self.assertEqual(code, 1)
        self.assertEqual([item["status"] for item in report["providers"]], ["failed", "passed", "passed"])
        self.assertNotIn("private-marker", str(report) + errors)

    @patch("deployment.verify_models.open_model")
    def test_raw_sdk_logs_are_suppressed_during_check(self, factory):
        @asynccontextmanager
        async def opened(*args, **kwargs):
            logging.getLogger("openai.agents").error("private-marker")
            raise RuntimeError("private-marker")
            yield
        factory.side_effect = opened
        old = logging.root.manager.disable
        code, report, errors = self.invoke("openai", {"OPENAI_API_KEY": "fixture"})
        self.assertEqual(code, 1)
        self.assertNotIn("private-marker", str(report) + errors)
        self.assertEqual(logging.root.manager.disable, old)

    @patch("deployment.verify_models.open_model")
    def test_verification_diagnostics_expose_only_stage_and_structural_boolean(self, factory):
        @asynccontextmanager
        async def opened(*args, **kwargs):
            answer = message()
            answer.content[0].text = "```json\nprivate-marker\n```"
            yield ScriptedModel([[tool_call()], [answer]])
        factory.side_effect = opened
        code, report, errors = self.invoke("openai", {"OPENAI_API_KEY": "secret-marker"})
        self.assertEqual(code, 1)
        self.assertEqual(report["providers"][0]["category"], "verification")
        self.assertEqual(report["providers"][0]["diagnostics"],
                         {"stage": "answer_json", "opening_fence": True})
        self.assertNotIn("marker", str(report) + errors)
        for category, stage, fence in (("verification", "private-marker", True),
                                       ("verification", "answer_facts", True),
                                       ("verification", "answer_json", "private-marker"),
                                       ("provider_error", "answer_json", True)):
            error = AnalysisError(category, stage=stage, opening_fence=fence)
            self.assertNotIn("marker", str(error.diagnostics))
            self.assertNotIn("opening_fence", error.diagnostics)
