import asyncio
import json
import unittest
from unittest.mock import patch

from agents.exceptions import ModelTimeoutError
from anthropic import APITimeoutError as AnthropicTimeout
import httpx2
from openai import APITimeoutError as OpenAITimeout
from agents import Runner

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
        with self.assertRaisesRegex(AnalysisError, "verification") as caught:
            await analyze_sample(ScriptedModel([[message()]]))
        self.assertEqual(caught.exception.diagnostics, {"stage": "tool_evidence"})

    async def test_complete_fences_preserve_numeric_verification_and_usage(self):
        for label, newline in (("json", "\n"), ("", "\n"), ("json", "\r\n")):
            for wrong in (False, True):
                answer = message(ANSWER | ({"scenario_total_usd": "1.00"} if wrong else {}))
                answer.content[0].text = f"  ```{label}{newline}{answer.content[0].text}{newline}```  "
                model = ScriptedModel([[tool_call()], [answer]])
                with self.subTest(label=label, newline=newline, wrong=wrong):
                    if wrong:
                        with self.assertRaises(AnalysisError) as caught:
                            await analyze_sample(model)
                        self.assertEqual(caught.exception.diagnostics, {"stage": "answer_facts"})
                    else:
                        result = await analyze_sample(model)
                        self.assertEqual(result.answer, ANSWER)
                        self.assertEqual((result.tool_calls, result.model_requests), (1, 2))

    async def test_wrappers_and_output_length_are_strictly_bounded(self):
        body = json.dumps(ANSWER)
        wrapped = f"```json\n{body}\n```"
        invalid = ("Result: " + wrapped, wrapped + "\n" + wrapped, wrapped[:-3],
                   wrapped + " extra", body.ljust(6001))
        for raw in (*invalid, body.ljust(6000)):
            answer = message()
            answer.content[0].text = raw
            with self.subTest(length=len(raw), valid=raw not in invalid):
                if raw in invalid:
                    with self.assertRaises(AnalysisError) as caught:
                        await analyze_sample(ScriptedModel([[tool_call()], [answer]]))
                    self.assertEqual(caught.exception.diagnostics["stage"], "answer_json")
                else:
                    result = await analyze_sample(ScriptedModel([[tool_call()], [answer]]))
                    self.assertEqual(result.answer, ANSWER)

    async def test_mismatched_amount_or_missing_fields_fails_at_specific_stage(self):
        variants = [(ANSWER | {"scenario_total_usd": "1.00"}, "answer_facts"),
                    (ANSWER | {"baseline_total_usd": "NaN"}, "answer_facts"),
                    (ANSWER | {"explanation": ""}, "answer_shape"),
                    ({"other": "private-marker"}, "answer_shape")]
        for answer, stage in variants:
            with self.subTest(answer=answer):
                with self.assertRaisesRegex(AnalysisError, "verification") as caught:
                    await analyze_sample(ScriptedModel([[tool_call()], [message(answer)]]))
                self.assertEqual(caught.exception.diagnostics, {"stage": stage})

    async def test_actual_invalid_answer_json_reports_only_stage_and_fence_boolean(self):
        for raw, fenced in (("{private-marker", False), ("```json\nprivate-marker\n```", True)):
            answer = message()
            answer.content[0].text = raw
            with self.subTest(fenced=fenced), self.assertRaises(AnalysisError) as caught:
                await analyze_sample(ScriptedModel([[tool_call()], [answer]]))
            self.assertEqual(caught.exception.category, "verification")
            self.assertEqual(caught.exception.diagnostics, dict(stage="answer_json", opening_fence=fenced))
            self.assertNotIn("private-marker", str(caught.exception))

    async def test_corrupt_tool_evidence_and_independent_calculation_have_distinct_stages(self):
        original_run = Runner.run
        for change in ("arguments", "output", "correlation", "calculation"):
            async def tampered_run(*args, **kwargs):
                result = await original_run(*args, **kwargs)
                call = next(item.raw_item for item in result.new_items if item.type == "tool_call_item")
                output = next(item.raw_item for item in result.new_items if item.type == "tool_call_output_item")
                if change == "arguments":
                    call.arguments = "{private-marker"
                elif change == "output":
                    output["output"] = "{private-marker"
                elif change == "correlation":
                    output["call_id"] = "private-marker"
                else:
                    report = kwargs["context"].executions[0].report
                    report["baseline_bill"]["total_usd"] = "0.00"
                    output["output"] = json.dumps(report)
                return result
            with self.subTest(change=change), patch("energy_ai.agents.analysis.Runner.run", side_effect=tampered_run):
                with self.assertRaises(AnalysisError) as caught:
                    await analyze_sample(ScriptedModel([[tool_call()], [message()]]))
            stage = "sample_calculation" if change == "calculation" else "tool_evidence"
            self.assertEqual(caught.exception.diagnostics, {"stage": stage})

    async def test_runner_validation_failure_remains_verification_and_has_no_response_details(self):
        with self.assertRaises(AnalysisError) as caught:
            await analyze_sample(ScriptedModel([ValueError("private-marker")]))
        self.assertEqual(caught.exception.category, "verification")
        self.assertEqual(caught.exception.diagnostics, {"stage": "runner"})
        self.assertNotIn("private-marker", str(caught.exception))

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
