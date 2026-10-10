"""OCI model-backed responses for offline deployment lifecycle contracts."""

from unittest.mock import create_autospec

from oci.resource_manager import ResourceManagerClient, models
from oci.response import Response

from deployment.configuration import DeploymentConfiguration


CONFIG = DeploymentConfiguration("energy-demo", "us-ashburn-1",
                                 "ocid1.compartment.oc1.." + "a" * 32)
REPOSITORY = "example/oci-energy-ai"
STACK_ID = "ocid1.ormstack.oc1.us-ashburn-1." + "b" * 32
PROJECT_ID = "ocid1.generativeaiproject.oc1.us-ashburn-1." + "c" * 32
PLAN_ID = "ocid1.ormjob.oc1.us-ashburn-1." + "d" * 32
APPLY_ID = "ocid1.ormjob.oc1.us-ashburn-1." + "e" * 32


def response(data, **headers):
    return Response(200, headers, data, None)


def stack(**changes):
    values = dict(
        id=STACK_ID, compartment_id=CONFIG.compartment_ocid,
        display_name="oci-energy-ai-energy-demo", lifecycle_state="ACTIVE",
        variables=CONFIG.terraform_variables(), terraform_version="1.5.x",
        freeform_tags={"application": "oci-energy-ai", "deployment_id": "energy-demo",
                       "repository": REPOSITORY, "managed_by": "terraform"},
    )
    return models.Stack(**(values | changes))


def client():
    result = create_autospec(ResourceManagerClient, instance=True)
    result.list_stacks.return_value = response([])
    result.get_stack.return_value = response(stack(), etag="stack-etag")
    result.create_stack.return_value = response(stack())
    result.update_stack.return_value = response(stack())
    result.list_jobs.return_value = response([])
    result.create_job.side_effect = lambda details, **kwargs: response(models.Job(
        id=PLAN_ID if details.job_operation_details.operation == "PLAN" else APPLY_ID,
        stack_id=STACK_ID, operation=details.job_operation_details.operation,
        lifecycle_state="ACCEPTED"))
    result.get_job.side_effect = lambda job_id: response(models.Job(
        id=job_id, stack_id=STACK_ID, lifecycle_state="SUCCEEDED"))
    result.list_job_outputs.return_value = response(models.JobOutputsCollection(items=[
        models.JobOutputSummary(output_name="generative_ai_project_ocid", output_type="string",
                                output_value=PROJECT_ID, is_sensitive=False),
        models.JobOutputSummary(output_name="artifact_bucket_name", output_type="string",
                                output_value="oci-energy-ai-energy-demo-artifacts", is_sensitive=False),
        models.JobOutputSummary(output_name="object_storage_namespace", output_type="string",
                                output_value="example_namespace", is_sensitive=False),
    ]))
    return result


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
