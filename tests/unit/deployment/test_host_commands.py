import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from oci.compute_instance_agent import models
from oci.exceptions import ServiceError

from deployment.configuration import DeploymentError
from deployment.host_commands import HostCommands, ACTIVATION_TIMEOUT
from deployment.resource_jobs import OperationDeadline
from tests.fixtures.resource_manager import CONFIG, REPOSITORY, Clock, response
from tests.fixtures.host_release import HOST_DIGEST


INSTANCE = 'ocid1.instance.oc1.iad.' + 'i' * 32
COMMAND = 'ocid1.instanceagentcommand.oc1.iad.' + 'c' * 32
DIGEST = 'a' * 64


class HostCommandTests(unittest.TestCase):
    def setUp(self):
        self.client, self.clock = Mock(), Clock()
        self.commands = HostCommands(self.client, CONFIG, REPOSITORY, INSTANCE, HOST_DIGEST,
                                     OperationDeadline(30, self.clock.monotonic, self.clock.sleep))
        self.client.list_instance_agent_commands.return_value = response([])
        self.command = None
        def create(details, **kwargs):
            self.command = models.InstanceAgentCommand(id=COMMAND, compartment_id=details.compartment_id,
                display_name=details.display_name, target=details.target, content=details.content,
                execution_time_out_in_seconds=details.execution_time_out_in_seconds, is_canceled=False)
            return response(self.command)
        self.client.create_instance_agent_command.side_effect = create
        self.client.get_instance_agent_command.side_effect = lambda _: response(self.command)
        self.state = dict(version=1, status='ready', host_digest=HOST_DIGEST, current=DIGEST,
                          previous=None, candidate=None, release='1' * 40)
        self.execution = NS(instance_agent_command_id=COMMAND, instance_id=INSTANCE,
                            lifecycle_state='SUCCEEDED', content=NS(exit_code=0, output_type='TEXT', text=json.dumps(self.state)))
        self.client.get_instance_agent_command_execution.return_value = response(self.execution)

    def existing(self):
        self.client.list_instance_agent_commands.return_value = response([NS(
            instance_agent_command_id=COMMAND, display_name=self.command.display_name)])

    def test_fixed_command_verified_target_and_bounded_result(self):
        result = self.commands.activate(DIGEST, 'run-123-attempt-1')
        self.assertEqual(result, self.state)
        details = self.client.create_instance_agent_command.call_args.args[0]
        self.assertEqual(details.content.source.text, 'sudo /usr/local/sbin/oci-energy-ai activate ' + DIGEST)
        self.assertEqual(details.target.instance_id, INSTANCE)
        # Two download limits, image load, inspect, reconciliation, candidate/recovery,
        # scoped pruning and filesystem headroom must fit inside remote execution.
        supported_host_budget = 2*600 + 300 + 2*30 + 3*(75 + 160 + 120) + 2*60 + 300
        self.assertGreater(ACTIVATION_TIMEOUT, supported_host_budget)
        self.assertEqual(details.execution_time_out_in_seconds, ACTIVATION_TIMEOUT)
        self.assertEqual(len(self.client.create_instance_agent_command.call_args.kwargs['opc_retry_token']), 64)

    def test_retry_recovers_original_command_and_rejects_changed_payload(self):
        self.commands.activate(DIGEST, 'same-run')
        self.existing()
        self.commands.activate(DIGEST, 'same-run')
        self.client.create_instance_agent_command.assert_called_once()
        with self.assertRaisesRegex(DeploymentError, 'intent'):
            self.commands.activate('b' * 64, 'same-run')

    def test_rollback_rerun_uses_original_fixed_target_even_after_history_swapped(self):
        self.commands.activate(DIGEST, 'rollback-123')
        self.existing()
        target = self.commands.rollback_target('rollback-123', attempt=2, previous='b' * 64)
        self.assertEqual(target, DIGEST)
        self.client.list_instance_agent_commands.return_value = response([])
        with self.assertRaisesRegex(DeploymentError, 'Original'):
            self.commands.rollback_target('rollback-123', attempt=2, previous='b' * 64)

    def test_older_queued_mutation_finishes_before_new_mutation_is_created(self):
        self.commands.activate(DIGEST, 'old')
        self.existing()
        pending = NS(**(vars(self.execution) | {'lifecycle_state': 'IN_PROGRESS', 'content': None}))
        self.client.get_instance_agent_command_execution.side_effect = [response(pending), response(self.execution), response(self.execution)]
        self.commands.activate('b' * 64, 'new')
        self.assertEqual(self.clock.now, 5)
        self.assertEqual(self.client.create_instance_agent_command.call_count, 2)

    def test_ambiguous_old_execution_blocks_new_mutation_and_pruning(self):
        self.commands.activate(DIGEST, 'old')
        self.existing()
        for state in ('CANCELED', 'TIMED_OUT', 'UNKNOWN_ENUM_VALUE'):
            self.execution.lifecycle_state = state
            with self.subTest(state=state), self.assertRaisesRegex(DeploymentError, 'completion'):
                self.commands.activate('b' * 64, 'new')
        self.client.create_instance_agent_command.assert_called_once()

    def test_failed_command_with_exit_proves_completion_but_cannot_report_success(self):
        self.commands.activate(DIGEST, 'old')
        self.existing()
        self.execution.lifecycle_state, self.execution.content.exit_code = 'FAILED', 2
        self.commands.settle()
        with self.assertRaises(DeploymentError):
            self.commands.activate(DIGEST, 'old')

    def test_wrong_execution_identity_oversize_duplicate_json_or_host_drift_is_rejected(self):
        self.commands.activate(DIGEST, 'old')
        self.existing()
        original = self.execution.content.text
        for text in ('x' * 1025, '{"version":1,"version":1}', json.dumps(self.state | {'host_digest': 'b'*64})):
            self.execution.content.text = text
            with self.subTest(text=text[:20]), self.assertRaises(DeploymentError):
                self.commands.activate(DIGEST, 'old')
        self.execution.content.text = original
        self.execution.instance_id += 'foreign'
        with self.assertRaises(DeploymentError):
            self.commands.activate(DIGEST, 'old')

    def test_ambiguous_submission_recovers_without_second_create(self):
        original = self.client.create_instance_agent_command.side_effect
        def uncertain(*args, **kwargs):
            original(*args, **kwargs)
            self.existing()
            raise ServiceError(500, 'Internal', {}, 'private')
        self.client.create_instance_agent_command.side_effect = uncertain
        self.assertEqual(self.commands.activate(DIGEST, 'same'), self.state)
        self.client.create_instance_agent_command.assert_called_once()

    def test_missing_exit_or_duplicate_command_marker_cannot_be_adopted(self):
        self.commands.activate(DIGEST, 'same')
        self.existing()
        self.execution.content.exit_code = None
        with self.assertRaises(DeploymentError):
            self.commands.settle()
        summaries = self.client.list_instance_agent_commands.return_value.data
        summaries.append(summaries[0])
        with self.assertRaisesRegex(DeploymentError, 'duplicate'):
            self.commands.activate(DIGEST, 'same')

    def test_throttled_post_create_read_retries_same_id_without_second_create(self):
        calls = []
        def read(identifier):
            calls.append(identifier)
            if len(calls) < 3:
                raise ServiceError(429, 'TooManyRequests', {}, 'private-service-detail')
            return response(self.command)
        self.client.get_instance_agent_command.side_effect = read
        self.assertEqual(self.commands.activate(DIGEST, 'same'), self.state)
        self.assertEqual(calls, [COMMAND] * 3)
        self.assertGreaterEqual(self.clock.now, 6)
        self.assertLessEqual(self.clock.now, 12)
        self.client.create_instance_agent_command.assert_called_once()

    def test_throttled_discovery_recovers_but_still_rejects_changed_identity(self):
        self.commands.activate(DIGEST, 'old')
        self.existing()
        for changed in (False, True):
            with self.subTest(changed=changed):
                if changed:
                    self.command.target.instance_id = 'ocid1.instance.oc1.iad.' + 'f' * 32
                self.client.get_instance_agent_command.side_effect = [
                    ServiceError(429, 'TooManyRequests', {}, 'private-service-detail'), response(self.command)]
                if changed:
                    with self.assertRaisesRegex(DeploymentError, 'identity'):
                        self.commands.settle()
                else:
                    self.commands.settle()
        self.client.create_instance_agent_command.assert_called_once()

    def test_metadata_read_exhaustion_and_other_errors_do_not_submit_commands(self):
        self.commands.activate(DIGEST, 'old')
        self.existing()
        self.commands.deadline.end = 1000
        errors = [ServiceError(status, 'Fixture', {}, 'private-service-detail')
                  for status in (429, 401, 403, 404, 500)] + [ConnectionError('private-service-detail')]
        for error in errors:
            with self.subTest(error=type(error).__name__, status=getattr(error, 'status', None)):
                self.client.get_instance_agent_command.reset_mock()
                self.client.get_instance_agent_command.side_effect = error
                with self.assertRaises(DeploymentError) as raised:
                    self.commands.activate('b' * 64, 'new')
                self.assertNotIn('private-service-detail', str(raised.exception))
                throttled = getattr(error, 'status', None) == 429
                self.assertEqual(self.client.get_instance_agent_command.call_count, 6 if throttled else 1)
                if throttled:
                    self.assertIn('throttled', str(raised.exception))
                    self.assertGreaterEqual(self.clock.now, 44)
                    self.assertLessEqual(self.clock.now, 88)
                self.client.create_instance_agent_command.assert_called_once()

    def test_metadata_read_deadline_blocks_backoff_replay_and_late_success(self):
        self.commands.activate(DIGEST, 'old')
        self.existing()
        for late_success in (False, True):
            with self.subTest(late_success=late_success):
                self.clock.now = 0
                self.commands.deadline.end = 1
                def read(identifier):
                    if late_success:
                        self.clock.now = 2
                        return response(self.command)
                    raise ServiceError(429, 'TooManyRequests', {}, 'private-service-detail')
                self.client.get_instance_agent_command.reset_mock()
                self.client.get_instance_agent_command.side_effect = read
                with self.assertRaisesRegex(DeploymentError, 'deadline'):
                    self.commands.activate('b' * 64, 'new')
                self.client.get_instance_agent_command.assert_called_once_with(COMMAND)
                self.assertEqual(self.clock.now, 2 if late_success else 1)
                self.client.create_instance_agent_command.assert_called_once()
