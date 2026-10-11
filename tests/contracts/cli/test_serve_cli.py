from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import MagicMock, patch

from energy_ai.web import serve
from energy_ai.web.hosted_configuration import HostedConfiguration
from tests.fixtures.hosted_runtime import CONFIG, PASSWORD
from tests.fixtures.setup_runtime import SETTINGS_CONFIG


class HostedEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.directory)
        (self.root / 'frontend/dist').mkdir(parents=True)
        (self.root / 'frontend/dist/index.html').write_text('public fixture')
        self.configuration = self.root / 'runtime.json'
        self.configuration.write_text(json.dumps(CONFIG))
        self.release = self.root / 'release.txt'
        self.release.write_text('b' * 40 + '\n')
        self.runtime = MagicMock()
        self.runtime.password = PASSWORD
        self.runtime.providers = ('oci',)
        self.runtime.config = HostedConfiguration.from_bytes(json.dumps(CONFIG).encode())
        self.enterContext(patch.object(serve, 'APP_ROOT', self.root))
        self.loader = self.enterContext(patch('energy_ai.web.hosted_runtime.load_runtime', return_value=self.runtime))
        self.server = self.enterContext(patch('uvicorn.run'))
        self.output, self.error = StringIO(), StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.error))
        self.enterContext(patch.dict(os.environ, {'OCI_METADATA_BASE_URL': 'https://private-marker',
            'OPENAI_API_KEY': 'private-marker', 'HTTPS_PROXY': 'https://private-marker'}))
        self.enterContext(patch('logging.disable'))

    def invoke(self):
        return serve.main(configuration_path=self.configuration, release_path=self.release,
                          database_path=self.root / 'office.sqlite3')

    def test_environment_is_isolated_before_runtime_load_and_single_worker_serves(self):
        import builtins
        original = builtins.__import__
        seen = []
        def inspect_import(name, *args, **kwargs):
            if name == 'energy_ai.web.hosted_runtime':
                seen.append(dict(os.environ))
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=inspect_import):
            self.assertEqual(self.invoke(), 0)
        self.assertTrue(seen)
        for environment in seen:
            self.assertNotIn('OCI_METADATA_BASE_URL', environment)
            self.assertNotIn('OPENAI_API_KEY', environment)
            self.assertNotIn('HTTPS_PROXY', environment)
        options = self.server.call_args.kwargs
        self.assertEqual((options['host'], options['port'], options['workers']), ('0.0.0.0', 8080, 1))
        self.assertFalse(options['proxy_headers'])
        self.assertFalse(options['access_log'])
        self.runtime.close.assert_called_once()
        self.assertNotIn(PASSWORD, self.output.getvalue() + self.error.getvalue())

    def test_startup_and_server_failures_are_fixed_and_initialized_runtime_is_closed(self):
        self.server.side_effect = RuntimeError('private-marker')
        self.assertEqual(self.invoke(), 2)
        self.runtime.close.assert_called_once()
        self.assertNotIn('private-marker', self.error.getvalue())
        self.assertNotIn('Traceback', self.error.getvalue())

    def test_version_two_hands_setup_runtime_to_app_without_a_temporary_password(self):
        self.configuration.write_text(json.dumps(SETTINGS_CONFIG))
        self.runtime.password = ''
        with patch('energy_ai.web.app.create_app') as create:
            self.assertEqual(self.invoke(), 0)
        self.assertIs(create.call_args.kwargs['setup'], self.runtime)
        self.assertEqual(create.call_args.kwargs['access_code'], '')

    def test_invalid_image_release_fails_before_loading_secrets(self):
        for content in ('../private-marker', 'b' * 40 + '\n private-marker'):
            self.release.write_text(content)
            self.assertEqual(self.invoke(), 2)
        self.loader.assert_not_called()
        self.server.assert_not_called()

    def test_first_import_in_clean_interpreter_is_isolated_before_sdk_loading(self):
        fixture = Path(__file__).resolve().parents[2] / 'fixtures/hosted_process.py'
        result = subprocess.run([sys.executable, '-I', '-B', str(fixture), str(self.root / 'missing.json')],
                                env=dict(os.environ), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'isolated-import-verified')
