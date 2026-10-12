import base64
import json
import unittest
from unittest.mock import Mock, patch

from oci.exceptions import ServiceError
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner
from oci.retry import NoneRetryStrategy
from oci.secrets import SecretsClient
from oci.vault import VaultsClient

from energy_ai.web.setup_secrets import AlreadyConfigured, SetupError, SetupSecrets
from tests.fixtures.hosted_runtime import SECRET, bundle
from tests.fixtures.setup_runtime import CODE, MemoryVault, PENDING


class SetupPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.vault = MemoryVault()
        self.store = SetupSecrets(self.vault, self.vault, SECRET)
        self.now, self.delays = 0, []
        self.store.monotonic = lambda: self.now
        self.store.sleep = self.advance

    def advance(self, seconds):
        self.delays.append(seconds)
        self.now += seconds

    def test_claim_replaces_current_once_preserving_exact_password_and_optional_keys(self):
        password = ' énergie solaire ☀ '
        result = self.store.complete(CODE, password, {'openai': 'invented-key'})
        self.assertEqual(result, {'version': 2, 'owner_code': CODE, 'password': password,
                                  'keys': {'openai': 'invented-key'}})
        self.assertEqual(len(self.vault.writes), 1)
        identity, details, guard = self.vault.writes[0]
        self.assertEqual((identity, guard), (SECRET, '1'))
        self.assertFalse(details.enable_auto_generation)
        self.assertEqual(details.secret_content.stage, 'CURRENT')
        self.assertIsNone(details.current_version_number)
        self.assertEqual(details.freeform_tags, {'application': 'oci-energy-ai', 'energy_ai_setup': 'complete'})
        self.assertEqual(json.loads(base64.b64decode(details.secret_content.content)), result)
        self.assertEqual(self.store.read().value, result)

    def test_wrong_code_invalid_fields_and_replay_never_overwrite_configuration(self):
        for code, password, keys in [(CODE + ' ', 'admin', {}), (CODE, ' ', {}),
                                     (CODE, 'x' * 201, {}), (CODE, 'admin', {'openai': 'bad key'}),
                                     (CODE, 'admin', {'unknown': 'private-marker'})]:
            with self.subTest(code=code == CODE), self.assertRaises(SetupError) as raised:
                self.store.complete(code, password, keys)
            self.assertNotIn('private-marker', str(raised.exception))
        self.assertEqual(self.vault.writes, [])
        self.store.complete(CODE, 'admin', {})
        with self.assertRaises(AlreadyConfigured) as raised:
            self.store.complete(CODE, 'other', {})
        self.assertEqual(raised.exception.value['password'], 'admin')
        self.assertEqual(len(self.vault.writes), 1)

    def test_lost_response_is_verified_without_replaying_the_write(self):
        original = self.vault.update_secret
        pending = self.store.read()
        read = self.store.read
        def committed(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError('private-marker')
        outcomes = iter([pending, SetupError(), pending])
        def delayed():
            outcome = next(outcomes, None)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome or read()
        with patch.object(self.vault, 'update_secret', side_effect=committed) as update, patch.object(
                self.store, 'read', side_effect=delayed):
            self.assertEqual(self.store.complete(CODE, 'admin', {})['password'], 'admin')
        update.assert_called_once()
        self.assertEqual(self.delays, [2, 2])

    def test_delayed_metadata_is_confirmed_after_one_write(self):
        original = self.vault.get_secret
        after_write = 0
        def metadata(*args, **kwargs):
            nonlocal after_write
            response = original(*args, **kwargs)
            if self.vault.writes:
                after_write += 1
                if after_write <= 2:  # Update response, then the first confirmation read.
                    response.data.lifecycle_state = 'UPDATING'
            return response
        with patch.object(self.vault, 'get_secret', side_effect=metadata):
            self.assertEqual(self.store.complete(CODE, 'admin', {})['password'], 'admin')
        self.assertEqual(self.delays, [2])
        self.assertEqual(len(self.vault.writes), 1)

    def test_unavailable_or_stale_bundle_is_never_accepted_as_confirmation(self):
        original = self.vault.get_secret_bundle
        failures = iter([ServiceError(404, 'NotFound', {}, 'private-marker'), 'PREVIOUS', 'CURRENT'])
        def content(*args, **kwargs):
            response = original(*args, **kwargs)
            if self.vault.writes:
                outcome = next(failures)
                if isinstance(outcome, Exception):
                    raise outcome
                response.data.stages = [outcome]
            return response
        with patch.object(self.vault, 'get_secret_bundle', side_effect=content):
            self.assertEqual(self.store.complete(CODE, 'admin', {})['password'], 'admin')
        self.assertEqual(self.delays, [2, 2])
        self.assertEqual(len(self.vault.writes), 1)

    def test_persistent_invalid_bundle_exhausts_confirmation_window_privately(self):
        original = self.vault.get_secret_bundle
        def content(*args, **kwargs):
            response = original(*args, **kwargs)
            if self.vault.writes:
                response.data.secret_id = SECRET + 'private-marker'
            return response
        with patch.object(self.vault, 'get_secret_bundle', side_effect=content) as read:
            with self.assertRaises(SetupError) as raised:
                self.store.complete(CODE, 'admin', {})
        self.assertEqual(raised.exception.status, 503)
        self.assertNotIn('private-marker', str(raised.exception))
        self.assertEqual(read.call_count, 16)  # Initial authentication plus 15 confirmations.
        self.assertEqual(self.now, 30)
        self.assertEqual(self.delays, [2] * 15)
        self.assertEqual(len(self.vault.writes), 1)

    def test_confirmation_attempt_limit_applies_even_if_clock_does_not_advance(self):
        pending = self.store.read()
        self.store.sleep = self.delays.append
        with patch.object(self.store, 'read', return_value=pending) as read:
            with self.assertRaises(SetupError):
                self.store.complete(CODE, 'admin', {})
        self.assertEqual(read.call_count, 17)  # Authentication plus at most 16 confirmations.
        self.assertEqual(self.delays, [2] * 15)
        self.assertEqual(len(self.vault.writes), 1)

    def test_slow_confirmation_or_sleep_cannot_admit_a_read_after_deadline(self):
        for slow_read in (True, False):
            with self.subTest(slow_read=slow_read):
                self.vault = MemoryVault()
                self.store = SetupSecrets(self.vault, self.vault, SECRET)
                self.now, self.delays = 0, []
                self.store.monotonic = lambda: self.now
                self.store.sleep = self.advance
                pending = self.store.read()
                def read():
                    if self.vault.writes and slow_read:
                        self.now += 31
                    return pending
                if not slow_read:
                    self.store.sleep = lambda seconds: self.advance(seconds + 30)
                with patch.object(self.store, 'read', side_effect=read) as confirm:
                    with self.assertRaises(SetupError):
                        self.store.complete(CODE, 'admin', {})
                self.assertEqual(confirm.call_count, 2)
                self.assertEqual(len(self.vault.writes), 1)
                self.assertEqual(self.delays, [] if slow_read else [32])

    def test_escaped_maximum_keys_cannot_commit_a_payload_that_exceeds_read_limit(self):
        keys = {'openai': '"' * 4096, 'anthropic': '"' * 4096}
        encoded = json.dumps({'version': 1, 'password': 'admin', 'keys': keys},
                             sort_keys=True, separators=(',', ':')).encode()
        self.assertGreater(len(encoded), 16384)
        with self.assertRaises(SetupError) as raised:
            self.store.complete(CODE, 'admin', keys)
        self.assertEqual(raised.exception.status, 422)
        self.assertEqual(self.vault.writes, [])
        self.assertEqual(self.store.read().value, PENDING)

    def test_uncommitted_or_unreadable_write_fails_privately_without_retry(self):
        for failure in (TimeoutError('private-marker'), ServiceError(403, 'Forbidden', {}, 'private-marker')):
            with self.subTest(failure=type(failure).__name__), patch.object(
                    self.vault, 'update_secret', side_effect=failure) as update:
                with self.assertRaises(SetupError) as raised:
                    self.store.complete(CODE, 'admin', {})
                self.assertNotIn('private-marker', str(raised.exception))
                update.assert_called_once()
            self.assertEqual(self.vault.value, PENDING)

    def test_stale_claim_cannot_overwrite_a_different_completed_configuration(self):
        original = self.vault.update_secret
        def competitor(secret_id, details, **kwargs):
            self.vault.value = {'version': 1, 'password': 'winner', 'keys': {}}
            self.vault.tags['energy_ai_setup'] = 'complete'
            self.vault.version += 1
            return original(secret_id, details, **kwargs)
        with patch.object(self.vault, 'update_secret', side_effect=competitor) as update:
            with self.assertRaises(AlreadyConfigured) as raised:
                self.store.complete(CODE, 'loser', {})
        self.assertEqual(raised.exception.value['password'], 'winner')
        update.assert_called_once()


class SetupReadContracts(unittest.TestCase):
    def setUp(self):
        self.vault = MemoryVault()
        self.store = SetupSecrets(self.vault, self.vault, SECRET)

    def test_reads_exact_metadata_version_and_requires_current_identity(self):
        with patch.object(self.vault, 'get_secret_bundle', wraps=self.vault.get_secret_bundle) as read:
            self.assertEqual(self.store.read().value, PENDING)
        self.assertEqual(read.call_args.kwargs['version_number'], 1)
        for change in ({'version_number': 2}, {'stages': ['PREVIOUS']}, {'secret_id': SECRET + 'z'}):
            response = bundle(value=json.dumps(PENDING), **change)
            with self.subTest(change=change), patch.object(self.vault, 'get_secret_bundle', return_value=response):
                with self.assertRaises(SetupError):
                    self.store.read()

    def test_malformed_or_reopened_claim_state_fails_closed(self):
        complete = {'version': 1, 'password': 'admin', 'keys': {}}
        for value, marker in [(PENDING, 'complete'), (complete, None), (PENDING, 'unknown'),
                              (PENDING | {'version': True}, None),
                              (PENDING | {'setup_code': ''}, None),
                              (complete | {'keys': {'openai': ''}}, 'complete')]:
            self.vault.value, self.vault.tags = value, {}
            if marker is not None:
                self.vault.tags['energy_ai_setup'] = marker
            with self.subTest(marker=marker), self.assertRaises(SetupError):
                self.store.read()

    def test_completed_legacy_and_owner_settings_are_strict_and_cannot_reopen_claim(self):
        from tests.fixtures.setup_runtime import COMPLETED
        for value in ({'version': 1, 'password': 'admin', 'keys': {}}, COMPLETED):
            self.vault = MemoryVault(value)
            self.store = SetupSecrets(self.vault, self.vault, SECRET)
            self.assertEqual(self.store.read().value, value)
        for value in (COMPLETED | {'owner_code': ''}, COMPLETED | {'version': 1},
                      {key: val for key, val in COMPLETED.items() if key != 'owner_code'},
                      PENDING | {'version': 2}, COMPLETED | {'extra': 'private-marker'}):
            self.vault.value = value
            with self.subTest(fields=list(value)), self.assertRaises(SetupError):
                self.store.read()

    def test_duplicate_oversized_or_invalid_json_and_missing_metadata_are_rejected(self):
        for raw in ('{"version":1,"version":1}', 'x' * 24577, '[]', '{'):
            with self.subTest(raw=raw[:20]), patch.object(
                    self.vault, 'get_secret_bundle', return_value=bundle(value=raw)):
                with self.assertRaises(SetupError):
                    self.store.read()
        for field, value in [('id', SECRET + 'x'), ('lifecycle_state', 'UPDATING'),
                             ('current_version_number', None), ('current_version_number', True)]:
            metadata = self.vault.get_secret(SECRET)
            setattr(metadata.data, field, value)
            with self.subTest(field=field), patch.object(self.vault, 'get_secret', return_value=metadata):
                with self.assertRaises(SetupError):
                    self.store.read()
        metadata = self.vault.get_secret(SECRET)
        metadata.headers.clear()
        with patch.object(self.vault, 'get_secret', return_value=metadata), self.assertRaises(SetupError):
            self.store.read()


class SetupSdkRequests(unittest.TestCase):
    def test_native_401_recovery_preserves_original_conditional_write_guard(self):
        from oci.response import Response
        from oci.vault.models import UpdateSecretDetails
        signer = Mock(spec=InstancePrincipalsSecurityTokenSigner)
        vault = VaultsClient({'region': 'us-ashburn-1'}, signer=signer, retry_strategy=NoneRetryStrategy())
        self.addCleanup(vault.base_client.session.close)
        attempts = []
        def send(request, *args):
            attempts.append((request.method, request.header_params['if-match']))
            if len(attempts) == 1:
                raise ServiceError(401, 'NotAuthenticated', {}, 'private-marker')
            return Response(200, {}, None, None)
        with patch.object(vault.base_client, 'request', side_effect=send):
            vault.update_secret(SECRET, UpdateSecretDetails(), if_match='original-etag',
                                retry_strategy=NoneRetryStrategy())
        self.assertEqual(attempts, [('PUT', 'original-etag'), ('PUT', 'original-etag')])
        signer.refresh_security_token.assert_called_once()

    def test_real_sdk_translates_version_guard_and_current_content_without_retries(self):
        memory = MemoryVault()
        signer = Mock(spec=InstancePrincipalsSecurityTokenSigner)
        vault = VaultsClient({'region': 'us-ashburn-1'}, signer=signer, retry_strategy=NoneRetryStrategy())
        bundles = SecretsClient({'region': 'us-ashburn-1'}, signer=signer, retry_strategy=NoneRetryStrategy())
        store = SetupSecrets(vault, bundles, SECRET)
        self.addCleanup(store.close)
        def control(**request):
            if request['operation_name'] == 'get_secret':
                return memory.get_secret(SECRET)
            return memory.update_secret(SECRET, request['body'], if_match=request['header_params']['if-match'])
        def content(**request):
            return memory.get_secret_bundle(SECRET, version_number=request['query_params']['versionNumber'])
        with patch.object(vault.base_client, 'call_api', side_effect=control) as write, patch.object(
                bundles.base_client, 'call_api', side_effect=content) as read:
            self.assertEqual(store.complete(CODE, 'admin', {})['password'], 'admin')
        updates = [call.kwargs for call in write.call_args_list if call.kwargs['operation_name'] == 'update_secret']
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]['header_params']['if-match'], '1')
        self.assertFalse(updates[0]['body'].enable_auto_generation)
        self.assertEqual(updates[0]['body'].secret_content.stage, 'CURRENT')
        self.assertEqual([call.kwargs['query_params'] for call in read.call_args_list],
                         [{'versionNumber': 1}, {'versionNumber': 2}])
