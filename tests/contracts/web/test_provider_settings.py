import asyncio
from contextlib import asynccontextmanager
import json
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from energy_ai.web.app import create_app
from energy_ai.web.hosted_configuration import HostedConfiguration
from energy_ai.web.hosted_setup import HostedSetup
from energy_ai.web.setup_secrets import SetupError, SetupSecrets
from tests.fixtures.hosted_runtime import SECRET
from tests.fixtures.setup_runtime import CODE, COMPLETED, MemoryVault, SETTINGS_CONFIG

ORIGIN = SETTINGS_CONFIG['origin']
HEADERS = {'Host': SETTINGS_CONFIG['backend_host'], 'Origin': ORIGIN, 'x-energy-action': '1'}


def runtime(vault):
    return HostedSetup(HostedConfiguration.from_bytes(json.dumps(SETTINGS_CONFIG).encode()),
                       Mock(), SetupSecrets(vault, vault, SECRET))


class ProviderKeyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.vault = MemoryVault(COMPLETED)
        self.store = SetupSecrets(self.vault, self.vault, SECRET)
        self.now = 0
        self.store.monotonic = lambda: self.now
        self.store.sleep = lambda seconds: setattr(self, 'now', self.now + seconds)

    def test_add_rotate_remove_keep_and_noop_preserve_owner_password_and_tags(self):
        self.vault.value['password'] = ' énergie ☀ '
        first = self.store.update_keys(CODE, {'anthropic': 'new-key'})
        self.assertEqual(first['keys'], {'openai': 'invented-key', 'anthropic': 'new-key'})
        self.assertEqual(self.vault.writes[0][2], '1')
        result = self.store.update_keys(CODE, {'openai': 'rotated-key', 'anthropic': None})
        self.assertEqual(result, COMPLETED | {'password': ' énergie ☀ ', 'keys': {'openai': 'rotated-key'}})
        self.assertEqual(self.store.update_keys(CODE, {'openai': 'rotated-key'}), result)
        self.assertEqual(len(self.vault.writes), 2)
        self.assertEqual(self.vault.tags, {'application': 'oci-energy-ai', 'energy_ai_setup': 'complete'})

    def test_wrong_owner_legacy_invalid_and_oversized_updates_never_write(self):
        for code, changes in [('admin', {'openai': 'new-key'}), (CODE, {}),
                              (CODE, {'openai': ''}), (CODE, {'openai': 3}),
                              (CODE, {'other': 'private-marker'}), (CODE, {'openai': 'bad key'}),
                              (CODE, {'openai': 'x' * 4097}),
                              (CODE, {'openai': '"' * 4096, 'anthropic': '"' * 4096})]:
            with self.subTest(fields=list(changes)), self.assertRaises(SetupError) as raised:
                self.store.update_keys(code, changes)
            self.assertNotIn('private-marker', str(raised.exception))
        self.vault.value = {'version': 1, 'password': 'admin', 'keys': {}}
        with self.assertRaises(SetupError) as raised:
            self.store.update_keys(CODE, {'openai': 'new-key'})
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.vault.writes, [])

    def test_lost_response_waits_past_stale_completed_snapshot_and_never_replays(self):
        old = self.store.read()
        read, write = self.store.read, self.vault.update_secret
        def lost(*args, **kwargs):
            write(*args, **kwargs)
            raise TimeoutError('private-marker')
        reads = iter([old, old, SetupError()])
        def delayed():
            item = next(reads, None)
            if isinstance(item, Exception):
                raise item
            return item or read()
        with patch.object(self.store, 'read', side_effect=delayed), patch.object(
                self.vault, 'update_secret', side_effect=lost) as update:
            result = self.store.update_keys(CODE, {'openai': 'rotated-key'})
        update.assert_called_once()
        self.assertEqual(result['keys'], {'openai': 'rotated-key'})
        self.assertEqual(self.now, 4)

    def test_conflicting_etag_never_overwrites_winner_and_unknown_write_is_bounded(self):
        write = self.vault.update_secret
        def competitor(*args, **kwargs):
            self.vault.value = COMPLETED | {'keys': {'anthropic': 'winner-key'}}
            self.vault.version += 1
            return write(*args, **kwargs)
        with patch.object(self.vault, 'update_secret', side_effect=competitor):
            with self.assertRaises(SetupError) as raised:
                self.store.update_keys(CODE, {'openai': 'loser-key'})
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.vault.value['keys'], {'anthropic': 'winner-key'})
        with patch.object(self.vault, 'update_secret', side_effect=TimeoutError('private-marker')) as update:
            with self.assertRaises(SetupError) as raised:
                self.store.update_keys(CODE, {'openai': 'unconfirmed-key'})
        self.assertEqual(raised.exception.status, 503)
        self.assertNotIn('private-marker', str(raised.exception))
        self.assertEqual(self.now, 30)
        update.assert_called_once()


