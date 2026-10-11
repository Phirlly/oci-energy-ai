import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from infra.terraform.host.contracts import HostError
from infra.terraform.host.process import run_command
from infra.terraform.host.service import HostService, container_arguments
from infra.terraform.host.state import HostState
from tests.fixtures.host_release import HOST_DIGEST, release


class ContainerServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.state = HostState(root / "state", root / "run", HOST_DIGEST)
        self.digest, payload, self.manifest, _ = release()
        self.state.save_release(self.digest, payload)
        self.runner = Mock(return_value="")
        self.service = HostService(self.state, runner=self.runner)

    def test_runtime_is_restricted_and_selects_verified_image_and_immutable_config(self):
        arguments = container_arguments(self.state, self.digest)
        for option in ("--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                       "--network=host", "--sdnotify=conmon", "--cgroups=split", "--pull=never"):
            self.assertIn(option, arguments)
        self.assertIn("--user=10001:10001", arguments)
        self.assertIn("--memory=2g", arguments)
        self.assertEqual(arguments[-1], self.manifest["image_id"])
        self.assertIn(str(self.state.release_path(self.digest) / "runtime.json") + ":/etc/energy-ai/runtime.json:ro,Z", arguments)

    def test_stop_requires_proven_container_absence_before_returning(self):
        self.runner.side_effect = ["", "present"]
        with self.assertRaises(HostError):
            self.service.stop()
        self.assertEqual(self.runner.call_args.args[0][-2:], ["--all", "--filter=name=^oci-energy-ai$"])

    def test_image_identity_architecture_user_and_release_are_all_checked(self):
        record = {"Id": self.manifest["image_id"], "Architecture": "amd64", "User": "10001:10001",
                  "Release": self.manifest["release"]}
        self.runner.return_value = json.dumps(record)
        self.service.verify_image(self.manifest)
        for key, value in (("Id", "sha256:" + "b" * 64), ("Architecture", "arm64"),
                           ("User", "0"), ("Release", "b" * 40)):
            self.runner.return_value = json.dumps(dict(record, **{key: value}))
            with self.subTest(key=key), self.assertRaises(HostError):
                self.service.verify_image(self.manifest)

    def test_image_removal_never_uses_force_or_global_pruning(self):
        self.service.remove_image(self.manifest["image_id"])
        arguments = self.runner.call_args.args[0]
        self.assertEqual(arguments, ["/usr/bin/podman", "rmi", "--ignore", self.manifest["image_id"]])

    @patch("infra.terraform.host.service.http.client.HTTPConnection")
    def test_readiness_matches_actual_web_health_contract_and_private_host(self, connection):
        response = connection.return_value.getresponse.return_value
        response.status = 200
        response.read.return_value = json.dumps({
            "status": "ready", "release": self.manifest["release"], "schema": 1}).encode()
        self.service.monotonic = Mock(side_effect=[0, 0, 0, 121])
        self.service.health(self.manifest)
        connection.return_value.request.assert_called_once_with(
            "GET", "/healthz", headers={"Host": self.manifest["runtime"]["backend_host"]})
        connection.return_value.close.assert_called_once()

    @patch("infra.terraform.host.service.http.client.HTTPConnection")
    def test_wrong_release_or_schema_never_establishes_readiness(self, connection):
        response = connection.return_value.getresponse.return_value
        response.status = 200
        for changes in ({"release": "b" * 40}, {"schema": 2}, {"status": "starting"}):
            response.read.return_value = json.dumps(dict(
                {"status": "ready", "release": self.manifest["release"], "schema": 1}, **changes)).encode()
            self.service.monotonic = Mock(side_effect=[0, 0, 0, 121, 121])
            self.service.sleep = Mock()
            with self.subTest(changes=changes), self.assertRaises(HostError):
                self.service.health(self.manifest)


class BoundedHostProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def command(self, source):
        script = self.root / "child.py"
        script.write_text(source, encoding="utf-8")
        return [sys.executable, "-EsB", str(script)]

    def test_small_output_succeeds_without_inheriting_secret_environment(self):
        with patch.dict(os.environ, {"PRIVATE_TEST_MARKER": "not-for-child"}):
            result = run_command(self.command(
                "import os\nprint(os.environ.get('PRIVATE_TEST_MARKER', 'absent'))\n"), timeout=3)
        self.assertEqual(result, "absent\n")

    def test_overflow_is_stopped_before_child_completes(self):
        marker = self.root / "completed"
        command = self.command("import os, time\nfrom pathlib import Path\n"
                               "os.write(1, b'x' * 1000000)\ntime.sleep(0.4)\n"
                               "Path(%r).touch()\n" % str(marker))
        with self.assertRaises(HostError) as raised:
            run_command(command, timeout=3)
        self.assertFalse(marker.exists())
        self.assertNotIn("xxx", str(raised.exception))

    def test_deadline_also_bounds_child_after_stdout_closes(self):
        command = self.command("import os, time\nos.close(1)\ntime.sleep(60)\n")
        with self.assertRaises(HostError):
            run_command(command, timeout=0.2)

    def test_descendant_holding_stdout_is_terminated_at_deadline(self):
        pid_file = self.root / "descendant"
        command = self.command("import os, time\nfrom pathlib import Path\n"
                               "pid = os.fork()\nif pid == 0:\n    time.sleep(60)\n"
                               "else:\n    Path(%r).write_text(str(pid) + ':' + str(os.getpgrp()))\n" % str(pid_file))
        try:
            with patch("infra.terraform.host.process.os.killpg", wraps=os.killpg) as terminate:
                with self.assertRaises(HostError):
                    run_command(command, timeout=0.3)
                _, group = pid_file.read_text().split(":")
                self.assertNotEqual(int(group), os.getpgrp())
                terminate.assert_called_once_with(int(group), signal.SIGKILL)
        finally:
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text().split(":")[0]), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_nonzero_and_invalid_utf8_never_echo_child_output(self):
        for source in ("import sys\nprint('private-marker')\nsys.exit(1)\n",
                       "import os\nos.write(1, b'\\xffprivate-marker')\n"):
            with self.subTest(source=source), self.assertRaises(HostError) as raised:
                run_command(self.command(source), timeout=3)
            self.assertNotIn("private-marker", str(raised.exception))
