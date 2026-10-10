from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

from tests.fixtures.terraform_source import EXPECTED_MEMBERS


class BundleCommandTests(unittest.TestCase):
    def test_real_configuration_packages_without_local_files(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "terraform.zip"
            command = [sys.executable, "-m", "deployment.terraform_bundle",
                       "--output", str(output)]
            first = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertRegex(first.stdout, r"^SHA256 [a-f0-9]{64}\n$")
            with ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), list(EXPECTED_MEMBERS))
                self.assertIn(b'"9.8.0"', archive.read(".terraform.lock.hcl"))
            original = output.read_bytes()
            second = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(second.returncode, 2)
            self.assertIn("error:", second.stderr)
            self.assertNotIn("Traceback", second.stderr)
            self.assertEqual(output.read_bytes(), original)