class ProviderSettingsApiTests(unittest.TestCase):
    def setUp(self):
        self.vault = MemoryVault(COMPLETED)
        self.runtime = runtime(self.vault)
        self.addCleanup(self.runtime.close)
        self.app = create_app(access_code=None, origin=ORIGIN, backend_host=HEADERS['Host'],
                              release='a' * 40, setup=self.runtime)
        self.client = self.enterContext(TestClient(self.app, base_url=ORIGIN, headers=HEADERS))
        self.body = {'owner_code': CODE, 'changes': {'anthropic': 'new-key'}}

    def login(self):
        self.assertEqual(self.client.post('/api/session', json={'code': 'admin'}).status_code, 200)

    def test_update_requires_session_owner_and_origin_and_never_discloses_settings(self):
        self.assertEqual(self.client.post('/api/settings', json=self.body).status_code, 401)
        self.login()
        self.assertTrue(self.client.get('/api/session').json()['settings_available'])
        for body, headers, status in [(self.body | {'owner_code': 'admin'}, HEADERS, 403),
                (self.body, HEADERS | {'Origin': 'https://wrong.example'}, 403),
                (self.body | {'changes': {'unknown': 'private-marker'}}, HEADERS, 422),
                (self.body | {'password': 'private-marker'}, HEADERS, 422)]:
            response = self.client.post('/api/settings', json=body, headers=headers)
            self.assertEqual(response.status_code, status, response.text)
            self.assertNotIn('private-marker', response.text)
        self.assertEqual(self.vault.writes, [])
        response = self.client.post('/api/settings', json=self.body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'saved': True})
        self.assertEqual(self.client.get('/api/session').json()['providers'], ['oci', 'openai', 'anthropic'])
        self.assertEqual(self.client.post('/api/setup', json={}).status_code, 422)
        restarted = runtime(self.vault)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.keys, {'openai': 'invented-key', 'anthropic': 'new-key'})
        self.assertEqual(restarted.password, 'admin')
        self.assertFalse(restarted.required)

    def test_update_retains_presenter_documents_and_attempts_share_login_limit(self):
        self.login()
        document = self.client.post('/api/example').json()
        self.assertEqual(self.client.post('/api/settings', json=self.body).status_code, 200)
        self.assertEqual(self.client.get('/api/documents').json()[0]['id'], document['id'])
        for _ in range(8):
            self.client.post('/api/settings', json=self.body | {'owner_code': 'wrong'})
        self.assertEqual(self.client.post('/api/settings', json=self.body).status_code, 429)
        self.assertEqual(len(self.vault.writes), 1)

    def test_legacy_completed_settings_cannot_enable_maintenance(self):
        self.runtime.close()
        legacy = runtime(MemoryVault({'version': 1, 'password': 'admin', 'keys': {}}))
        self.addCleanup(legacy.close)
        app = create_app(access_code=None, origin=ORIGIN, backend_host=HEADERS['Host'], release='a' * 40, setup=legacy)
        with TestClient(app, base_url=ORIGIN, headers=HEADERS) as client:
            client.post('/api/session', json={'code': 'admin'})
            self.assertFalse(client.get('/api/session').json()['settings_available'])
            self.assertEqual(client.post('/api/settings', json=self.body).status_code, 409)

    def test_session_that_expires_during_body_read_cannot_write(self):
        from energy_ai.web.requests import read_contract
        self.login()
        async def expires(request, contract):
            body = await read_contract(request, contract)
            self.app.state.sessions.close(request.cookies.get('energy_session'))
            return body
        with patch('energy_ai.web.settings.read_contract', expires):
            response = self.client.post('/api/settings', json=self.body)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.vault.writes, [])

    def test_conflict_refreshes_runtime_to_verified_winner_without_reopening_setup(self):
        self.login()
        write = self.vault.update_secret
        def competitor(*args, **kwargs):
            self.vault.value = COMPLETED | {'keys': {'anthropic': 'winner-key'}}
            self.vault.version += 1
            return write(*args, **kwargs)
        with patch.object(self.vault, 'update_secret', side_effect=competitor):
            response = self.client.post('/api/settings', json=self.body)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('winner-key', response.text)
        self.assertEqual(self.client.get('/api/session').json()['providers'], ['oci', 'anthropic'])
        self.assertEqual(self.client.get('/api/setup').json(), {'required': False})
        self.assertEqual(self.runtime.keys, {'anthropic': 'winner-key'})


class ProviderSettingsAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_update_retains_capacity_and_new_models_use_verified_key(self):
        vault = MemoryVault(COMPLETED)
        instance = runtime(vault)
        self.addCleanup(instance.close)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        write = vault.update_secret
        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError()
            return write(*args, **kwargs)
        with patch.object(vault, 'update_secret', side_effect=blocked):
            task = asyncio.create_task(instance.update_keys(CODE, {'openai': 'rotated-key'}))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(instance.keys['openai'], 'invented-key')
            with self.assertRaises(SetupError) as busy:
                await instance.update_keys(CODE, {'openai': 'rejected-key'})
            self.assertEqual(busy.exception.status, 409)
            release.set()
            await asyncio.wait_for(asyncio.shield(instance.pending), 3)
        calls = []
        @asynccontextmanager
        async def model(provider, **options):
            calls.append((provider, options['api_key']))
            yield object()
        with patch('energy_ai.web.hosted_runtime.open_model', model):
            async with instance.model('openai'):
                pass
        self.assertEqual(calls, [('openai', 'rotated-key')])
        self.assertEqual(len(vault.writes), 1)
