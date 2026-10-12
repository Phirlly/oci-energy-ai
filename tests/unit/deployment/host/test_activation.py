from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call

from infra.terraform.host.activation import Activator
from infra.terraform.host.contracts import HostError
from infra.terraform.host.state import HostState
from tests.fixtures.host_release import HOST_DIGEST, release


class HostActivationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.state = HostState(root / "state", root / "run", HOST_DIGEST)
        self.service = Mock()
        self.artifacts = Mock()
        self.activator = Activator(self.state, self.service, self.artifacts)
        self.releases = [release(number) for number in (1, 2, 3)]
        self.artifacts.prepare.side_effect = self.prepare

    def prepare(self, digest):
        _, payload, _, _ = next(item for item in self.releases if item[0] == digest)
        self.state.save_release(digest, payload)

    def activate(self, number):
        digest = self.releases[number - 1][0]
        self.activator.activate(digest)
        return digest

    def test_first_repeat_update_and_rollback_preserve_current_and_previous(self):
        first = self.activate(1)
        self.assertEqual(self.state.read(), {"version": 1, "current": first, "previous": None})
        self.activate(1)
        self.assertIsNone(self.state.read()["previous"])
        second = self.activate(2)
        self.assertEqual(self.state.read()["previous"], first)
        self.assertIsNone(self.state.candidate())
        self.activator.rollback()
        self.assertEqual(self.state.read(), {"version": 1, "current": first, "previous": second})
        self.assertEqual(self.state.selected(), first)

    def test_bad_artifact_never_stops_working_release(self):
        first = self.activate(1)
        self.service.reset_mock()
        self.artifacts.prepare.side_effect = HostError("Artifact rejected.")
        with self.assertRaises(HostError):
            self.activate(2)
        self.service.stop.assert_not_called()
        self.assertEqual(self.state.selected(), first)

    def test_repeat_restarts_to_reload_current_credentials_without_rotating_history(self):
        first = self.activate(1)
        second = self.activate(2)
        self.service.reset_mock()
        self.activate(2)
        self.assertEqual(self.service.mock_calls, [
            call.stop(), call.start(), call.health(self.releases[1][2]),
        ])
        self.assertEqual(self.state.read(), {"version": 1, "current": second, "previous": first})

    def test_console_repeat_confirms_health_without_restart_and_retains_failure(self):
        first = self.activate(1)
        self.service.reset_mock()
        self.activator.activate(first, restart_current=False)
        self.assertEqual(self.service.mock_calls, [call.health(self.releases[0][2])])
        self.service.health.side_effect = HostError("Not ready.")
        with self.assertRaises(HostError):
            self.activator.activate(first, restart_current=False)
        self.service.stop.assert_not_called()
        self.service.start.assert_not_called()

    def test_commit_confirmation_never_prepares_or_changes_selection(self):
        first = self.activate(1)
        self.state.set_candidate(first)
        self.service.reset_mock()
        self.artifacts.reset_mock()
        self.assertTrue(self.activator.confirm_current(first))
        self.assertEqual(self.service.mock_calls, [call.verify_image(self.releases[0][2]),
                                                   call.health(self.releases[0][2])])
        self.assertEqual(self.artifacts.mock_calls, [])
        self.assertEqual(self.state.candidate(), first)
        for method in (self.service.verify_image, self.service.health):
            method.side_effect = HostError("Invalid readiness.")
            with self.assertRaises(HostError):
                self.activator.confirm_current(first)
            method.side_effect = None
        self.state.set_candidate(self.releases[1][0])
        self.service.reset_mock()
        self.assertFalse(self.activator.confirm_current(first))
        self.assertFalse(self.activator.confirm_current(self.releases[2][0]))
        self.assertEqual(self.service.mock_calls, [])

    def test_failed_candidate_restores_committed_release_and_still_fails(self):
        first = self.activate(1)
        self.service.health.side_effect = [HostError("Not ready."), None]
        with self.assertRaises(HostError):
            self.activate(2)
        self.assertEqual(self.state.selected(), first)
        self.assertIsNone(self.state.candidate())
        self.assertEqual(self.service.start.call_args.args, ())
        self.assertEqual(self.service.health.call_args.args[0]["release"], self.releases[0][2]["release"])

    def test_failed_first_release_leaves_no_commit_or_running_service(self):
        self.service.health.side_effect = HostError("Not ready.")
        with self.assertRaises(HostError):
            self.activate(1)
        self.assertIsNone(self.state.selected())
        self.assertIsNone(self.state.read()["current"])
        self.assertEqual(self.service.stop.call_count, 2)

    def test_ambiguous_stop_never_starts_another_writer(self):
        self.activate(1)
        self.service.reset_mock()
        self.service.stop.side_effect = HostError("Stop not established.")
        with self.assertRaises(HostError):
            self.activate(2)
        self.service.start.assert_not_called()

    def test_interrupted_candidate_is_reconciled_before_new_preparation(self):
        first = self.activate(1)
        self.prepare(self.releases[1][0])
        self.state.set_candidate(self.releases[1][0])
        self.artifacts.prepare.side_effect = lambda digest: (
            self.assertEqual(self.state.selected(), first), self.prepare(digest))
        self.activate(3)
        self.assertEqual(self.state.read()["previous"], first)

    def test_commit_error_after_replace_does_not_roll_back_published_state(self):
        self.activate(1)
        original = self.state.commit
        def uncertain(current, previous):
            original(current, previous)
            raise OSError("directory fsync failed")
        self.state.commit = uncertain
        with self.assertRaises(HostError):
            self.activate(2)
        self.assertEqual(self.state.read()["current"], self.releases[1][0])
        self.assertEqual(self.state.selected(), self.releases[1][0])

    def test_cleanup_failure_preserves_commit_and_blocks_next_admission(self):
        self.artifacts.prune.side_effect = [None, HostError("Cleanup pending."), HostError("Cleanup pending.")]
        with self.assertRaises(HostError):
            self.activate(1)
        self.assertEqual(self.state.read()["current"], self.releases[0][0])
        self.artifacts.prepare.reset_mock()
        with self.assertRaises(HostError):
            self.activate(2)
        self.artifacts.prepare.assert_not_called()

    def test_missing_rollback_and_concurrent_operation_fail_without_service_changes(self):
        with self.assertRaises(HostError):
            self.activator.rollback()
        with self.state.lock():
            with self.assertRaises(HostError):
                self.activate(1)
        self.service.stop.assert_not_called()
