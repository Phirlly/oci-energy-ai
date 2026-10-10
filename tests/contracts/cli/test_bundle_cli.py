from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from tests.fixtures.terraform_source import EXPECTED_MEMBERS


class BundleCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "terraform.zip"

    def run_cli(self):
        return subprocess.run([sys.executable, "-m", "deployment.terraform_bundle",
                               "--output", str(self.output)],
                              capture_output=True, text=True, timeout=15)

    def test_real_configuration_packages_without_local_files(self):
        process = self.run_cli()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertRegex(process.stdout, r"^SHA256 [a-f0-9]{64}\n$")
        with ZipFile(self.output) as archive:
            self.assertEqual(archive.namelist(), list(EXPECTED_MEMBERS))
            self.assertIn(b'"9.8.0"', archive.read(".terraform.lock.hcl"))

    def test_existing_output_is_rejected_and_preserved(self):
        self.output.write_bytes(b"preserve this existing archive")
        process = self.run_cli()
        self.assertEqual(process.returncode, 2)
        self.assertIn("error:", process.stderr)
        self.assertNotIn("Traceback", process.stderr)
        self.assertEqual(self.output.read_bytes(), b"preserve this existing archive")
