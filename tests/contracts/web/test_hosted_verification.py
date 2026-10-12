from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from deployment.configuration import DeploymentError
from deployment.resource_jobs import OperationDeadline
from deployment.verify_hosted import HostedVerifier
from energy_ai.agents.analysis import AnalysisError
from energy_ai.agents.office_analysis import analyze_office
from energy_ai.bills.extraction import ExtractionResult
from energy_ai.bills.schema import Candidate
from energy_ai.web.app import create_app
from energy_ai.web.hosted_configuration import HostedConfiguration
from energy_ai.web.sessions import Document
from tests.fixtures.agent_responses import ScriptedModel
from tests.fixtures.bills import candidate
from tests.fixtures.host_release import release
from tests.fixtures.office_responses import office_outputs


class HostedVerificationTests(unittest.TestCase):
    def setUp(self):
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
        self.options = dict(access_code='admin', origin=self.config.origin, backend_host=self.config.backend_host,
            release=self.manifest['release'], providers=self.config.providers, model_ids=self.config.models(),
            extractor=extract, office_analyzer=analyze)
        self.app = create_app(**self.options)
        self.client = self.enterContext(TestClient(self.app, base_url=self.config.origin,
                                                    headers={'Host': self.config.backend_host}))
        self.verifier = HostedVerifier(self.client, self.config, 'admin', self.manifest['release'],
                                      OperationDeadline(30, time.monotonic, lambda _: time.sleep(.01)))

    def test_public_hosted_customer_journey_uses_real_routes_and_cleans_session(self):
        result = self.verifier.check(full=True)
        self.assertEqual(result['providers'], ['oci'])
        self.assertTrue(result['office_scenario'])
        self.assertTrue(result['bill_upload_review'])
        self.assertEqual(len(result['history']), 1)
        self.assertEqual(self.client.get('/api/office').status_code, 401)
        self.assertEqual(self.app.state.sessions.items, {})
        record = self.saved_history()[0]
        self.assertIn(record['id'], result['history'])
        self.assertRegex(result['history'][record['id']], r'^[a-f0-9]{64}$')
        self.assertNotIn('result', result['history'])

    def test_public_history_fingerprint_survives_a_sqlite_presenter_restart(self):
        with TemporaryDirectory() as directory:
            snapshots = []
            for _ in range(2):
                app = create_app(**self.options, office_database=Path(directory) / 'office.sqlite3')
                with TestClient(app, base_url=self.config.origin,
                                headers={'Host': self.config.backend_host}) as client:
                    verifier = HostedVerifier(client, self.config, 'admin', self.manifest['release'],
                                              self.verifier.deadline)
                    snapshots.append(verifier.check(full=True)['history'])
            selected = next(iter(snapshots[0]))
            self.assertEqual(len(snapshots[0]), 1)
            self.assertEqual(len(snapshots[1]), 2)
            self.assertEqual(snapshots[0][selected], snapshots[1][selected])

    def saved_history(self):
        self.client.post('/api/session', headers=self.verifier.headers, json={'code': 'admin'})
        records = self.client.get('/api/office/runs').json()
        self.client.delete('/api/session', headers=self.verifier.headers)
        return records

    def test_changed_history_result_changes_fingerprint_without_disclosing_text(self):
        first = self.verifier.check(full=True)['history']
        selected = next(iter(first))
        record = self.saved_history()[0]
        record['result']['details'] = 'private-test-marker'
        with patch.object(self.app.state.office.repository, 'history', return_value=[record]):
            second = self.verifier.check(full=True)['history']
        self.assertNotEqual(first[selected], second[selected])
        self.assertNotIn('private-test-marker', repr(second))

    def test_malformed_or_duplicate_history_fails_safely_and_closes_session(self):
        self.verifier.check(full=True)
        record = self.saved_history()[0]
        variants = {'not_list': {}, 'too_many': [record] * 101,
                    'duplicate': [record, record | {'status': 'running'}],
                    'bad_id': [record | {'id': 'private-test-marker'}],
                    'bad_status': [record | {'status': 'unknown'}],
                    'bad_record': [None], 'nonfinite': [record | {'created': float('nan')}]}
        for name, value in variants.items():
            with self.subTest(name=name), patch.object(self.app.state.office.repository, 'history', return_value=value):
                with self.assertRaises(DeploymentError) as raised:
                    self.verifier.check(full=True)
                self.assertNotIn('private-test-marker', str(raised.exception))
                self.assertEqual(self.app.state.sessions.items, {})

    def test_wrong_password_fails_without_disclosing_password_or_response_body(self):
        self.verifier.password = 'private-marker'
        with self.assertRaises(DeploymentError) as raised:
            self.verifier.check()
        self.assertNotIn('private-marker', str(raised.exception))
        self.assertNotIn('Incorrect demo password', str(raised.exception))

    def bill_failure(self, change):
        original = Document.public
        def altered(document):
            value = deepcopy(original(document))
            if value['job'] and value['job']['status'] == 'complete':
                change(value)
            return value
        with patch.object(Document, 'public', altered):
            with self.assertRaises(DeploymentError) as raised:
                self.verifier.check(full=True)
        message = str(raised.exception)
        self.assertIn('provider=oci', message)
        self.assertNotIn('private-test-marker', message)
        self.assertNotIn(self.verifier.password, message)
        self.assertEqual(self.app.state.sessions.items, {})
        self.assertEqual(self.client.get('/api/office').status_code, 401)
        return message

    def test_completed_bill_fact_diagnostics_identify_stage_without_values(self):
        cases = [
            ('proposal_facts', lambda value: value['proposal']['facts'].update(account='private-test-marker'),
             {'fields': ['account']}),
            ('proposal_facts', lambda value: value['proposal']['facts'].update(supplier='Juniper Power private-test-marker'),
             {'fields': ['supplier'], 'supplier_absent': False, 'supplier_normalized_match': False,
              'supplier_contains_expected': True}),
            ('reviewed_facts', lambda value: value['facts'].update(account='private-test-marker'),
             {'fields': ['account']}),
        ]
        for stage, change, expected in cases:
            with self.subTest(stage=stage, fields=expected['fields']):
                message = self.bill_failure(change)
                self.assertIn('stage=' + stage, message)
                self.assertEqual(json.loads(message.split('diagnostics=', 1)[1]), expected)

    def test_completed_bill_metadata_schema_and_evidence_failures_suppress_details(self):
        cases = [
            ('job_metadata', lambda value: value['job']['usage'].update(requests=0)),
            ('job_metadata', lambda value: value.update(approved_revision=1)),
            ('proposal_evidence', lambda value: value['proposal']['facts'].update(service='private-test-marker')),
            ('proposal_evidence', lambda value: value['proposal']['evidence']['account'].update(quote='private-test-marker')),
            ('reviewed_facts', lambda value: value['facts'].update(service='private-test-marker')),
        ]
        for stage, change in cases:
            with self.subTest(stage=stage):
                message = self.bill_failure(change)
                self.assertIn('stage=' + stage, message)
                self.assertIn('response details suppressed', message)
                self.assertNotIn('diagnostics=', message)

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
        self.assertIn('provider=oci; stage=office_analysis; status=failed; category=unclassified',
                      str(raised.exception))
        self.assertEqual(self.app.state.sessions.items, {})

    def test_office_failures_report_fixed_categories_and_stop_before_extraction(self):
        categories = ('verification', 'timeout', 'authentication', 'access', 'rate_limit', 'provider_error')
        self.config.secret_ids['openai'] = self.config.secret_ids['demo_password'] + 'openai'
        for category in categories:
            with self.subTest(category=category):
                analyze = AsyncMock(side_effect=AnalysisError(category))
                extract = AsyncMock(side_effect=AssertionError('Extraction must not start.'))
                app = create_app(**(self.options | dict(providers=self.config.providers,
                    model_ids=self.config.models(), office_analyzer=analyze, extractor=extract)))
                with TestClient(app, base_url=self.config.origin,
                                headers={'Host': self.config.backend_host}) as client:
                    verifier = HostedVerifier(client, self.config, 'admin', self.manifest['release'],
                                              self.verifier.deadline)
                    with self.assertRaises(DeploymentError) as raised:
                        verifier.check(full=True)
                    self.assertIn('provider=oci; stage=office_analysis; status=failed; category=' + category,
                                  str(raised.exception))
                    self.assertEqual(app.state.sessions.items, {})
                    self.assertEqual(client.get('/api/office').status_code, 401)
                analyze.assert_awaited_once()
                self.assertEqual(analyze.await_args.args[0], 'oci')
                extract.assert_not_awaited()

    def test_failed_bill_job_identifies_extraction_and_cleans_session(self):
        extract = AsyncMock(side_effect=RuntimeError('private-test-marker'))
        app = create_app(**(self.options | dict(extractor=extract)))
        with TestClient(app, base_url=self.config.origin,
                        headers={'Host': self.config.backend_host}) as client:
            verifier = HostedVerifier(client, self.config, 'admin', self.manifest['release'],
                                      self.verifier.deadline)
            with self.assertRaises(DeploymentError) as raised:
                verifier.check(full=True)
            message = str(raised.exception)
            self.assertIn('provider=oci; stage=bill_extraction; status=failed; category=unclassified', message)
            self.assertNotIn('private-test-marker', message)
            self.assertEqual(app.state.sessions.items, {})
            self.assertEqual(client.get('/api/office').status_code, 401)
        extract.assert_awaited_once()

    def test_polling_projects_untrusted_status_and_error_shapes_onto_fixed_labels(self):
        cases = [
            (None, 'invalid'), ({}, 'invalid'),
            ({'status': 'private-test-marker', 'error': 'private-test-marker'}, 'invalid'),
            ({'status': ['private-test-marker']}, 'invalid'),
            ({'status': 'failed', 'error': {'private-test-marker': 1}}, 'failed'),
            ({'status': 'failed', 'error': str(AnalysisError('access')) + ' private-test-marker'}, 'failed'),
            ({'status': 'cancelled'}, 'cancelled'), ({'status': 'interrupted'}, 'interrupted'),
        ]
        for document in (False, True):
            stage = 'bill_extraction' if document else 'office_analysis'
            for job, status in cases:
                with self.subTest(document=document, status=status, job=job):
                    response = {'job': job} if document else job
                    with patch.object(self.verifier, '_request', return_value=response) as request:
                        with self.assertRaises(DeploymentError) as raised:
                            self.verifier._poll('/private-test-marker', provider='openai', document=document)
                    self.assertEqual(str(raised.exception), 'Hosted provider journey did not complete successfully: '
                        f'provider=openai; stage={stage}; status={status}; category=unclassified')
                    request.assert_called_once()
