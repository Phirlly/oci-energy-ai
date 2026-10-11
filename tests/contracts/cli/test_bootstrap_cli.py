from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import subprocess
import sys
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from deployment.bootstrap import main
from tests.fixtures.deployment_environment import configured_environment
from tests.fixtures.terraform_source import EXPECTED_MEMBERS


ENVIRONMENT = configured_environment() | {
    "GITHUB_REPOSITORY": "example/oci-energy-ai", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
}


class BootstrapCommandTests(unittest.TestCase):
    def invoke(self, arguments, environment=None):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = main(arguments, environment=ENVIRONMENT if environment is None else environment)
        return status, output.getvalue(), error.getvalue()

    @patch("deployment.bootstrap.resource_manager_client")
    def test_missing_settings_report_names_without_authentication(self, client):
        status, output, error = self.invoke(["apply"], {})
        self.assertEqual(status, 2)
        self.assertIn("OCI_PRIVATE_KEY | missing", output)
        self.assertEqual(error, "")
        client.assert_not_called()

    @patch("deployment.bootstrap.ResourceManager")
    @patch("deployment.bootstrap.resource_manager_client")
    def test_apply_uses_allowlisted_bundle_and_reports_only_validated_outputs(self, client, manager):
        manager.return_value.apply.return_value = {"artifact_bucket_name": "example-bucket"}
        status, output, error = self.invoke(["apply"])
        self.assertEqual(status, 0, error)
        archive = manager.return_value.apply.call_args.args[0]
        with ZipFile(BytesIO(archive)) as bundle:
            self.assertEqual(bundle.namelist(), list(EXPECTED_MEMBERS))
        self.assertIn("Foundation apply succeeded", output)
        self.assertNotIn(ENVIRONMENT["OCI_PRIVATE_KEY"], output + error)

    @patch("deployment.bootstrap.build_bundle")
    @patch("deployment.bootstrap.ResourceManager")
    @patch("deployment.bootstrap.resource_manager_client")
    def test_destroy_requires_confirmation_and_never_packages_current_source(self, client, manager, bundle):
        status, output, error = self.invoke(["destroy", "--confirm", "wrong"])
        self.assertEqual(status, 2)
        self.assertIn("confirmation", error)
        client.assert_not_called()
        manager.return_value.destroy.return_value = True
        status, output, error = self.invoke(["destroy", "--confirm", "fixture-demo"])
        self.assertEqual(status, 0, error)
        manager.return_value.destroy.assert_called_once_with("fixture-demo")
        bundle.assert_not_called()
        self.assertIn("empty stack retained", output)

    @patch("deployment.bootstrap.resource_manager_client", side_effect=RuntimeError("private-marker"))
    def test_unexpected_failure_hides_raw_details_and_exits_nonzero(self, client):
        status, output, error = self.invoke(["apply"])
        self.assertEqual(status, 1)
        self.assertNotIn("private-marker", output + error)
        self.assertNotIn("Traceback", output + error)

    def test_help_and_missing_settings_work_in_fresh_process_without_local_profile(self):
        for arguments, expected in [(["--help"], 0), (["apply"], 2)]:
            with self.subTest(arguments=arguments):
                process = subprocess.run([sys.executable, "-m", "deployment.bootstrap", *arguments],
                                         env={}, capture_output=True, text=True, timeout=15)
                self.assertEqual(process.returncode, expected, process.stderr)
                self.assertNotIn("Traceback", process.stderr)
