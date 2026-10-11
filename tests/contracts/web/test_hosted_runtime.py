import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from contextlib import asynccontextmanager

from oci.secrets.models import Base64SecretBundleContentDetails

from energy_ai.web.hosted_configuration import HostedConfiguration, RuntimeConfigurationError
from energy_ai.web.hosted_runtime import HostedRuntime, load_runtime
from tests.fixtures.hosted_runtime import CONFIG, PASSWORD, SECRET, bundle


class HostedConfigurationTests(unittest.TestCase):
    def test_valid_configuration_and_strict_rejections(self):
        parsed = HostedConfiguration.from_bytes(json.dumps(CONFIG).encode())
        self.assertEqual(parsed.providers, ('oci',))
        for change in ({'version': True}, {'extra': 'private-marker'}, {'region': 'us-gov-ashburn-1'},
                       {'project': CONFIG['project'].replace('.iad.', '.phx.')},
                       {'secret_ids': {'demo_password': SECRET.replace('.oc1.', '.oc2.')}},
                       {'secret_ids': {'openai': SECRET}}, {'model_ids': {'openai': 'fixture'}},
                       {'model_ids': {'oci': '../private-marker'}}, {'origin': 'http://demo.example'}):
            with self.subTest(change=change), self.assertRaises(RuntimeConfigurationError) as error:
                HostedConfiguration.from_bytes(json.dumps(CONFIG | change).encode())
            self.assertNotIn('private-marker', str(error.exception))
        with self.assertRaises(RuntimeConfigurationError):
            HostedConfiguration.from_bytes(json.dumps(CONFIG | {
                'origin': 'http://127.0.0.1:8765', 'backend_host': None}).encode())
        for data in (b'{"version":1,"version":1}', b'x' * 16385, b'[]', b'\xff', b'{'):
            with self.subTest(data=data[:30]), self.assertRaises(RuntimeConfigurationError):
                HostedConfiguration.from_bytes(data)

    def test_file_read_is_bounded_and_missing_or_invalid_files_have_fixed_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runtime.json'
            with self.assertRaises(RuntimeConfigurationError):
                HostedConfiguration.load(path)
            path.write_bytes(json.dumps(CONFIG).encode())
            self.assertEqual(HostedConfiguration.load(path).origin, CONFIG['origin'])
            path.write_bytes(b' ' * 16385)
            with self.assertRaises(RuntimeConfigurationError):
                HostedConfiguration.load(path)


class VaultRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.signer = MagicMock()
        self.signer.region = 'us-ashburn-1'
        self.client = MagicMock()
        self.client.get_secret_bundle.return_value = bundle()
        self.signer_factory = self.enterContext(patch('energy_ai.web.hosted_runtime.InstancePrincipalsSecurityTokenSigner',
                                                     return_value=self.signer))
        self.client_factory = self.enterContext(patch('energy_ai.web.hosted_runtime.SecretsClient', return_value=self.client))

    def test_reads_current_in_memory_without_key_profile_or_environment_fallback(self):
        with patch('oci.config.from_file') as profile, patch.dict('os.environ', {'OPENAI_API_KEY': 'unrequested-key'}):
            runtime = load_runtime(HostedConfiguration.from_bytes(json.dumps(CONFIG).encode()))
        self.assertEqual(runtime.providers, ('oci',))
        self.assertEqual(runtime.password, PASSWORD)
        profile.assert_not_called()
        self.client.get_secret_bundle.assert_called_once_with(SECRET, stage='CURRENT')
        options = self.client_factory.call_args.kwargs
        self.assertEqual(options['service_endpoint'], 'https://secrets.vaults.us-ashburn-1.oci.oraclecloud.com')
        self.assertEqual(options['timeout'], (10, 30))
        self.assertEqual(type(options['retry_strategy']).__name__, 'NoneRetryStrategy')
        self.assertEqual(set(self.signer_factory.call_args.kwargs),
                         {'retry_strategy', 'federation_client_retry_strategy'})
        self.client.base_client.session.close.assert_called_once()
        runtime.close()

    def test_optional_provider_secret_is_required_once_configured_and_failures_are_private(self):
        configuration = CONFIG | {'secret_ids': {'demo_password': SECRET, 'openai': SECRET[:-1] + 'c'}}
        self.client.get_secret_bundle.side_effect = [bundle(), RuntimeError('private response or key')]
        with self.assertRaisesRegex(RuntimeConfigurationError, 'credentials') as error:
            load_runtime(HostedConfiguration.from_bytes(json.dumps(configuration).encode()))
        self.assertNotIn('private response', str(error.exception))
        self.client.base_client.session.close.assert_called_once()
        for name in ('federation_client', 'leaf_certificate_retriever', 'intermediate_certificate_retriever'):
            getattr(self.signer, name).requests_session.close.assert_called_once()

    def test_rejects_wrong_identity_stage_encoding_password_and_metadata_region(self):
        variants = [bundle(secret_id=SECRET[:-1] + 'z'), bundle(stages=['PREVIOUS']),
                    bundle(value='short'), bundle(value=' ' + PASSWORD),
                    bundle(secret_bundle_content=Base64SecretBundleContentDetails(content='not-base64')),
                    bundle(secret_bundle_content=Base64SecretBundleContentDetails(content='/w=='))]
        for response in variants:
            with self.subTest(response=response.data.secret_id), self.assertRaises(RuntimeConfigurationError):
                self.client.get_secret_bundle.return_value = response
                load_runtime(HostedConfiguration.from_bytes(json.dumps(CONFIG).encode()))
        self.signer.region = 'us-phoenix-1'
        self.client_factory.reset_mock()
        with self.assertRaises(RuntimeConfigurationError):
            load_runtime(HostedConfiguration.from_bytes(json.dumps(CONFIG).encode()))
        self.client_factory.assert_not_called()


class HostedProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_passes_only_explicit_identity_and_selected_vault_key(self):
        config = HostedConfiguration.from_bytes(json.dumps(CONFIG | {'secret_ids': {
            'demo_password': SECRET, 'openai': SECRET[:-1] + 'c', 'anthropic': SECRET[:-1] + 'd'}}).encode())
        runtime = HostedRuntime(config, MagicMock(), {'demo_password': PASSWORD,
            'openai': 'fixture-openai-key', 'anthropic': 'fixture-anthropic-key'})
        self.addCleanup(runtime.close)
        calls = []
        @asynccontextmanager
        async def model(provider, **options):
            calls.append((provider, options))
            yield object()
        with patch('energy_ai.web.hosted_runtime.open_model', model), patch.dict('os.environ', {
                'OPENAI_API_KEY': 'wrong-key', 'ANTHROPIC_API_KEY': 'wrong-key', 'OCI_PRIVATE_KEY': 'wrong-key'}):
            for provider in runtime.providers:
                async with runtime.model(provider):
                    pass
        self.assertIs(calls[0][1]['oci_auth'], runtime.auth)
        self.assertNotIn('oci_signer', calls[0][1])
        self.assertEqual(calls[1][1]['api_key'], 'fixture-openai-key')
        self.assertEqual(calls[2][1]['api_key'], 'fixture-anthropic-key')
        self.assertEqual(calls[0][1]['oci_project'], CONFIG['project'])
