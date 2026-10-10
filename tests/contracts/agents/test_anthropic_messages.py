import json
import unittest
from unittest.mock import patch

import httpx2 as httpx
from agents import ModelSettings
from agents.models.interface import ModelTracing

from energy_ai.agents.analysis import AnalysisError, analyze_sample
from energy_ai.agents.provider_clients import open_model
from energy_ai.agents.anthropic_model import to_messages
from tests.fixtures.agent_responses import ANSWER, PARAMETERS


def response_body(content, stop_reason="end_turn"):
    return {"id": "msg-fixture", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 20}}


class AnthropicMessagesTests(unittest.IsolatedAsyncioTestCase):
    @patch.dict("os.environ", {"ANTHROPIC_AUTH_TOKEN": "unrelated-token",
                               "ANTHROPIC_BASE_URL": "https://untrusted.invalid"})
    async def test_native_messages_round_trip_preserves_tool_schema_id_and_result(self):
        requests = []

        def respond(request):
            requests.append(request)
            if len(requests) == 1:
                content = [{"type": "text", "text": "Calculating the scenario."},
                           {"type": "tool_use", "id": "toolu-fixture", "name": "analyze_energy", "input": PARAMETERS}]
                return httpx.Response(200, json=response_body(content, "tool_use"))
            return httpx.Response(200, json=response_body([{"type": "text", "text": json.dumps(ANSWER)}]))

        async with open_model("anthropic", api_key="fixture-key", transport=httpx.MockTransport(respond)) as model:
            result = await analyze_sample(model)
        self.assertEqual(result.answer, ANSWER)
        self.assertEqual(result.model_requests, 2)
        self.assertEqual(str(requests[0].url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(requests[0].headers["x-api-key"], "fixture-key")
        self.assertNotIn("authorization", requests[0].headers)
        first, second = [json.loads(request.content) for request in requests]
        self.assertEqual(first["model"], "claude-haiku-5-5")
        self.assertEqual(first["thinking"], {"type": "disabled"})
        self.assertEqual(first["output_config"], {"effort": "low"})
        self.assertEqual(first["max_tokens"], 2048)
        self.assertEqual(first["tool_choice"]["type"], "any")
        self.assertEqual(first["tools"][0]["input_schema"]["required"], list(PARAMETERS))
        self.assertNotIn("temperature", first)
        self.assertNotIn("store", first)
        self.assertEqual(second["tool_choice"]["type"], "auto")
        self.assertEqual([item["role"] for item in second["messages"]], ["user", "assistant", "user"])
        self.assertEqual(second["messages"][1]["content"][1]["id"], "toolu-fixture")
        output = second["messages"][2]["content"][0]
        self.assertEqual(output["tool_use_id"], "toolu-fixture")
        self.assertEqual(json.loads(output["content"])["modeled_cost_difference_usd"], "366.69")

    async def test_truncation_refusal_thinking_and_unknown_blocks_cannot_pass(self):
        cases = [("max_tokens", [{"type": "text", "text": json.dumps(ANSWER)}]),
                 ("refusal", [{"type": "text", "text": "private-marker"}]),
                 ("end_turn", [{"type": "thinking", "thinking": "private-marker", "signature": "fixture"}])]
        for reason, content in cases:
            with self.subTest(reason=reason, content=content):
                transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response_body(content, reason)))
                async with open_model("anthropic", api_key="fixture-key", transport=transport) as model:
                    with self.assertRaises(AnalysisError) as raised:
                        await analyze_sample(model)
                self.assertNotIn("private-marker", str(raised.exception))

    async def test_rate_limit_is_not_retried(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(429, json={"type": "error", "error": {"type": "rate_limit_error",
                                                                     "message": "private-marker"}})
        async with open_model("anthropic", api_key="fixture-key", transport=httpx.MockTransport(respond)) as model:
            with self.assertRaises(AnalysisError) as raised:
                await analyze_sample(model)
        self.assertEqual(raised.exception.category, "rate_limit")
        self.assertEqual(len(requests), 1)

    async def test_unsupported_remote_state_is_rejected_before_request(self):
        requests = []
        transport = httpx.MockTransport(lambda request: requests.append(request))
        async with open_model("anthropic", api_key="fixture-key", transport=transport) as model:
            with self.assertRaises(ValueError):
                await model.get_response(None, "fixture", ModelSettings(max_tokens=100),
                                         [], None, [], ModelTracing.DISABLED,
                                         previous_response_id="remote", conversation_id=None, prompt=None)
        self.assertEqual(requests, [])


class MessageTranslationTests(unittest.TestCase):
    def test_parallel_results_group_after_same_assistant_turn(self):
        items = [{"role": "user", "content": "calculate"}]
        for call_id in ("one", "two"):
            items.append({"type": "function_call", "call_id": call_id, "name": "analyze_energy", "arguments": "{}"})
        for call_id in ("one", "two"):
            items.append({"type": "function_call_output", "call_id": call_id, "output": "{}"})
        messages = to_messages(items)
        self.assertEqual([item["role"] for item in messages], ["user", "assistant", "user"])
        self.assertEqual([item["tool_use_id"] for item in messages[-1]["content"]], ["one", "two"])

    def test_unknown_content_or_orphan_results_are_rejected(self):
        for items in ([{"type": "reasoning", "summary": []}],
                      [{"role": "user", "content": [{"type": "input_image", "image_url": "private"}]}],
                      [{"type": "function_call_output", "call_id": "missing", "output": "{}"}]):
            with self.subTest(items=items):
                with self.assertRaises(ValueError):
                    to_messages(items)
