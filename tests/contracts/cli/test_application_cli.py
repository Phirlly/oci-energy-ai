from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployment.application import main
from tests.fixtures.deployment_environment import configured_environment


ENVIRONMENT = configured_environment() | dict(GITHUB_REPOSITORY='example/oci-energy-ai', GITHUB_RUN_ID='123',
    GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='a'*40, DEMO_PASSWORD='admin')


class ApplicationCommandTests(unittest.TestCase):
    def invoke(self, arguments, environment=None):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = main(arguments, environment=ENVIRONMENT if environment is None else environment)
        return status, output.getvalue(), error.getvalue()

    @patch('deployment.application.DeliveryClients')
    def test_missing_password_or_bad_confirmation_fails_before_authentication(self, clients):
        environment = dict(ENVIRONMENT)
        del environment['DEMO_PASSWORD']
        status, output, _ = self.invoke(['verify'], environment)
        self.assertEqual(status, 2)
        self.assertIn('DEMO_PASSWORD | missing', output)
        status, _, error = self.invoke(['destroy', '--confirm', 'wrong'])
        self.assertEqual(status, 2)
        self.assertIn('confirmation', error)
        clients.assert_not_called()

    @patch('deployment.application.Delivery')
    @patch('deployment.application.DeliveryClients')
    def test_apply_reads_exact_checked_artifact_and_only_reports_safe_result(self, clients, delivery):
        delivery.return_value.apply.return_value = dict(operation='apply', release='a'*40)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            (path/'image.tar').write_bytes(b'public checked archive')
            (path/'image-id.txt').write_text('sha256:'+'b'*64+'\n')
            status, output, error = self.invoke(['apply', '--artifact-dir', str(path)])
        self.assertEqual(status, 0, error)
        self.assertEqual(delivery.return_value.apply.call_args.args[1:], ('sha256:'+'b'*64, 'a'*40))
        self.assertNotIn(ENVIRONMENT['OCI_PRIVATE_KEY'], output + error)
        clients.return_value.__exit__.assert_called_once()

    @patch('deployment.application.DeliveryClients')
    def test_unknown_or_symlink_artifact_is_rejected_before_cloud_clients(self, clients):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            (path/'image.tar').write_bytes(b'fixture')
            (path/'image-id.txt').write_text('sha256:'+'b'*64)
            (path/'unexpected.txt').write_text('fixture')
            self.assertEqual(self.invoke(['apply', '--artifact-dir', str(path)])[0], 1)
            (path/'unexpected.txt').unlink()
            (path/'image.tar').unlink()
            (path/'image.tar').symlink_to(path/'image-id.txt')
            self.assertEqual(self.invoke(['apply', '--artifact-dir', str(path)])[0], 1)
        clients.assert_not_called()

    @patch('deployment.application.Delivery')
    @patch('deployment.application.DeliveryClients')
    def test_destroy_needs_no_provider_password_or_build_artifact(self, clients, delivery):
        environment = {k: v for k, v in ENVIRONMENT.items() if k not in {'DEMO_PASSWORD', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'}}
        delivery.return_value.destroy.return_value = dict(operation='destroy', stack='retained')
        status, _, error = self.invoke(['destroy', '--confirm', 'fixture-demo'], environment)
        self.assertEqual(status, 0, error)
        delivery.return_value.destroy.assert_called_once_with('fixture-demo')

    @patch('deployment.application.DeliveryClients', side_effect=RuntimeError('private-marker'))
    def test_unexpected_failure_has_fixed_error_and_no_raw_response_or_traceback(self, clients):
        status, output, error = self.invoke(['verify'])
        self.assertEqual(status, 1)
        self.assertNotIn('private-marker', output + error)
        self.assertNotIn('Traceback', error)

    @patch('deployment.application.Delivery')
    @patch('deployment.application.DeliveryClients')
    def test_verified_browser_target_is_written_without_credentials_or_progress(self, clients, delivery):
        result = dict(operation='verify', origin='https://demo.example.com', release='b'*40)
        delivery.return_value.verify.return_value = result
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'outputs'
            environment = ENVIRONMENT | {'GITHUB_OUTPUT': str(target)}
            status, _, error = self.invoke(['verify'], environment)
            self.assertEqual(status, 0, error)
            self.assertEqual(target.read_text(), 'origin=https://demo.example.com\nrelease='+'b'*40+'\n')
            target.unlink()
            delivery.return_value.destroy.return_value = dict(operation='destroy')
            self.assertEqual(self.invoke(['destroy', '--confirm', 'fixture-demo'], environment)[0], 0)
            self.assertFalse(target.exists())

    @patch('deployment.application.Delivery')
    @patch('deployment.application.DeliveryClients')
    def test_failed_or_malformed_verification_never_publishes_a_browser_target(self, clients, delivery):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'outputs'
            environment = ENVIRONMENT | {'GITHUB_OUTPUT': str(target)}
            valid = dict(operation='verify', origin='https://demo.example.com', release='b'*40)
            for change in ({'origin': 'http://demo.example.com'}, {'origin': 'https://demo.example.com\nx=value'},
                           {'origin': 'https://demo.example.com/path'}, {'origin': 'https://user@demo.example.com'},
                           {'release': 'b'*40+'\nx=value'}, {'release': 'main'}, {'operation': 'apply'}):
                with self.subTest(change=change):
                    delivery.return_value.verify.return_value = valid | change
                    self.assertEqual(self.invoke(['verify'], environment)[0], 1)
                    self.assertFalse(target.exists())
            delivery.return_value.verify.side_effect = RuntimeError('private-marker')
            status, output, error = self.invoke(['verify'], environment)
            self.assertEqual(status, 1)
            self.assertFalse(target.exists())
            self.assertNotIn('private-marker', output + error)
