from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployment.publish_console import main
from tests.fixtures.deployment_environment import configured_environment


ENV = configured_environment() | dict(GITHUB_REPOSITORY='example/oci-energy-ai', GITHUB_RUN_ID='123',
                                      GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='a'*40)


class ConsolePublicationCommandTests(unittest.TestCase):
    def invoke(self, arguments, environment=None):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = main(arguments, environment=ENV if environment is None else environment)
        return status, output.getvalue() + error.getvalue()

    @patch('deployment.publish_console.DistributionClients')
    def test_missing_identity_or_extra_artifact_fails_before_cloud_access(self, clients):
        self.assertEqual(self.invoke([], {})[0], 2)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            (path/'image.tar').write_bytes(b'public')
            (path/'image-id.txt').write_text('sha256:'+'b'*64)
            (path/'unexpected.pdf').write_bytes(b'private-marker')
            status, output = self.invoke(['--artifact-dir', str(path)])
        self.assertEqual(status, 1)
        self.assertNotIn('private-marker', output)
        clients.assert_not_called()

    @patch('deployment.publish_console.publish_assets')
    @patch('deployment.publish_console.DistributionManager')
    @patch('deployment.publish_console.DistributionClients')
    def test_publication_needs_no_demo_id_password_or_model_keys_and_closes_clients(self, clients, manager, publish):
        publish.return_value = dict(release='a'*40, source_url='https://example.com/public.zip',
                                    template_sha256='c'*64, image_sha256='d'*64)
        environment = {k: v for k, v in ENV.items() if k != 'DEPLOYMENT_ID'}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            (path/'image.tar').write_bytes(b'checked public image')
            (path/'image-id.txt').write_text('sha256:'+'b'*64)
            status, output = self.invoke(['--artifact-dir', str(path)], environment)
        self.assertEqual(status, 0, output)
        self.assertIn('Distribution ready; preparing checked public assets.', output)
        self.assertIn('Public installer publication verified.', output)
        self.assertTrue(callable(publish.call_args.kwargs['emit']))
        self.assertEqual(publish.call_args.args[2:4], ('sha256:'+'b'*64, 'a'*40))
        self.assertTrue(manager.call_args.args[1].deployment_id.startswith('releases-'))
        self.assertNotIn(ENV['OCI_PRIVATE_KEY'], output)
        clients.return_value.__exit__.assert_called_once()

    @patch('deployment.publish_console.DistributionClients', side_effect=RuntimeError('private-marker'))
    def test_unexpected_error_is_fixed_without_raw_details(self, clients):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            (path/'image.tar').write_bytes(b'public')
            (path/'image-id.txt').write_text('sha256:'+'b'*64)
            status, output = self.invoke(['--artifact-dir', str(path)])
        self.assertEqual(status, 1)
        self.assertNotIn('private-marker', output)
        self.assertNotIn('Traceback', output)
