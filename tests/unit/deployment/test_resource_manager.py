import base64
import unittest

from oci.exceptions import ServiceError

from deployment.configuration import DeploymentError
from deployment.resource_manager import ResourceManager
from tests.fixtures.resource_manager import CONFIG, REPOSITORY, STACK_ID, Clock, client, response, stack


class StackOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.client = client()
        self.clock = Clock()
        self.events = []
        self.manager = ResourceManager(self.client, CONFIG, REPOSITORY, "123-1",
                                       emit=self.events.append, monotonic=self.clock.monotonic,
                                       sleep=self.clock.sleep, timeout=30)

    def test_new_stack_has_exact_nonsecret_variables_tags_and_zip(self):
        outputs = self.manager.apply(b"reviewed-archive")
        details = self.client.create_stack.call_args.args[0]
        self.assertEqual(details.variables, CONFIG.terraform_variables())
        self.assertEqual(details.terraform_version, "1.5.x")
        self.assertEqual(details.freeform_tags["repository"], REPOSITORY)
        self.assertEqual(base64.b64decode(details.config_source.zip_file_base64_encoded), b"reviewed-archive")
        self.assertIn("generative_ai_project_ocid", outputs)
        self.assertIn(STACK_ID, self.events[0])
        self.assertEqual(self.client.list_stacks.call_args.kwargs["compartment_id"], CONFIG.compartment_ocid)

    def test_owned_stack_is_updated_with_etag_and_without_recreation(self):
        self.client.list_stacks.return_value = response([stack()])
        self.manager.apply(b"archive")
        self.client.create_stack.assert_not_called()
        self.assertEqual(self.client.update_stack.call_args.kwargs["if_match"], "stack-etag")

    def test_foreign_duplicate_renamed_and_wrong_region_stacks_are_rejected(self):
        cases = [
            [stack(freeform_tags={})], [stack(), stack()],
            [stack(display_name="renamed-owned-stack")],
            [stack(variables=CONFIG.terraform_variables() | {"region": "us-chicago-1"})],
        ]
        for candidates in cases:
            with self.subTest(candidates=candidates):
                self.client.list_stacks.return_value = response(candidates)
                self.client.get_stack.return_value = response(candidates[0], etag="etag")
                with self.assertRaises(DeploymentError):
                    self.manager.apply(b"archive")
                self.client.create_stack.assert_not_called()
                self.client.update_stack.assert_not_called()
                self.client.create_job.assert_not_called()

    def test_discovery_reads_all_pages_and_rejects_repeated_page_token(self):
        self.client.list_stacks.side_effect = [response([], **{"opc-next-page": "next"}), response([stack()])]
        self.manager.apply(b"archive")
        self.assertEqual(self.client.list_stacks.call_args.kwargs["page"], "next")
        self.client.list_stacks.side_effect = None
        self.client.list_stacks.return_value = response([], **{"opc-next-page": "same"})
        with self.assertRaisesRegex(DeploymentError, "pagination"):
            self.manager.apply(b"archive")

    def test_create_token_is_stable_across_workflow_retries(self):
        self.manager.apply(b"archive")
        first = self.client.create_stack.call_args.kwargs["opc_retry_token"]
        ResourceManager(self.client, CONFIG, REPOSITORY, "123-2").apply(b"archive")
        self.assertEqual(first, self.client.create_stack.call_args.kwargs["opc_retry_token"])

    def test_missing_etag_and_expired_deadline_prevent_update(self):
        self.client.list_stacks.return_value = response([stack()])
        self.client.get_stack.return_value = response(stack())
        with self.assertRaisesRegex(DeploymentError, "ETag"):
            self.manager.apply(b"archive")
        self.client.update_stack.assert_not_called()
        self.clock.now = 31
        with self.assertRaisesRegex(DeploymentError, "deadline"):
            self.manager.apply(b"archive")
        self.client.create_stack.assert_not_called()

    def test_failed_or_unknown_stack_state_stops_before_jobs(self):
        for state in ("FAILED", "DELETING", "UNKNOWN_ENUM_VALUE"):
            with self.subTest(state=state):
                self.client.get_stack.return_value = response(stack(lifecycle_state=state))
                with self.assertRaises(DeploymentError):
                    self.manager.apply(b"archive")
                self.client.create_job.assert_not_called()

    def test_etag_conflict_is_safe_and_does_not_submit_a_plan(self):
        self.client.list_stacks.return_value = response([stack()])
        self.client.update_stack.side_effect = ServiceError(412, "conflict", {}, "private-marker")
        with self.assertRaisesRegex(DeploymentError, "ETag") as raised:
            self.manager.apply(b"archive")
        self.assertNotIn("private-marker", str(raised.exception))
        self.client.create_job.assert_not_called()

    def test_creating_stack_waits_until_active_before_plan(self):
        self.client.get_stack.side_effect = [response(stack(lifecycle_state="CREATING")), response(stack())]
        self.manager.apply(b"archive")
        self.assertEqual(self.clock.now, 5)
        self.assertEqual(self.client.create_job.call_count, 2)

    def test_unavailable_identity_or_transport_stops_without_mutation_or_raw_error(self):
        for error in [ServiceError(401, "unauthorized", {}, "private-marker"),
                      ServiceError(429, "limit", {}, "private-marker"), RuntimeError("private-marker")]:
            with self.subTest(error=type(error).__name__):
                self.client.list_stacks.side_effect = error
                with self.assertRaises(DeploymentError) as raised:
                    self.manager.apply(b"archive")
                self.assertNotIn("private-marker", str(raised.exception))
                self.client.create_stack.assert_not_called()


class StackCleanupTests(unittest.TestCase):
    def setUp(self):
        self.client = client()
        self.manager = ResourceManager(self.client, CONFIG, REPOSITORY, "124-1")

    def test_destroy_missing_stack_is_a_noop(self):
        self.assertFalse(self.manager.destroy("energy-demo"))
        self.client.create_stack.assert_not_called()
        self.client.create_job.assert_not_called()

    def test_destroy_uses_owned_existing_configuration_and_retains_empty_stack(self):
        self.client.list_stacks.return_value = response([stack()])
        self.assertTrue(self.manager.destroy("energy-demo"))
        operation = self.client.create_job.call_args.args[0].job_operation_details
        self.assertEqual(operation.operation, "DESTROY")
        self.assertEqual(operation.execution_plan_strategy, "AUTO_APPROVED")
        self.client.update_stack.assert_not_called()
        self.client.delete_stack.assert_not_called()

    def test_destroy_requires_matching_confirmation_before_any_api_call(self):
        with self.assertRaisesRegex(DeploymentError, "confirmation"):
            self.manager.destroy("wrong")
        self.assertEqual(self.client.mock_calls, [])
