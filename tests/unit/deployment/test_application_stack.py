import json
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch

from oci.resource_manager import models

from deployment.application_configuration import ApplicationConfiguration
from deployment.configuration import DeploymentError
from deployment.resource_manager import ResourceManager
from tests.fixtures.resource_manager import (
    APPLY_ID, CONFIG, REPOSITORY, STACK_ID, application_outputs, client, response, stack,
)


APPLICATION = ApplicationConfiguration(
    version=1, tenancy_ocid="ocid1.tenancy.oc1.." + "a" * 32,
    home_region="us-ashburn-1", availability_domain="EXAMPLE:US-ASHBURN-AD-1",
    image_ocid="ocid1.image.oc1.iad." + "b" * 32,
)


class ApplicationConfigurationTests(unittest.TestCase):
    def test_json_round_trip_is_canonical_and_contains_only_topology(self):
        value = APPLICATION.to_json()
        self.assertEqual(ApplicationConfiguration.from_json(value), APPLICATION)
        self.assertEqual(json.loads(value), asdict(APPLICATION))
        self.assertEqual(value, json.dumps(asdict(APPLICATION), sort_keys=True, separators=(",", ":")))
        APPLICATION.validate_region(CONFIG.region)

    def test_invalid_direct_values_and_cross_region_image_are_rejected(self):
        for changes in ({"version": True}, {"version": 2}, {"tenancy_ocid": "private-marker"},
                        {"home_region": "unknown-region-1"}, {"availability_domain": "bad\nvalue"},
                        {"image_ocid": "ocid1.instance.oc1.iad." + "b" * 32}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(APPLICATION, **changes)
        with self.assertRaises(ValueError):
            APPLICATION.validate_region("us-phoenix-1")

    def test_unknown_duplicate_missing_oversized_and_nonobject_json_are_rejected(self):
        values = ["null", "[]", "{}", "not-json", " " * 8192, None,
                  APPLICATION.to_json()[:-1] + ',"version":1}',
                  json.dumps(asdict(APPLICATION) | {"api_key": "private-marker"})]
        for value in values:
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError) as raised:
                ApplicationConfiguration.from_json(value)
            self.assertNotIn("private-marker", str(raised.exception))

    def test_variable_size_limit_counts_the_name_and_valid_json_whitespace(self):
        boundary = APPLICATION.to_json().ljust(8192 - len("application"))
        self.assertEqual(ApplicationConfiguration.from_json(boundary), APPLICATION)
        with self.assertRaises(ValueError):
            ApplicationConfiguration.from_json(boundary + " ")


