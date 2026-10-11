from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.fixtures.deployment_environment import configured_environment


class DeploymentSetupCommandTests(unittest.TestCase):
    def run_cli(self, environment, *arguments, cwd=None):
        return subprocess.run(
            [sys.executable, "-m", "deployment.preflight", *arguments],
            env=environment, cwd=cwd, capture_output=True, text=True, timeout=15,
        )

    def test_complete_configuration_exits_zero_and_prints_limited_result(self):
        environment = configured_environment()
        process = self.run_cli(environment)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertIn("Configuration checks passed", process.stdout)
        self.assertIn("Live authentication, permissions and model calls were not checked",
                      process.stdout)
        for value in environment.values():
            self.assertNotIn(value, process.stdout)

    def test_missing_configuration_exits_two_and_lists_fields_without_traceback(self):
        process = self.run_cli({})
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stderr, "")
        self.assertIn("Configuration needs attention", process.stdout)
        for name in configured_environment():
            self.assertIn(name, process.stdout)
        self.assertNotIn("Traceback", process.stdout)

    def test_invalid_values_are_not_echoed_to_either_stream(self):
        environment = {**configured_environment(), "OCI_REGION": "sensitive-marker\n::error::x"}
        process = self.run_cli(environment)
        self.assertEqual(process.returncode, 2)
        self.assertIn("OCI_REGION", process.stdout)
        self.assertNotIn("sensitive-marker", process.stdout + process.stderr)
        self.assertNotIn("::error::", process.stdout + process.stderr)

    def test_local_dotenv_is_not_loaded_or_modified(self):
        repository = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temporary:
            dotenv = Path(temporary) / ".env"
            contents = "\n".join(f"{key}={value}" for key, value in configured_environment().items())
            dotenv.write_text(contents, encoding="utf-8")
            process = self.run_cli({"PYTHONPATH": str(repository)}, cwd=temporary)
            self.assertEqual(process.returncode, 2)
            self.assertIn("OCI_PRIVATE_KEY | missing", process.stdout)
            self.assertEqual(dotenv.read_text(encoding="utf-8"), contents)
            self.assertEqual(list(Path(temporary).iterdir()), [dotenv])

    def test_help_needs_no_configuration(self):
        process = self.run_cli({}, "--help")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("configuration", process.stdout)

    def test_application_mode_requires_password_and_does_not_print_it(self):
        environment = configured_environment()
        missing = self.run_cli(environment, "--application")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("DEMO_PASSWORD | missing", missing.stdout)
        for password, status in (("admin", 0), (" énergie solaire ", 0),
                                 ("private-marker\n", 2), ("x" * 201, 2)):
            with self.subTest(expected_exit=status):
                result = self.run_cli(environment | {"DEMO_PASSWORD": password}, "--application")
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertIn("DEMO_PASSWORD", result.stdout)
                self.assertNotIn(password, result.stdout)
