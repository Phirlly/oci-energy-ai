import asyncio
import json
import unittest
from unittest.mock import patch

from agents.exceptions import ModelTimeoutError
from anthropic import APITimeoutError as AnthropicTimeout
import httpx2
from openai import APITimeoutError as OpenAITimeout

from energy_ai.agents.analysis import AnalysisError, analyze_sample
from tests.fixtures.agent_responses import ANSWER, ScriptedModel, message, tool_call


class SampleAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_runner_executes_tool_then_returns_verified_answer(self):
        model = ScriptedModel([[tool_call()], [message()]])
        with patch("agents.tracing.processors.BatchTraceProcessor.on_trace_end") as trace:
            result = await analyze_sample(model)
        self.assertEqual(result.answer, ANSWER)
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(result.model_requests, 2)
        self.assertEqual(result.input_tokens, 20)
        self.assertEqual(result.output_tokens, 40)
        returned = [item for item in model.requests[1]["input"] if item.get("type") == "function_call_output"]
        self.assertEqual(returned[0]["call_id"], "call-1")
        self.assertEqual(json.loads(returned[0]["output"])["scenario_bill"]["total_usd"], "6344.11")
        self.assertEqual(model.requests[0]["model_settings"].tool_choice, "required")
        self.assertNotEqual(model.requests[1]["model_settings"].tool_choice, "required")
        self.assertFalse(model.requests[0]["model_settings"].store)
        self.assertTrue(model.requests[0]["tracing"].is_disabled())
        trace.assert_not_called()

    async def test_answer_without_actual_tool_execution_fails(self):
        with self.assertRaisesRegex(AnalysisError, "verification"):
            await analyze_sample(ScriptedModel([[message()]]))

    async def test_mismatched_amount_invalid_json_or_missing_explanation_fails(self):
        variants = [ANSWER | {"scenario_total_usd": "1.00"},
                    ANSWER | {"baseline_total_usd": "NaN"}, ANSWER | {"explanation": ""},
                    {"other": "private-marker"}]
        for answer in variants:
            with self.subTest(answer=answer):
                with self.assertRaisesRegex(AnalysisError, "verification"):
                    await analyze_sample(ScriptedModel([[tool_call()], [message(answer)]]))

    async def test_wrong_scenario_and_unbounded_tool_loop_fail(self):
        for outputs in ([[tool_call(power_kw=0)], [message()]],
                        [[tool_call("one")], [tool_call("two")], [tool_call("three")]]):
            with self.subTest(outputs=outputs):
                with self.assertRaises(AnalysisError):
                    await analyze_sample(ScriptedModel(outputs))

    async def test_raw_provider_exception_is_not_public(self):
        with self.assertRaises(AnalysisError) as raised:
            await analyze_sample(ScriptedModel([RuntimeError("private-marker")]))
        self.assertNotIn("private-marker", str(raised.exception))
        self.assertEqual(raised.exception.category, "provider_error")

    async def test_deadline_cancels_inflight_model_request(self):
        stopped = asyncio.Event()

        class WaitingModel(ScriptedModel):
            async def get_response(self, **request):
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        with self.assertRaises(AnalysisError) as raised:
            await analyze_sample(WaitingModel([]), timeout=.01)
        self.assertEqual(raised.exception.category, "timeout")
        self.assertTrue(stopped.is_set())

    async def test_sdk_and_runner_timeouts_have_the_same_safe_category(self):
        request = httpx2.Request("POST", "https://fixture.invalid/private-marker")
        for error in (ModelTimeoutError(60), OpenAITimeout(request), AnthropicTimeout(request)):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(AnalysisError) as raised:
                    await analyze_sample(ScriptedModel([error]))
                self.assertEqual(raised.exception.category, "timeout")
                self.assertNotIn("private-marker", str(raised.exception))

    async def test_caller_cancellation_propagates_without_success(self):
        started = asyncio.Event()

        class WaitingModel(ScriptedModel):
            async def get_response(self, **request):
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(analyze_sample(WaitingModel([])))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
