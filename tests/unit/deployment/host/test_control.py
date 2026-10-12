import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from infra.terraform.host.control import load_host_configuration, main, serve
from infra.terraform.host.contracts import HostError
from tests.fixtures.host_release import HOST_DIGEST


class FixedHostControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "host.json"
        self.config = {"version": 1, "host_digest": HOST_DIGEST, "region": "us-ashburn-1",
                       "namespace": "example", "bucket": "oci-energy-ai-demo-artifacts"}
        self.path.write_text(json.dumps(self.config))

    def test_host_configuration_accepts_only_fixed_nonsecret_fields(self):
        self.assertEqual(load_host_configuration(self.path), self.config)
        for changes in ({"bucket": "--private-marker"}, {"version": True}, {"password": "private-marker"}):
            self.path.write_text(json.dumps(dict(self.config, **changes)))
            with self.assertRaises(HostError) as raised:
                load_host_configuration(self.path)
            self.assertNotIn("private-marker", str(raised.exception))

    def test_console_configuration_has_no_private_storage_and_rejects_mixed_versions(self):
        console = {"version": 2, "host_digest": HOST_DIGEST, "region": "us-ashburn-1"}
        self.path.write_text(json.dumps(console))
        self.assertEqual(load_host_configuration(self.path), console)
        for invalid in (dict(self.config, version=2), dict(console, version=1),
                        dict(console, version=3), dict(console, bucket="private-marker"),
                        dict(console, region="../private-marker")):
            self.path.write_text(json.dumps(invalid))
            with self.subTest(fields=list(invalid)), self.assertRaises(HostError) as raised:
                load_host_configuration(self.path)
            self.assertNotIn("private-marker", str(raised.exception))

    @patch("infra.terraform.host.control.os.geteuid", return_value=0)
    def test_console_refuses_github_operations_before_constructing_runtime(self, uid):
        self.path.write_text(json.dumps({"version": 2, "host_digest": HOST_DIGEST, "region": "us-ashburn-1"}))
        (self.root / "ready").touch()
        with patch("infra.terraform.host.control.HostState") as state, patch(
                "infra.terraform.host.control.ObjectDownload") as download:
            for arguments in (["activate", "b" * 64], ["rollback"]):
                with self.subTest(operation=arguments[0]), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(arguments, config_path=self.path), 2)
                self.assertIn("Console installer", json.loads(output.getvalue())["detail"])
            state.assert_not_called()
            download.assert_not_called()

    @patch("infra.terraform.host.control.os.geteuid", return_value=0)
    def test_console_status_stop_and_service_start_need_no_storage_configuration(self, uid):
        console = {"version": 2, "host_digest": HOST_DIGEST, "region": "us-ashburn-1"}
        self.path.write_text(json.dumps(console))
        (self.root / "ready").touch()
        from infra.terraform.host.state import HostState
        state = HostState(self.root / "state", self.root / "run", HOST_DIGEST)
        with patch("infra.terraform.host.control.HostState", return_value=state), patch(
                "infra.terraform.host.control.HostService") as service, patch(
                "infra.terraform.host.control.ObjectDownload") as download:
            for operation in ("status", "stop"):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main([operation], config_path=self.path), 0)
                self.assertEqual(json.loads(output.getvalue())["status"], "ready")
            service.return_value.stop.assert_called_once()
            download.assert_not_called()
        with patch("infra.terraform.host.control.load_host_configuration",
                   side_effect=lambda: load_host_configuration(self.path)), patch(
                "infra.terraform.host.control.HostState") as host, patch(
                "infra.terraform.host.control.container_arguments", return_value=["/usr/bin/podman", "run"]) as args, patch(
                "infra.terraform.host.control.os.execve") as execute:
            host.return_value.selected.return_value = "b" * 64
            serve()
            args.assert_called_once_with(host.return_value, "b" * 64)
            self.assertEqual(execute.call_args.args[:2], ("/usr/bin/podman", ["/usr/bin/podman", "run"]))

    @patch("infra.terraform.host.control.os.geteuid", return_value=0)
    def test_invalid_command_never_echoes_supplied_argument_or_constructs_runtime(self, uid):
        output = io.StringIO()
        with patch("infra.terraform.host.control.HostState") as state, contextlib.redirect_stdout(output):
            result = main(["activate", "private-marker"], config_path=self.path)
        self.assertEqual(result, 2)
        self.assertNotIn("private-marker", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "error")
        state.assert_not_called()

    @patch("infra.terraform.host.control.os.geteuid", return_value=1000)
    def test_nonroot_caller_cannot_start_host_operations(self, uid):
        with patch("infra.terraform.host.control.HostState") as state, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["status"], config_path=self.path), 2)
        state.assert_not_called()

    @patch("infra.terraform.host.control.os.geteuid", return_value=0)
    def test_failed_bootstrap_status_has_safe_phase_guidance_without_starting_runtime(self, uid):
        (self.root / "failed").touch()
        (self.root / "bootstrap-stage").write_bytes(b"permissions")
        with patch("infra.terraform.host.control.HostState") as state, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["status"], config_path=self.path), 2)
        self.assertIn("stopped during permissions", json.loads(output.getvalue())["detail"])
        state.assert_not_called()