class ApplicationStackTransitionTests(unittest.TestCase):
    def setUp(self):
        self.client = client()
        self.manager = ResourceManager(self.client, CONFIG, REPOSITORY, "123-1")
        self.variables = CONFIG.terraform_variables() | {"application": APPLICATION.to_json()}
        self.promoted = stack(variables=self.variables)
        self.client.list_stacks.return_value = response([stack()])

    def select_promoted(self):
        self.client.get_stack.return_value = response(self.promoted, etag="app-etag")

    def assert_no_mutation(self):
        self.client.create_stack.assert_not_called()
        self.client.update_stack.assert_not_called()
        self.client.create_job.assert_not_called()

    def test_promotion_preserves_stack_etag_and_requires_expected_post_update_variables(self):
        self.client.get_stack.side_effect = [response(stack(), etag="foundation-etag"), response(self.promoted)]
        # Output validation is tested separately; this case proves the transition request.
        with patch.object(self.manager.jobs, "apply", return_value={}) as apply:
            self.manager.apply_application(b"archive", APPLICATION)
        self.client.create_stack.assert_not_called()
        request = self.client.update_stack.call_args
        self.assertEqual(request.kwargs["if_match"], "foundation-etag")
        self.assertEqual(request.args[1].variables, self.variables)
        apply.assert_called_once_with(STACK_ID, CONFIG.deployment_id, application_region=CONFIG.region)

    def test_repeat_or_interrupted_promotion_reuses_exact_topology(self):
        self.select_promoted()
        with patch.object(self.manager.jobs, "apply", return_value={}):
            self.manager.apply_application(b"archive", APPLICATION)
        self.assertEqual(self.client.update_stack.call_args.args[1].variables, self.variables)
        self.assertEqual(self.client.update_stack.call_args.kwargs["if_match"], "app-etag")

    def test_foundation_mutations_and_topology_changes_refuse_before_mutation(self):
        self.select_promoted()
        for operation in (lambda: self.manager.apply(b"archive"),
                          lambda: self.manager.destroy(CONFIG.deployment_id),
                          lambda: self.manager.apply_application(
                              b"archive", replace(APPLICATION, availability_domain="EXAMPLE:US-ASHBURN-AD-2"))):
            with self.subTest(operation=operation), self.assertRaises(DeploymentError):
                operation()
            self.assert_no_mutation()

    def test_post_update_mismatch_stops_before_plan(self):
        with self.assertRaises(DeploymentError):
            self.manager.apply_application(b"archive", APPLICATION)
        self.client.update_stack.assert_called_once()
        self.client.create_job.assert_not_called()

    def test_invalid_extended_state_is_never_accepted_for_read_or_mutation(self):
        for variables in (self.variables | {"unexpected": "private-marker"},
                          self.variables | {"application": "null"},
                          self.variables | {"application": APPLICATION.to_json()[:-1] + ',"version":1}'}):
            self.client.get_stack.return_value = response(stack(variables=variables), etag="etag")
            with self.subTest(variables=variables), self.assertRaises(DeploymentError):
                self.manager.application_configuration()
            self.assert_no_mutation()

    def test_readonly_discovery_preserves_model_outputs_and_pinned_topology(self):
        self.select_promoted()
        self.client.list_jobs.return_value = response([models.JobSummary(
            id=APPLY_ID, stack_id=STACK_ID, operation="APPLY", lifecycle_state="SUCCEEDED")])
        self.assertEqual(self.manager.application_configuration(), APPLICATION)
        self.assertEqual(len(self.manager.foundation_outputs()), 3)
        self.assert_no_mutation()

    def test_application_read_requires_current_application_apply_and_returns_eight_outputs(self):
        self.select_promoted()
        job = models.JobSummary(id=APPLY_ID, stack_id=STACK_ID, operation="APPLY", lifecycle_state="SUCCEEDED")
        self.client.list_jobs.return_value = response([job])
        self.client.list_job_outputs.return_value.data.items.extend(application_outputs())
        self.assertEqual(len(self.manager.application_outputs()), 8)
        self.assert_no_mutation()
        for operation, state in (("PLAN", "SUCCEEDED"), ("DESTROY", "SUCCEEDED"), ("APPLY", "FAILED")):
            job.operation, job.lifecycle_state = operation, state
            self.client.list_job_outputs.reset_mock()
            with self.subTest(operation=operation), self.assertRaises(DeploymentError):
                self.manager.application_outputs()
            self.client.list_job_outputs.assert_not_called()
        job.operation, job.lifecycle_state = "APPLY", "SUCCEEDED"
        self.client.get_stack.return_value = response(stack(), etag="etag")
        with self.assertRaises(DeploymentError):
            self.manager.application_outputs()
        self.client.list_job_outputs.assert_not_called()
        self.assert_no_mutation()

    def test_new_application_stack_is_created_with_topology_and_all_outputs(self):
        self.client.list_stacks.return_value = response([])
        self.select_promoted()
        self.client.list_job_outputs.return_value.data.items.extend(application_outputs())
        self.assertEqual(len(self.manager.apply_application(b"archive", APPLICATION)), 8)
        self.assertEqual(self.client.create_stack.call_args.args[0].variables, self.variables)
        self.assertEqual(len(self.client.create_job.call_args_list), 2)

    def test_cleanup_refuses_foundation_and_different_application_topology(self):
        for candidate in (stack(), stack(variables=CONFIG.terraform_variables() | {
                "application": replace(APPLICATION, availability_domain="EXAMPLE:US-ASHBURN-AD-2").to_json()})):
            self.client.get_stack.return_value = response(candidate, etag="etag")
            with self.subTest(candidate=candidate), self.assertRaises(DeploymentError):
                self.manager.destroy_application(CONFIG.deployment_id, APPLICATION)
            self.assert_no_mutation()

    def test_application_cleanup_requires_confirmation_and_retains_configuration(self):
        with self.assertRaises(DeploymentError):
            self.manager.destroy_application("wrong", APPLICATION)
        self.assertEqual(self.client.mock_calls, [])
        self.select_promoted()
        self.assertTrue(self.manager.destroy_application(CONFIG.deployment_id, APPLICATION))
        self.assertEqual(self.client.create_job.call_args.args[0].job_operation_details.operation, "DESTROY")
        self.client.update_stack.assert_not_called()
        self.client.delete_stack.assert_not_called()
