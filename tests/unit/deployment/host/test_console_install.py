import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from infra.terraform.host.console_contract import parse_installation
from infra.terraform.host.console_install import ConsoleInstaller
from infra.terraform.host.contracts import HostError
from infra.terraform.host.state import HostState, atomic_write
from tests.fixtures.host_release import HOST_DIGEST, VNIC_CONTENT, installation


class ConsoleInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "config"
        self.config.mkdir()
        self.state = HostState(self.root / "state", self.root / "run", HOST_DIGEST)
        self.journal = self.state.root / "installation.json"
        self.activator = Mock()
        self.activator.confirm_current.return_value = False
        self.runner = Mock(side_effect=self.bootstrap)
        self.installer = ConsoleInstaller(self.state, self.activator, self.config, runner=self.runner)
        self.desired = self.desire()

    def desire(self, number=1, generation=0):
        raw, _ = installation(number, generation)
        return parse_installation(raw, VNIC_CONTENT, HOST_DIGEST, "us-ashburn-1")

    def bootstrap(self, *args, **kwargs):
        self.assertGreaterEqual(self.record()["attempts"], 1)
        (self.config / "ready").touch()
        (self.config / "failed").unlink(missing_ok=True)

    def record(self):
        return json.loads(self.journal.read_bytes())

    def seed(self, attempts=12):
        value = {"version": 1, "target": self.desired.target, "generation": 0,
                 "attempts": attempts, "complete": False}
        self.journal.write_text(json.dumps(value))

    def test_initial_install_reserves_before_work_and_completed_repeat_is_noop(self):
        def activate(digest, **kwargs):
            self.assertEqual(self.record()["attempts"], 1)
            self.assertFalse(self.record()["complete"])
            self.assertEqual(digest, self.desired.digest)
        self.activator.activate.side_effect = activate
        self.assertEqual(self.installer.run(self.desired), "installed")
        self.assertTrue(self.record()["complete"])
        self.activator.activate.assert_called_once_with(self.desired.digest, restart_current=False)
        self.runner.assert_called_once()
        self.activator.reset_mock()
        self.runner.reset_mock()
        self.assertEqual(self.installer.run(self.desired), "installed")
        self.assertEqual(self.activator.mock_calls, [])
        self.runner.assert_not_called()

    def test_failure_and_process_recreation_preserve_budget_and_repair_bootstrap_marker(self):
        (self.config / "failed").touch()
        self.runner.side_effect = HostError("Package unavailable.")
        with self.assertRaises(HostError):
            self.installer.run(self.desired)
        self.assertEqual(self.record()["attempts"], 1)
        self.activator.activate.assert_not_called()
        self.runner.side_effect = self.bootstrap
        resumed = ConsoleInstaller(self.state, self.activator, self.config, runner=self.runner)
        resumed.run(self.desired)
        self.assertEqual(self.record()["attempts"], 2)
        self.assertTrue(self.record()["complete"])
        self.assertFalse((self.config / "failed").exists())

    def test_last_attempt_commit_recovers_after_completion_journal_failure_without_more_work(self):
        self.seed(attempts=11)
        def write(path, content):
            if json.loads(content)["complete"]:
                raise OSError("Interrupted after application commit.")
            atomic_write(path, content)
        with patch("infra.terraform.host.console_install.atomic_write", side_effect=write):
            with self.assertRaises(OSError):
                self.installer.run(self.desired)
        self.assertEqual(self.record()["attempts"], 12)
        self.assertFalse(self.record()["complete"])
        self.activator.reset_mock()
        self.activator.confirm_current.return_value = True
        self.runner.reset_mock()
        self.assertEqual(self.installer.run(self.desired), "installed")
        self.assertTrue(self.record()["complete"])
        self.assertEqual(self.record()["attempts"], 12)
        self.activator.confirm_current.assert_called_once_with(self.desired.digest)
        self.activator.activate.assert_not_called()
        self.runner.assert_not_called()

    def test_exhaustion_or_failed_confirmation_cannot_admit_thirteenth_attempt(self):
        self.seed()
        for failure in (False, HostError("Unverified application.")):
            with self.subTest(failure=type(failure).__name__):
                self.activator.confirm_current.side_effect = failure if isinstance(failure, Exception) else None
                self.activator.confirm_current.return_value = False
                with self.assertRaises(HostError):
                    self.installer.run(self.desired)
                self.assertEqual(self.record()["attempts"], 12)
                self.assertFalse(self.record()["complete"])
                self.activator.activate.assert_not_called()
                self.runner.assert_not_called()

    def test_changed_target_or_higher_generation_has_new_budget_but_lower_generation_is_rejected(self):
        self.seed()
        self.installer.run(self.desire(generation=1))
        self.assertEqual(self.record()["attempts"], 1)
        self.assertEqual(self.record()["generation"], 1)
        self.installer.run(self.desire(number=2, generation=1))
        self.assertEqual(self.record()["target"], self.desire(number=2, generation=1).target)
        self.assertEqual(self.record()["attempts"], 1)
        self.activator.reset_mock()
        with self.assertRaises(HostError):
            self.installer.run(self.desire(number=3, generation=0))
        self.assertEqual(self.activator.mock_calls, [])

    def test_reservation_failure_or_invalid_journal_cannot_run_bootstrap_or_activate(self):
        with patch("infra.terraform.host.console_install.atomic_write", side_effect=OSError("Disk full.")):
            with self.assertRaises(OSError):
                self.installer.run(self.desired)
        for value in (b"{}", b"x" * 2049, b'{"version":1,"version":1}'):
            self.journal.write_bytes(value)
            with self.subTest(value=value[:10]), self.assertRaises(HostError):
                self.installer.run(self.desired)
        self.runner.assert_not_called()
        self.assertEqual(self.activator.mock_calls, [])

    def test_ready_host_skips_packages_and_concurrent_installer_cannot_start_work(self):
        (self.config / "ready").touch()
        lock_path = self.state.run / "installation.lock"
        with lock_path.open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(HostError):
                self.installer.run(self.desired)
            self.assertFalse(self.journal.exists())
        self.installer.run(self.desired)
        self.runner.assert_not_called()
        self.activator.activate.assert_called_once()

    def test_bootstrap_success_without_ready_marker_cannot_activate(self):
        self.runner.side_effect = None
        with self.assertRaises(HostError):
            self.installer.run(self.desired)
        self.activator.activate.assert_not_called()
        self.assertEqual(self.record()["attempts"], 1)
