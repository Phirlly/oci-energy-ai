"""Bounded Resource Manager jobs, pagination and validated public outputs."""

import hashlib
import json
import re

from oci.exceptions import ServiceError
from oci.resource_manager import models

from deployment.configuration import DeploymentError


def resource_id(value, kind):
    if not isinstance(value, str) or not re.fullmatch(
        rf"ocid1\.{kind}\.oc1\.[a-z0-9-]+\.[a-z0-9.]{{20,255}}", value
    ):
        raise DeploymentError("OCI returned an invalid resource identifier.")
    return value


def retry_token(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


class OperationDeadline:
    """One budget shared by discovery, mutations and every wait in an operation."""

    def __init__(self, timeout, monotonic, sleep):
        self.end = monotonic() + timeout
        self.monotonic = monotonic
        self.sleep = sleep

    def check(self):
        if self.monotonic() >= self.end:
            raise DeploymentError("Deployment deadline exceeded; inspect the reported stack/job before retrying.")

    def call(self, method, *args, **kwargs):
        self.check()
        try:
            return method(*args, **kwargs)
        except ServiceError as error:
            guidance = {
                401: "OCI authentication failed; check the deployment identity.",
                403: "OCI denied access; check compartment permissions.",
                404: "OCI resource unavailable or access denied; check identity and compartment.",
                409: "OCI resource is busy; inspect the reported stack/job before retrying.",
                412: "Stack ETag changed; inspect concurrent operations before retrying.",
                429: "OCI rate limit reached; inspect the reported stack/job before retrying later.",
            }
            raise DeploymentError(guidance.get(error.status, "OCI request failed; inspect the reported stack/job.")) from None
        except Exception:
            raise DeploymentError("OCI connection or response failed; inspect the reported stack/job before retrying.") from None

    def pause(self):
        self.check()
        self.sleep(min(5, self.end - self.monotonic()))

    def pages(self, method, *args, collection=False, **kwargs):
        page = None
        seen = set()
        while True:
            result = self.call(method, *args, **kwargs, **({"page": page} if page else {}))
            yield from result.data.items if collection else result.data
            page = result.headers.get("opc-next-page")
            if not page:
                return
            if page in seen:
                raise DeploymentError("OCI pagination repeated a page; operation stopped.")
            seen.add(page)


class ResourceJobs:
    def __init__(self, client, deadline, repository, run_id, emit):
        self.client = client
        self.deadline = deadline
        self.repository = repository
        self.run_id = run_id
        self.emit = emit

    def require_idle(self, stack_id):
        jobs = self.deadline.pages(self.client.list_jobs, stack_id=stack_id)
        if any(job.lifecycle_state not in {"SUCCEEDED", "FAILED", "CANCELED"} for job in jobs):
            raise DeploymentError("Stack has an active or unknown job; wait and inspect it before retrying.")

    def run(self, stack_id, operation):
        self.require_idle(stack_id)
        result = self.deadline.call(
            self.client.create_job,
            models.CreateJobDetails(stack_id=stack_id, job_operation_details=operation),
            opc_retry_token=retry_token(self.repository, self.run_id, stack_id, operation.operation),
        )
        job_id = resource_id(result.data.id, "ormjob")
        self.emit(f"Resource Manager {operation.operation} job: {job_id}")
        while True:
            job = self.deadline.call(self.client.get_job, job_id).data
            if job.id != job_id or job.stack_id != stack_id:
                raise DeploymentError("OCI job identity changed; operation stopped.")
            if job.lifecycle_state == "SUCCEEDED":
                return job_id
            if job.lifecycle_state not in {"ACCEPTED", "IN_PROGRESS", "CANCELING"}:
                raise DeploymentError("Resource Manager job did not succeed; inspect the reported job.")
            self.deadline.pause()

    def apply(self, stack_id, deployment_id):
        plan_id = self.run(stack_id, models.CreatePlanJobOperationDetails(is_provider_upgrade_required=False))
        apply_id = self.run(stack_id, models.CreateApplyJobOperationDetails(
            execution_plan_strategy="FROM_PLAN_JOB_ID", execution_plan_job_id=plan_id,
            is_provider_upgrade_required=False,
        ))
        return self.outputs(apply_id, deployment_id)

    def destroy(self, stack_id):
        self.run(stack_id, models.CreateDestroyJobOperationDetails(
            execution_plan_strategy="AUTO_APPROVED", is_provider_upgrade_required=False,
        ))

    def outputs(self, job_id, deployment_id):
        expected = {"artifact_bucket_name", "object_storage_namespace", "generative_ai_project_ocid"}
        result = {}
        for item in self.deadline.pages(self.client.list_job_outputs, job_id, collection=True):
            name = item.output_name
            if name not in expected:
                continue
            if name in result or item.is_sensitive is not False or item.output_type != "string":
                raise DeploymentError("Resource Manager outputs have unexpected types or sensitivity.")
            value = item.output_value
            # Resource Manager may serialize a Terraform string as JSON text.
            if isinstance(value, str) and value.startswith('"'):
                try:
                    value = json.loads(value)
                except ValueError:
                    raise DeploymentError("Resource Manager output is malformed.") from None
            if not isinstance(value, str):
                raise DeploymentError("Resource Manager output is not a string.")
            if name == "generative_ai_project_ocid":
                resource_id(value, "generativeaiproject")
            elif name == "artifact_bucket_name" and value != f"oci-energy-ai-{deployment_id}-artifacts":
                raise DeploymentError("Resource Manager bucket output does not match this deployment.")
            elif name == "object_storage_namespace" and not re.fullmatch(r"[a-zA-Z0-9_-]{1,255}", value):
                raise DeploymentError("Resource Manager namespace output is malformed.")
            result[name] = value
        if set(result) != expected:
            raise DeploymentError("Resource Manager did not return all required outputs.")
        return result
