from pathlib import Path
import os
import shlex
import tempfile
import unittest

from infra.terraform.host import control
from infra.terraform.host.contracts import HostError
from infra.terraform.host.process import run_command


class BootstrapStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.marker = self.root / "bootstrap-stage"

    def test_known_stages_return_fixed_operator_guidance(self):
        for stage, guidance in (("packages", "package repositories"),
                                ("cli-repository", "CLI repository"),
                                ("cli-install", "CLI package"),
                                ("runtime", "Python, OCI CLI and Podman"),
                                ("permissions", "ocarun"),
                                ("firewall", "firewalld"),
                                ("service", "systemd")):
            with self.subTest(stage=stage):
                self.marker.write_bytes(stage.encode())
                error = control.bootstrap_error(self.root)
                self.assertIsInstance(error, HostError)
                self.assertIn("stopped during " + stage, str(error))
                self.assertIn(guidance, str(error))

    def test_missing_malformed_or_private_stage_never_appears_in_error(self):
        fallback = str(control.bootstrap_error(self.root))
        for content in (b"private-marker", b"packages\n", b"runtime\x00", b"\xff",
                        b"x" * 65, b"complete", b""):
            with self.subTest(size=len(content)):
                self.marker.write_bytes(content)
                self.assertEqual(str(control.bootstrap_error(self.root)), fallback)
        self.marker.unlink()
        self.marker.mkdir()
        self.assertEqual(str(control.bootstrap_error(self.root)), fallback)

    def test_real_script_first_command_failure_records_stage_and_failed_marker(self):
        script = Path("infra/terraform/host/bootstrap.sh").read_text()
        prefix, suffix = script.split("timeout 900 ", 1)
        # Permit only these inert operations before the intercepted first command.
        self.assertEqual(prefix, "#!/bin/bash\nset -euo pipefail\n"
                         "export PATH=/usr/sbin:/usr/bin:/sbin:/bin\numask 077\n"
                         "trap 'touch /etc/oci-energy-ai/failed' ERR\n\n"
                         "printf '%s' packages > /etc/oci-energy-ai/bootstrap-stage\n")
        self.assertTrue(suffix.startswith("dnf -y --setopt=timeout=30"))
        run_command(["/bin/bash", "-n", "infra/terraform/host/bootstrap.sh"], timeout=5)
        local = self.root / "bootstrap.sh"
        local.write_text("timeout() { return 17; }\n" + script.replace(
            "/etc/oci-energy-ai", shlex.quote(str(self.root))))
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with self.assertRaises(HostError):
                run_command(["/bin/bash", str(local)], timeout=5)
        finally:
            os.chdir(previous)
        self.assertEqual(self.marker.read_bytes(), b"packages")
        self.assertTrue((self.root / "failed").is_file())
        self.assertFalse((self.root / "ready").exists())
