import asyncio
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient

from energy_ai.agents.office_analysis import analyze_office
from energy_ai.office.sample import Controls
from energy_ai.web.app import create_app
from energy_ai.web.requests import read_contract
from tests.fixtures.agent_responses import ScriptedModel
from tests.fixtures.office_responses import office_outputs

ORIGIN = 'http://127.0.0.1:8765'
HEADERS = {'Origin': ORIGIN, 'X-Energy-Action': '1'}


async def scripted(provider, controls, question, publish):
    return await analyze_office(ScriptedModel(office_outputs()), controls, question, publish)


class OfficeRoutesTests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(create_app(
            access_code='test-launch-code', origin=ORIGIN, providers=['openai'], office_analyzer=scripted), base_url=ORIGIN))

    def login(self):
        self.assertEqual(self.client.post('/api/session', headers=HEADERS, json={'code': 'test-launch-code'}).status_code, 200)

    def payload(self):
        return dict(request_key=str(uuid4()), provider='openai', consent=True,
                    controls=Controls().model_dump(), question='evaluate_battery')

    def test_office_requires_auth_and_origin_and_returns_reconciled_profile_scenario_pdf(self):
        self.assertEqual(self.client.get('/api/office').status_code, 401)
        self.login()
        self.assertEqual(self.client.get('/api/office').json()['bill']['total_usd'], '6710.80')
        self.assertEqual(self.client.post('/api/office/scenario', json={}).status_code, 403)
        response = self.client.post('/api/office/scenario', headers=HEADERS, json=Controls().model_dump())
        self.assertEqual(response.json()['scenario_bill']['total_usd'], '6344.11')
        response = self.client.get('/api/office/bill.pdf')
        self.assertEqual(response.headers['content-type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('attachment', response.headers['content-disposition'])

    def test_real_runner_polling_idempotency_shared_history_and_conflict(self):
        self.login()
        payload = self.payload()
        response = self.client.post('/api/office/runs', headers=HEADERS, json=payload)
        self.assertEqual(response.status_code, 202)
        run_id = response.json()['id']
        for _ in range(100):
            run = self.client.get('/api/office/runs/' + run_id).json()
            if run['status'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(run['status'], 'complete', run)
        self.assertEqual(run['result']['usage']['tool_calls'], 2)
        self.assertEqual(self.client.post('/api/office/runs', headers=HEADERS, json=payload).json()['id'], run_id)
        self.assertEqual(self.client.post('/api/office/runs', headers=HEADERS,
                                         json=payload | {'question': 'explain_bill'}).status_code, 409)
        self.client.delete('/api/session', headers=HEADERS)
        self.login()
        self.assertEqual(self.client.get('/api/office/runs').json()[0]['id'], run_id)
        self.assertEqual(self.client.get('/api/office/runs/not-present').status_code, 404)

    def test_invalid_controls_missing_consent_unconfigured_provider_and_arbitrary_question_rejected(self):
        self.login()
        for changes in ({'consent': False}, {'provider': 'anthropic'}, {'question': 'private-marker'},
                        {'request_key': 'not-uuid'}, {'controls': {'power_kw': -1}}):
            response = self.client.post('/api/office/runs', headers=HEADERS, json=self.payload() | changes)
            self.assertIn(response.status_code, (409, 422))
            self.assertNotIn('private-marker', response.text)

    def test_cancellation_is_terminal_and_capacity_is_bounded(self):
        async def waiting(*args):
            await asyncio.Event().wait()
        with TestClient(create_app(access_code='test-launch-code', origin=ORIGIN, providers=['openai'],
                                  office_analyzer=waiting), base_url=ORIGIN) as client:
            client.post('/api/session', headers=HEADERS, json={'code': 'test-launch-code'})
            run = client.post('/api/office/runs', headers=HEADERS, json=self.payload()).json()
            self.assertEqual(client.post('/api/office/runs', headers=HEADERS, json=self.payload()).status_code, 409)
            cancelled = client.delete('/api/office/runs/' + run['id'], headers=HEADERS).json()
            self.assertEqual(cancelled['status'], 'cancelled')
            self.assertIsNone(cancelled['result'])

    def test_signout_during_body_read_cannot_start_new_model_work(self):
        self.login()
        async def signout(request, contract):
            body = await read_contract(request, contract)
            request.app.state.sessions.close(request.cookies.get('energy_session'))
            return body
        with patch('energy_ai.web.office.read_contract', side_effect=signout):
            response = self.client.post('/api/office/runs', headers=HEADERS, json=self.payload())
        self.assertEqual(response.status_code, 401)
        self.login()
        self.assertEqual(self.client.get('/api/office/runs').json(), [])
