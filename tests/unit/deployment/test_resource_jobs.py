import unittest

from oci.resource_manager import models

from deployment.configuration import DeploymentError
from deployment.resource_manager import ResourceManager
from tests.fixtures.resource_manager import (
    APPLY_ID, CONFIG, PLAN_ID, PROJECT_ID, REPOSITORY, STACK_ID, Clock, client, response, stack,
)


class ResourceJobLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.client = client()
        self.clock = Clock()
        self.events = []
        self.manager = ResourceManager(self.client, CONFIG, REPOSITORY, "123-1",
                                       monotonic=self.clock.monotonic, sleep=self.clock.sleep,
                                       emit=self.events.append, timeout=20)

    def test_apply_references_only_successful_plan_and_disables_provider_upgrade(self):
        self.manager.apply(b"archive")
        calls = self.client.create_job.call_args_list
        self.assertEqual(len(calls), 2)
        plan = calls[0].args[0].job_operation_details
        apply = calls[1].args[0].job_operation_details
        self.assertEqual(plan.operation, "PLAN")
        self.assertEqual(apply.execution_plan_strategy, "FROM_PLAN_JOB_ID")
        self.assertEqual(apply.execution_plan_job_id, PLAN_ID)
        self.assertFalse(plan.is_provider_upgrade_required)
        self.assertFalse(apply.is_provider_upgrade_required)
        self.assertNotEqual(calls[0].kwargs["opc_retry_token"], calls[1].kwargs["opc_retry_token"])

    def test_active_or_unknown_jobs_refuse_stack_mutation(self):
        self.client.list_stacks.return_value = response([stack()])
        for state in ("ACCEPTED", "IN_PROGRESS", "CANCELING", "UNKNOWN_ENUM_VALUE"):
            with self.subTest(state=state):
                self.client.list_jobs.return_value = response([models.Job(lifecycle_state=state)])
                with self.assertRaisesRegex(DeploymentError, "job"):
                    self.manager.apply(b"archive")
                self.client.update_stack.assert_not_called()
                self.client.create_job.assert_not_called()

    def test_plan_failure_and_cancel_never_submit_apply_or_delete_state(self):
        for state in ("FAILED", "CANCELED", "UNKNOWN_ENUM_VALUE"):
            with self.subTest(state=state):
                self.client.create_job.reset_mock()
                self.client.get_job.side_effect = lambda job_id: response(models.Job(
                    id=job_id, stack_id=STACK_ID, lifecycle_state=state))
                with self.assertRaises(DeploymentError):
                    self.manager.apply(b"archive")
                self.assertEqual(self.client.create_job.call_count, 1)
                self.client.delete_stack.assert_not_called()
                self.client.cancel_job.assert_not_called()

    def test_timeout_preserves_recovery_ids_and_never_submits_apply(self):
        self.client.get_job.side_effect = lambda job_id: response(models.Job(
            id=job_id, stack_id=STACK_ID, lifecycle_state="IN_PROGRESS"))
        with self.assertRaisesRegex(DeploymentError, "deadline"):
            self.manager.apply(b"archive")
        self.assertTrue(any(PLAN_ID in event for event in self.events))
        self.assertTrue(any(STACK_ID in event for event in self.events))
        self.assertEqual(self.client.create_job.call_count, 1)
        self.client.cancel_job.assert_not_called()
        self.client.delete_stack.assert_not_called()

    def test_deadline_expires_after_successful_plan_before_apply(self):
        def expire(job_id):
            self.clock.now = 21
            return response(models.Job(id=job_id, stack_id=STACK_ID, lifecycle_state="SUCCEEDED"))
        self.client.get_job.side_effect = expire
        with self.assertRaisesRegex(DeploymentError, "deadline"):
            self.manager.apply(b"archive")
        self.assertEqual(self.client.create_job.call_count, 1)


class ResourceOutputTests(unittest.TestCase):
    def setUp(self):
        self.client = client()
        self.manager = ResourceManager(self.client, CONFIG, REPOSITORY, "123-1")
        self.outputs = self.client.list_job_outputs.return_value.data.items

    def test_only_expected_outputs_are_returned_and_state_is_never_downloaded(self):
        self.outputs.append(models.JobOutputSummary(
            output_name="unexpected", output_value="private-marker", is_sensitive=True))
        result = self.manager.apply(b"archive")
        self.assertEqual(result["generative_ai_project_ocid"], PROJECT_ID)
        self.assertEqual(len(result), 3)
        self.assertNotIn("private-marker", repr(result))
        self.client.get_job_tf_state.assert_not_called()
        self.client.get_stack_tf_state.assert_not_called()

    def test_json_string_outputs_and_pagination_preserve_the_expected_values(self):
        self.outputs[0].output_value = '"' + PROJECT_ID + '"'
        self.client.list_job_outputs.side_effect = [
            response(models.JobOutputsCollection(items=self.outputs[:1]), **{"opc-next-page": "next"}),
            response(models.JobOutputsCollection(items=self.outputs[1:])),
        ]
        self.assertEqual(self.manager.apply(b"archive")["generative_ai_project_ocid"], PROJECT_ID)
        self.assertEqual(self.client.list_job_outputs.call_args.kwargs["page"], "next")

    def test_missing_duplicate_sensitive_wrong_type_or_malformed_output_is_rejected(self):
        first = self.outputs[0]
        variants = [self.outputs[1:], self.outputs + [first]]
        for changes in ({"is_sensitive": True}, {"output_type": "number"},
                        {"output_value": "private-marker\n::error::bad"}):
            variants.append([models.JobOutputSummary(
                output_name=first.output_name, output_type=changes.get("output_type", "string"),
                output_value=changes.get("output_value", PROJECT_ID),
                is_sensitive=changes.get("is_sensitive", False)), *self.outputs[1:]])
        for items in variants:
            with self.subTest(items=items):
                self.client.list_job_outputs.return_value = response(models.JobOutputsCollection(items=items))
                with self.assertRaises(DeploymentError) as raised:
                    self.manager.apply(b"archive")
                self.assertNotIn("private-marker", str(raised.exception))
