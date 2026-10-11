import asyncio
import json
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from energy_ai.web.app import create_app
from energy_ai.web.hosted_configuration import HostedConfiguration
from energy_ai.web.hosted_setup import HostedSetup
from energy_ai.web.setup_secrets import SetupError, SetupSecrets
from tests.fixtures.setup_runtime import CODE, MemoryVault, SETTINGS_CONFIG
from tests.fixtures.hosted_runtime import SECRET

ORIGIN = SETTINGS_CONFIG['origin']
HEADERS = {'Host': SETTINGS_CONFIG['backend_host'], 'Origin': ORIGIN, 'x-energy-action': '1'}
BODY = {'setup_code': CODE, 'password': 'admin', 'openai_key': 'invented-api-key'}


def runtime(vault):
    return HostedSetup(HostedConfiguration.from_bytes(json.dumps(SETTINGS_CONFIG).encode()),
                       Mock(), SetupSecrets(vault, vault, SECRET))


class FirstRunApiTests(unittest.TestCase):
    def setUp(self):
        self.vault = MemoryVault()
        self.runtime = runtime(self.vault)
        self.addCleanup(self.runtime.close)
        self.app = create_app(access_code=None, origin=ORIGIN, backend_host=HEADERS['Host'],
                              release='a' * 40, setup=self.runtime)
        self.client = self.enterContext(TestClient(self.app, base_url=ORIGIN, headers=HEADERS))

    def test_setup_then_login_exposes_saved_providers_and_survives_restart(self):
        status = self.client.get('/api/setup')
        self.assertEqual(status.json(), {'required': True})
        self.assertEqual(status.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get('/healthz').json()['status'], 'setup_required')
        self.assertEqual(self.client.post('/api/session', json={'code': 'admin'}).status_code, 503)
        self.assertEqual(self.client.get('/api/office').status_code, 401)
        complete = self.client.post('/api/setup', json=BODY)
        self.assertEqual(complete.status_code, 200, complete.text)
        self.assertEqual(complete.json(), {'required': False})
        self.assertEqual(self.client.get('/api/session').status_code, 401)
        self.assertEqual(self.client.post('/api/session', json={'code': 'admin'}).status_code, 200)
        self.assertEqual(self.client.get('/api/session').json()['providers'], ['oci', 'openai'])
        self.assertEqual(self.client.get('/api/session').json()['models']['openai'], 'public-model-fixture')
        self.assertEqual(self.client.get('/healthz').json()['status'], 'ready')
        self.assertEqual(self.client.post('/api/setup', json=BODY | {'password': 'overwrite'}).status_code, 409)
        self.assertEqual(len(self.vault.writes), 1)
        restarted = runtime(self.vault)
        self.addCleanup(restarted.close)
        self.assertFalse(restarted.required)
        self.assertEqual(restarted.password, 'admin')
        self.assertEqual(restarted.providers, ['oci', 'openai'])

    def test_wrong_origin_code_and_malformed_inputs_are_private_and_cannot_create_session(self):
        bad_origin = self.client.post('/api/setup', headers=HEADERS | {'Origin': 'https://wrong.example'}, json=BODY)
        self.assertEqual(bad_origin.status_code, 403)
        cases = [(BODY | {'setup_code': 'wrong-private-marker'}, 403),
                 (BODY | {'password': ' '}, 422), (BODY | {'openai_key': 'private marker'}, 422),
                 (BODY | {'password': 'x' * 201}, 422), (BODY | {'extra': 'private-marker'}, 422)]
        for body, status in cases:
            with self.subTest(status=status):
                response = self.client.post('/api/setup', json=body)
                self.assertEqual(response.status_code, status)
                self.assertNotIn('private', response.text)
        self.assertEqual(self.vault.writes, [])
        self.assertEqual(self.client.get('/api/session').status_code, 401)

    def test_setup_and_login_share_attempt_limit_and_regular_installs_disable_setup(self):
        for _ in range(5):
            self.client.post('/api/setup', json=BODY | {'setup_code': 'wrong'})
            self.client.post('/api/session', json={'code': 'admin'})
        self.assertEqual(self.client.post('/api/setup', json=BODY).status_code, 429)
        regular = create_app(access_code='admin', origin='http://127.0.0.1:8765')
        with TestClient(regular, base_url='http://127.0.0.1:8765') as client:
            self.assertEqual(client.get('/api/setup').json(), {'required': False})
            self.assertEqual(client.post('/api/setup', headers={'Origin': 'http://127.0.0.1:8765',
                'x-energy-action': '1'}, json=BODY).status_code, 409)


class SetupAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_caller_does_not_release_write_capacity_or_discard_completion(self):
        vault = MemoryVault()
        instance = runtime(vault)
        self.addCleanup(instance.close)
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = vault.update_secret
        def blocked(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise TimeoutError()
            return original(*args, **kwargs)
        with patch.object(vault, 'update_secret', side_effect=blocked) as update:
            caller = asyncio.create_task(instance.complete(CODE, 'admin', {}))
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            with self.assertRaises(SetupError) as busy:
                await instance.complete(CODE, 'overwrite', {})
            self.assertEqual(busy.exception.status, 409)
            release.set()
            await asyncio.wait_for(asyncio.shield(instance.pending), 3)
        update.assert_called_once()
        self.assertFalse(instance.required)
        self.assertEqual(instance.password, 'admin')

    async def test_close_is_ordered_after_active_write_and_prevents_new_work(self):
        vault = MemoryVault()
        instance = runtime(vault)
        started, release, closed = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = vault.update_secret
        def blocked(*args, **kwargs):
            started.set()
            release.wait(5)
            return original(*args, **kwargs)
        vault.base_client.session.close.side_effect = closed.set
        with patch.object(vault, 'update_secret', side_effect=blocked):
            caller = asyncio.create_task(instance.complete(CODE, 'admin', {}))
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            instance.close()
            self.assertFalse(closed.is_set())
            with self.assertRaises(SetupError):
                await instance.complete(CODE, 'other', {})
            release.set()
            with self.assertRaises(SetupError):
                await caller
            self.assertTrue(await asyncio.to_thread(closed.wait, 2))
        self.assertEqual(instance.password, '')
