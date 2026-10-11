from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import httpx2 as httpx
from agents import ModelSettings
from agents.models.interface import ModelTracing
from anthropic import transform_schema

from energy_ai.agents.analysis import AnalysisError, analyze_sample
from energy_ai.agents.provider_clients import open_model
from energy_ai.agents.anthropic_model import to_messages
from tests.fixtures.agent_responses import ANSWER, PARAMETERS


def response_body(content, stop_reason="end_turn"):
    return {"id": "msg-fixture", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 20}}


class AnthropicMessagesTests(unittest.IsolatedAsyncioTestCase):
    async def test_bill_http_status_is_classified_without_exposing_body_or_retrying(self):
        from energy_ai.bills.extraction import extract_bill, ExtractionError
        from tests.fixtures.bills import TEXT
        for status in (400, 500):
            requests = []
            def respond(request):
                requests.append(request)
                return httpx.Response(status, headers={"request-id": "private-marker"}, json={
                    "type": "error", "error": {"type": "private-marker",
                                              "message": "invalid schema pattern private-marker"}})
            with self.subTest(status=status):
                async with open_model("anthropic", api_key="secret-marker", transport=httpx.MockTransport(respond)) as model:
                    with self.assertRaises(ExtractionError) as caught:
                        await extract_bill(model, [TEXT])
                expected = dict(kind="http_status", http_status=status, attempt=1, completed_responses=0)
                if status == 400:
                    expected["message_mentions"] = ["invalid", "pattern", "schema", "type"]
                self.assertEqual(caught.exception.diagnostics, expected)
                self.assertEqual(len(requests), 1)
                self.assertIsNone(caught.exception.__context__)
                self.assertNotIn("marker", str(caught.exception) + json.dumps(caught.exception.diagnostics))

    async def test_text_only_extraction_omits_tool_configuration(self):
        from energy_ai.bills.extraction import extract_bill
        from tests.fixtures.bills import proposal, TEXT
        requests = []
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json=response_body([
                {"type": "text", "text": json.dumps(proposal())}]))
        async with open_model("anthropic", api_key="fixture-key", transport=httpx.MockTransport(respond)) as model:
            result = await extract_bill(model, [TEXT])
        self.assertEqual(result.requests, 1)
        self.assertNotIn("tool_choice", requests[0])
        self.assertNotIn("tools", requests[0])

    async def test_native_bill_schema_keeps_local_bounds_correction_and_usage(self):
        from energy_ai.bills.extraction import extract_bill
        from tests.fixtures.bills import proposal, TEXT
        for field, value, reason in (("days", 367, "range"), ("supplier", "private-marker" * 14, "length"),
                                      ("consumption", "-1", "range"), ("currency", "usd", "value")):
            requests, source_schemas, invalid = [], [], proposal()
            invalid[field]["value"] = value
            def observed_transform(schema):
                source_schemas.append((schema, deepcopy(schema)))
                return transform_schema(schema)
            def respond(request):
                requests.append(json.loads(request.content))
                return httpx.Response(200, json=response_body([{"type": "text", "text": json.dumps(
                    invalid if len(requests) == 1 else proposal())}]))
            with self.subTest(field=field), patch("energy_ai.agents.anthropic_model.transform_schema",
                                                side_effect=observed_transform):
                async with open_model("anthropic", api_key="fixture", transport=httpx.MockTransport(respond)) as model:
                    result = await extract_bill(model, [TEXT + "\nprivate-source-marker"])
                self.assertEqual((result.requests, result.input_tokens, result.output_tokens), (2, 20, 40))
                self.assertEqual(result.candidate.facts.consumption, 580)
                first, second = requests
                self.assertIn("format", first["output_config"])
                self.assertEqual(first["output_config"], second["output_config"])
                self.assertEqual(first["output_config"]["effort"], "low")
                self.assertEqual(first["output_config"]["format"]["type"], "json_schema")
                schema = first["output_config"]["format"]["schema"]
                self.assertEqual(set(schema["required"]), set(proposal()))
                quote = next(d for d in schema["$defs"].values() if "quote" in d.get("properties", {}))
                self.assertEqual(set(quote["properties"]), {"page", "quote"})
                self.assertNotIn("maximum", quote["properties"]["page"])
                self.assertNotIn("marker", json.dumps(schema))
                self.assertEqual(len(source_schemas), 2)
                for actual, before in source_schemas:
                    self.assertEqual(actual, before)
                    self.assertIsNot(actual, schema)
                self.assertNotIn("tools", first)
                self.assertNotIn("tool_choice", first)
                payload = json.loads(second["messages"][0]["content"][0]["text"])
                self.assertEqual(payload["document_pages"], [{"page": 1, "text": TEXT + "\nprivate-source-marker"}])
                self.assertEqual(payload["validation_feedback"], dict(category="schema", diagnostics=dict(
                    issues=[dict(field=field + ".value", reason=reason)], truncated=False)))

    async def test_structured_bill_refusal_or_truncation_is_safe_and_not_retried(self):
        from energy_ai.bills.extraction import extract_bill, ExtractionError
        from tests.fixtures.bills import TEXT
        for reason in ("refusal", "max_tokens"):
            requests = []
            def respond(request):
                requests.append(request)
                return httpx.Response(200, json=response_body([{"type": "text", "text": "private-marker"}], reason))
            with self.subTest(reason=reason):
                async with open_model("anthropic", api_key="fixture", transport=httpx.MockTransport(respond)) as model:
                    with self.assertRaises(ExtractionError) as caught:
                        await extract_bill(model, [TEXT])
                self.assertEqual(len(requests), 1)
                self.assertEqual(caught.exception.category, "provider")
                self.assertIsNone(caught.exception.__context__)
                self.assertNotIn("marker", str(caught.exception))

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
