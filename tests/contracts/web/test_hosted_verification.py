import unittest

from fastapi.testclient import TestClient

from deployment.configuration import DeploymentError
from deployment.resource_jobs import OperationDeadline
from deployment.verify_hosted import HostedVerifier
from energy_ai.agents.office_analysis import analyze_office
from energy_ai.bills.extraction import ExtractionResult
from energy_ai.bills.schema import Candidate
from energy_ai.web.app import create_app
from energy_ai.web.hosted_configuration import HostedConfiguration
from tests.fixtures.agent_responses import ScriptedModel
from tests.fixtures.bills import candidate
from tests.fixtures.host_release import release
from tests.fixtures.office_responses import office_outputs


class HostedVerificationTests(unittest.TestCase):
    def setUp(self):
        import json
        import time
        self.manifest = release()[2]
        runtime = self.manifest['runtime']
        self.config = HostedConfiguration.from_bytes(json.dumps(runtime).encode())
        async def extract(provider, pages):
            value = candidate()
            for evidence in value['evidence'].values():
                evidence['quote'] = pages[0]
            return ExtractionResult(Candidate.model_validate(value).verify(pages), 1, 20, 30)
        async def analyze(provider, controls, question, publish):
            return await analyze_office(ScriptedModel(office_outputs()), controls, question, publish)
        self.app = create_app(access_code='admin', origin=self.config.origin, backend_host=self.config.backend_host,
            release=self.manifest['release'], providers=self.config.providers, model_ids=self.config.models(),
            extractor=extract, office_analyzer=analyze)
        self.client = self.enterContext(TestClient(self.app, base_url=self.config.origin,
                                                    headers={'Host': self.config.backend_host}))
        self.verifier = HostedVerifier(self.client, self.config, 'admin', self.manifest['release'],
                                      OperationDeadline(30, time.monotonic, lambda _: time.sleep(.01)))

    def test_public_hosted_customer_journey_uses_real_routes_and_cleans_session(self):
        result = self.verifier.check(full=True)
        self.assertEqual(result['providers'], ['oci'])
        self.assertTrue(result['office_scenario'])
        self.assertTrue(result['bill_upload_review'])
        self.assertEqual(self.client.get('/api/office').status_code, 401)
        self.assertEqual(self.app.state.sessions.items, {})

    def test_wrong_password_fails_without_disclosing_password_or_response_body(self):
        self.verifier.password = 'private-marker'
        with self.assertRaises(DeploymentError) as raised:
            self.verifier.check()
        self.assertNotIn('private-marker', str(raised.exception))
        self.assertNotIn('Incorrect launch code', str(raised.exception))

    def test_stale_release_fails_before_login(self):
        self.verifier.release = 'b' * 40
        with self.assertRaisesRegex(DeploymentError, 'release'):
            self.verifier.check()
        self.assertEqual(self.app.state.sessions.items, {})

    def test_configured_provider_failure_is_not_reported_as_passed_and_session_closes(self):
        async def fail(*args):
            raise RuntimeError('private-provider-detail')
        self.app.state.office.analyze = fail
        with self.assertRaisesRegex(DeploymentError, 'provider journey') as raised:
            self.verifier.check(full=True)
        self.assertNotIn('private-provider-detail', str(raised.exception))
        self.assertEqual(self.app.state.sessions.items, {})
