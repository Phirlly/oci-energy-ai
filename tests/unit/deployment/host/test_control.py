import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from infra.terraform.host.control import load_host_configuration, main
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
