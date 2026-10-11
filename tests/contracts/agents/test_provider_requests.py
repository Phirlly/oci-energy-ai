import json
import unittest
from unittest.mock import patch

import httpx
from agents import AgentOutputSchema
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from oci.signer import Signer

from energy_ai.agents.analysis import AnalysisError, analyze_sample
from energy_ai.agents.provider_clients import open_model
from energy_ai.agents.instance_auth import InstanceAuth
from tests.fixtures.agent_responses import ANSWER, PARAMETERS, message, tool_call
from tests.fixtures.resource_manager import PROJECT_ID


def response_body(output):
    return {"id": "resp-fixture", "object": "response", "created_at": 0, "status": "completed",
            "model": "fixture", "output": [item.model_dump() for item in output],
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30,
                      "input_tokens_details": {"cached_tokens": 0},
                      "output_tokens_details": {"reasoning_tokens": 0}}}


class ResponsesContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_bill_http_failure_reports_only_allowlisted_metadata_without_retry(self):
        from energy_ai.bills.extraction import extract_bill, ExtractionError
        from tests.fixtures.bills import TEXT
        for status, code, param in ((400, "invalid_json_schema", "text.format.schema"),
                                    (400, "private-marker", "secret-marker"),
                                    (429, "rate_limit_exceeded", None)):
            requests = []
            def respond(request):
                requests.append(request)
                return httpx.Response(status, headers={"x-request-id": "private-marker"}, json={"error": {
                    "message": "invalid schema mentions anyOf and private-marker",
                    "code": code, "param": param, "private-marker": "secret-marker"}})
            with self.subTest(status=status, code=code):
                async with open_model("openai", api_key="secret-marker", transport=httpx.MockTransport(respond)) as model:
                    with self.assertRaises(ExtractionError) as caught:
                        await extract_bill(model, [TEXT])
                expected = dict(kind="http_status", attempt=1, completed_responses=0, http_status=status,
                                code="other" if code == "private-marker" else code,
                                param="other" if param == "secret-marker" else param)
                if status == 400:
                    expected["message_mentions"] = ["anyOf", "invalid", "schema"]
                    if param == "text.format.schema":
                        expected["message_mentions"] = ["anyOf", "format", "invalid", "schema", "text.format"]
                self.assertEqual(caught.exception.diagnostics, expected)
                self.assertEqual(len(requests), 1)
                self.assertIsNone(caught.exception.__context__)
                self.assertNotIn("marker", str(caught.exception) + json.dumps(caught.exception.diagnostics))

    async def test_bill_schema_is_sent_through_openai_and_signed_oci_responses(self):
        from energy_ai.bills.extraction import extract_bill
        from energy_ai.bills.proposal import BillProposal
        from tests.fixtures.bills import proposal, TEXT
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        signer = Signer("ocid1.tenancy.oc1..fixture", "ocid1.user.oc1..fixture", "aa:bb",
                        None, private_key_content=pem)
        for provider in ("openai", "oci"):
            requests = []
            def respond(request):
                requests.append(request)
                return httpx.Response(200, json=response_body([message(proposal())]))
            options = dict(api_key="fixture") if provider == "openai" else dict(
                oci_region="us-ashburn-1", oci_project=PROJECT_ID, oci_signer=signer)
            with self.subTest(provider=provider):
                async with open_model(provider, **options, transport=httpx.MockTransport(respond)) as model:
                    result = await extract_bill(model, [TEXT + "\nprivate-source-marker"])
                self.assertEqual((len(requests), result.requests), (1, 1))
                self.assertEqual(result.candidate.evidence["supplier"].offset, 0)
                body = json.loads(requests[0].content)
                self.assertIn("text", body)
                format = body["text"]["format"]
                self.assertEqual(format["type"], "json_schema")
                self.assertTrue(format["strict"])
                original = AgentOutputSchema(BillProposal).json_schema()
                self.assertEqual(original["properties"]["charges"].pop("maxItems"), 40)
                self.assertEqual(format["schema"], original)
                self.assertEqual(BillProposal.model_json_schema()["properties"]["charges"]["maxItems"], 40)
                self.assertEqual(set(format["schema"]["required"]), set(proposal()))
                self.assertNotIn("offset", json.dumps(format["schema"]))
                self.assertNotIn("marker", json.dumps(format["schema"]))
                self.assertFalse(body["store"])
                self.assertEqual(body.get("tools", []), [])
                if provider == "oci":
                    self.assertTrue(requests[0].headers["authorization"].startswith("Signature "))
                    self.assertEqual(requests[0].headers["openai-project"], PROJECT_ID)

    async def test_openai_round_trip_has_correlated_output_and_bounded_private_requests(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=response_body([tool_call()] if len(requests) == 1 else [message()]))

        with patch.dict("os.environ", {"OPENAI_BASE_URL": "https://untrusted.invalid",
                                       "OPENAI_PROJECT_ID": "untrusted-project"}):
            async with open_model("openai", api_key="fixture-key", transport=httpx.MockTransport(respond)) as model:
                result = await analyze_sample(model)
        self.assertEqual(result.tool_calls, 1)
        self.assertEqual(len(requests), 2)
        self.assertEqual(str(requests[0].url), "https://api.openai.com/v1/responses")
        self.assertEqual(requests[0].headers["authorization"], "Bearer fixture-key")
        self.assertNotIn("untrusted-project", str(requests[0].headers))
        first, second = [json.loads(request.content) for request in requests]
        self.assertEqual(first["model"], "gpt-4.1-mini-2025-04-14")
        self.assertFalse(first["store"])
        self.assertEqual(first["max_output_tokens"], 2048)
        self.assertEqual(first["tool_choice"], "required")
        self.assertEqual(first["tools"][0]["name"], "analyze_energy")
        self.assertEqual(requests[0].extensions["timeout"]["read"], 60)
        output = next(item for item in second["input"] if item.get("type") == "function_call_output")
        self.assertEqual(output["call_id"], "call-1")
        self.assertEqual(json.loads(output["output"])["scenario_bill"]["total_usd"], "6344.11")

    async def test_oci_signs_in_memory_and_routes_to_explicit_project(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        signer = Signer("ocid1.tenancy.oc1..fixture", "ocid1.user.oc1..fixture", "aa:bb",
                        None, private_key_content=pem)
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=response_body([tool_call()] if len(requests) == 1 else [message()]))

        with patch("oci.config.from_file") as profile:
            async with open_model("oci", oci_region="us-ashburn-1", oci_project=PROJECT_ID,
                                  oci_signer=signer, transport=httpx.MockTransport(respond)) as model:
                await analyze_sample(model)
            profile.assert_not_called()
        self.assertEqual(str(requests[0].url),
                         "https://inference.generativeai.us-ashburn-1.oci.oraclecloud.com/openai/v1/responses")
        self.assertTrue(requests[0].headers["authorization"].startswith("Signature "))
        self.assertEqual(requests[0].headers["openai-project"], PROJECT_ID)
        self.assertIn("x-content-sha256", requests[0].headers)
        self.assertNotIn("Bearer", str(requests[0].headers))
        self.assertEqual(json.loads(requests[0].content)["model"], "google.gemini-2.5-flash")

    async def test_provider_errors_are_not_retried_and_body_is_not_exposed(self):
        for status, category in ((401, "authentication"), (403, "access"), (404, "access"),
                                 (429, "rate_limit"), (500, "provider_error")):
            with self.subTest(status=status):
                requests = []

                def fail(request):
                    requests.append(request)
                    return httpx.Response(status, json={"error": {"message": "private-marker", "type": "fixture"}})

                async with open_model("openai", api_key="fixture-key", transport=httpx.MockTransport(fail)) as model:
                    with self.assertRaises(AnalysisError) as raised:
                        await analyze_sample(model)
                self.assertEqual(raised.exception.category, category)
                self.assertNotIn("private-marker", str(raised.exception))
                self.assertEqual(len(requests), 1)

    async def test_incomplete_response_fails_even_if_it_contains_correct_answer(self):
        requests = []

        def respond(request):
            requests.append(request)
            body = response_body([tool_call()] if len(requests) == 1 else [message()])
            if len(requests) == 2:
                body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
            return httpx.Response(200, json=body)

        async with open_model("openai", api_key="fixture", transport=httpx.MockTransport(respond)) as model:
            with self.assertRaises(AnalysisError):
                await analyze_sample(model)
        self.assertEqual(len(requests), 2)

    async def test_client_closes_when_consumer_fails(self):
        class Transport(httpx.MockTransport):
            closed = False

            async def aclose(self):
                self.closed = True

        transport = Transport(lambda request: httpx.Response(500))
        with self.assertRaisesRegex(RuntimeError, "consumer"):
            async with open_model("openai", api_key="fixture-key", transport=transport):
                raise RuntimeError("consumer")
        self.assertTrue(transport.closed)

    async def test_invalid_model_or_missing_identity_fails_before_network(self):
        for provider, options in (("openai", {}), ("unknown", {}), ("oci", {}),
                                  ("openai", {"api_key": "fixture", "model_id": "../private"})):
            with self.subTest(provider=provider, options=options):
                with self.assertRaises(ValueError):
                    async with open_model(provider, **options):
                        self.fail("Invalid configuration accepted.")

    async def test_explicit_instance_auth_is_used_and_cannot_be_combined_with_fixed_signer(self):
        signed = []
        def signer(request):
            signed.append(request)
            request.headers['authorization'] = 'Signature fixture-instance'
            return request
        auth = InstanceAuth(signer)
        self.addCleanup(auth.close)
        def respond(request):
            self.assertEqual(request.headers['authorization'], 'Signature fixture-instance')
            return httpx.Response(200, json=response_body([tool_call()] if len(signed) == 1 else [message()]))
        options = dict(oci_region='us-ashburn-1', oci_project=PROJECT_ID, oci_auth=auth)
        async with open_model('oci', **options, transport=httpx.MockTransport(respond)) as model:
            self.assertEqual((await analyze_sample(model)).tool_calls, 1)
        self.assertEqual(len(signed), 2)
        with self.assertRaises(ValueError):
            async with open_model('oci', **options, oci_signer=signer):
                self.fail('Ambiguous identity accepted.')
