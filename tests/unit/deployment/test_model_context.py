import unittest
from unittest.mock import patch

from oci.generative_ai import models as genai_models
from oci.resource_manager import models

from deployment.configuration import DeploymentError
from deployment.model_context import load_oci_model_context
from deployment.resource_manager import ResourceManager
from tests.fixtures.deployment_environment import configured_environment
from tests.fixtures.resource_manager import (
    APPLY_ID, CONFIG, PROJECT_ID, REPOSITORY, STACK_ID, client, response, stack,
)


class FoundationDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.client = client()
        self.client.list_stacks.return_value = response([stack()])
        self.job = models.JobSummary(id=APPLY_ID, stack_id=STACK_ID,
                                     operation="APPLY", lifecycle_state="SUCCEEDED")
        self.client.list_jobs.return_value = response([self.job])
        self.manager = ResourceManager(self.client, CONFIG, REPOSITORY, "123-1")

    def test_latest_successful_apply_returns_outputs_without_mutation(self):
        self.assertEqual(self.manager.foundation_outputs()["generative_ai_project_ocid"], PROJECT_ID)
        latest = self.client.list_jobs.call_args.kwargs
        self.assertEqual((latest["sort_by"], latest["sort_order"], latest["limit"]), ("TIMECREATED", "DESC", 1))
        self.client.create_stack.assert_not_called()
        self.client.update_stack.assert_not_called()
        self.client.create_job.assert_not_called()

    def test_missing_stack_or_nonapply_latest_job_cannot_reuse_stale_outputs(self):
        cases = [("DESTROY", "SUCCEEDED"), ("PLAN", "SUCCEEDED"), ("APPLY", "FAILED"),
                 ("APPLY", "IN_PROGRESS")]
        for operation, state in cases:
            with self.subTest(operation=operation, state=state):
                self.job.operation, self.job.lifecycle_state = operation, state
                with self.assertRaises(DeploymentError):
                    self.manager.foundation_outputs()
                self.client.list_job_outputs.assert_not_called()
        self.client.list_stacks.return_value = response([])
        with self.assertRaisesRegex(DeploymentError, "foundation"):
            self.manager.foundation_outputs()

    def test_job_from_different_stack_is_rejected(self):
        self.job.stack_id = STACK_ID + "foreign"
        with self.assertRaisesRegex(DeploymentError, "job"):
            self.manager.foundation_outputs()
        self.client.list_job_outputs.assert_not_called()


class ActiveProjectTests(unittest.TestCase):
    def setUp(self):
        self.environment = configured_environment() | {
            "DEPLOYMENT_ID": CONFIG.deployment_id, "OCI_COMPARTMENT_OCID": CONFIG.compartment_ocid,
            "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
        }
        self.project = genai_models.GenerativeAiProject(
            id=PROJECT_ID, compartment_id=CONFIG.compartment_ocid, display_name="oci-energy-ai-energy-demo",
            lifecycle_state="ACTIVE", freeform_tags={"application": "oci-energy-ai",
                                                     "deployment_id": "energy-demo", "managed_by": "terraform"})

    @patch("deployment.model_context.deployment_identity")
    @patch("deployment.model_context.ResourceManagerClient")
    @patch("deployment.model_context.GenerativeAiClient")
    @patch("deployment.model_context.ResourceManager")
    def test_project_ownership_is_verified_and_clients_closed(self, manager, genai, resource, identity):
        identity.return_value = ({"region": "us-ashburn-1"}, object())
        manager.return_value.foundation_outputs.return_value = {"generative_ai_project_ocid": PROJECT_ID}
        manager.return_value.name = "oci-energy-ai-energy-demo"
        manager.return_value.deadline.call.side_effect = lambda method, *args: method(*args)
        genai.return_value.get_generative_ai_project.return_value = response(self.project)
        result = load_oci_model_context(self.environment)
        self.assertEqual(result["oci_project"], PROJECT_ID)
        self.assertIs(result["oci_signer"], identity.return_value[1])
        genai.return_value.get_generative_ai_project.assert_called_once_with(PROJECT_ID)
        resource.return_value.base_client.session.close.assert_called_once()
        genai.return_value.base_client.session.close.assert_called_once()
        for field, value in (("lifecycle_state", "DELETED"), ("compartment_id", "foreign"),
                             ("display_name", "foreign"), ("freeform_tags", {}), ("id", PROJECT_ID + "foreign")):
            old = getattr(self.project, field)
            setattr(self.project, field, value)
            with self.subTest(field=field):
                with self.assertRaisesRegex(DeploymentError, "project"):
                    load_oci_model_context(self.environment)
            setattr(self.project, field, old)
