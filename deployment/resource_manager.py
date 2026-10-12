"""Manage only this repository's explicitly owned Terraform stack."""

import base64
import re
import time

from oci.resource_manager import models

from deployment.application_configuration import ApplicationConfiguration, stack_application
from deployment.configuration import DeploymentError, validate_compartment_tenancy
from deployment.resource_jobs import OperationDeadline, ResourceJobs, resource_id, retry_token


class ResourceManager:
    def __init__(self, client, config, repository, run_id, *, emit=lambda message: None,
                 monotonic=time.monotonic, sleep=time.sleep, timeout=1200):
        if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise DeploymentError("A valid owning GitHub repository is required.")
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9]+-[0-9]+", run_id):
            raise DeploymentError("A GitHub run and attempt identifier is required.")
        self.client = client
        self.config = config
        self.repository = repository
        self.name = f"oci-energy-ai-{config.deployment_id}"
        self.tags = {"application": "oci-energy-ai", "deployment_id": config.deployment_id,
                     "repository": repository, "managed_by": "terraform"}
        self.emit = emit
        self.deadline = OperationDeadline(timeout, monotonic, sleep)
        self.jobs = ResourceJobs(client, self.deadline, repository, run_id, emit)

    def _verify(self, stack):
        resource_id(stack.id, "ormstack")
        try:
            stack_application(stack.variables, self.config)
        except ValueError:
            raise DeploymentError("Stack configuration does not match; refusing adoption.") from None
        if (stack.display_name != self.name or stack.compartment_id != self.config.compartment_ocid
                or stack.terraform_version != "1.5.x"
                or any((stack.freeform_tags or {}).get(key) != value for key, value in self.tags.items())):
            raise DeploymentError("Stack ownership or deployment configuration does not match; refusing adoption.")

    def _discover(self):
        candidates = []
        for stack in self.deadline.pages(self.client.list_stacks, compartment_id=self.config.compartment_ocid):
            tags = stack.freeform_tags or {}
            if stack.display_name == self.name or (
                tags.get("application") == "oci-energy-ai"
                and tags.get("deployment_id") == self.config.deployment_id
                and tags.get("repository") == self.repository
            ):
                candidates.append(stack)
        if len(candidates) > 1:
            raise DeploymentError("Multiple matching stacks found; resolve the collision before retrying.")
        if not candidates:
            return None
        stack_id = resource_id(candidates[0].id, "ormstack")
        self.emit(f"Resource Manager stack: {stack_id}")
        result = self._active_stack(stack_id)
        self.jobs.require_idle(stack_id)
        return result

    def _active_stack(self, stack_id):
        while True:
            result = self.deadline.call(self.client.get_stack, stack_id)
            if result.data.id != stack_id:
                raise DeploymentError("OCI stack identity changed; operation stopped.")
            self._verify(result.data)
            state = result.data.lifecycle_state
            if state == "ACTIVE":
                return result
            if state not in {"CREATING", "UPDATING"}:
                raise DeploymentError("Stack is not usable; inspect its state before retrying.")
            self.deadline.pause()

    def application_configuration(self, *, require_stack=False):
        """Read pinned topology without reselecting an image or changing the stack."""
        existing = self._discover()
        if require_stack and existing is None:
            raise DeploymentError("No owned stack exists; refusing resource cleanup.")
        return stack_application(existing.data.variables, self.config) if existing else None

    def foundation_outputs(self):
        """Read the current foundation, including within a hosted application."""
        return self._current_outputs()

    def application_outputs(self):
        return self._current_outputs(application=True)

    def _current_outputs(self, *, application=False):
        existing = self._discover()
        if existing is None:
            raise DeploymentError("No owned foundation found; run Bootstrap OCI foundation first.")
        if application and stack_application(existing.data.variables, self.config) is None:
            raise DeploymentError("The owned stack has no application configuration.")
        stack_id = existing.data.id
        jobs = self.deadline.call(self.client.list_jobs, stack_id=stack_id,
                                  sort_by="TIMECREATED", sort_order="DESC", limit=1).data
        if (len(jobs) != 1 or jobs[0].stack_id != stack_id
                or jobs[0].operation != "APPLY" or jobs[0].lifecycle_state != "SUCCEEDED"):
            raise DeploymentError("Latest foundation job must be a successful APPLY; inspect the stack.")
        return self.jobs.outputs(resource_id(jobs[0].id, "ormjob"), self.config.deployment_id,
                                 **({"application_region": self.config.region} if application else {}))

    def apply(self, archive):
        existing = self._discover()
        self._require_foundation(existing)
        return self._apply(archive, existing, self.config.terraform_variables())

    def apply_application(self, archive, application):
        self._validate_application(application)
        existing = self._discover()
        self._require_application(existing, application, allow_foundation=True)
        variables = self.config.terraform_variables() | {"application": application.to_json()}
        return self._apply(archive, existing, variables, application=True)

    def _apply(self, archive, existing, variables, *, application=False):
        encoded = base64.b64encode(archive).decode("ascii")
        if existing is None:
            result = self.deadline.call(
                self.client.create_stack,
                models.CreateStackDetails(
                    compartment_id=self.config.compartment_ocid, display_name=self.name,
                    config_source=models.CreateZipUploadConfigSourceDetails(zip_file_base64_encoded=encoded),
                    variables=variables, terraform_version="1.5.x", freeform_tags=self.tags,
                ),
                opc_retry_token=retry_token(self.repository, self.config.compartment_ocid,
                                           self.config.region, self.config.deployment_id),
            )
            stack_id = resource_id(result.data.id, "ormstack")
            self.emit(f"Resource Manager stack: {stack_id}")
        else:
            stack_id = existing.data.id
            etag = existing.headers.get("etag")
            if not isinstance(etag, str) or not etag:
                raise DeploymentError("Stack ETag missing; refusing an unguarded update.")
            self.deadline.call(
                self.client.update_stack, stack_id,
                models.UpdateStackDetails(
                    config_source=models.UpdateZipUploadConfigSourceDetails(zip_file_base64_encoded=encoded),
                    variables=variables, terraform_version="1.5.x",
                ),
                if_match=etag,
            )
        current = self._active_stack(stack_id)
        if current.data.variables != variables:
            raise DeploymentError("Stack update did not retain the requested configuration; no job submitted.")
        return self.jobs.apply(stack_id, self.config.deployment_id,
                               **({"application_region": self.config.region} if application else {}))

    def _require_foundation(self, existing):
        if existing and stack_application(existing.data.variables, self.config) is not None:
            raise DeploymentError("Application hosting is configured; use the application deployment workflow.")

    def _validate_application(self, application):
        try:
            if not isinstance(application, ApplicationConfiguration):
                raise ValueError()
            application.validate_region(self.config.region)
            validate_compartment_tenancy(self.config.compartment_ocid, application.tenancy_ocid)
        except ValueError:
            raise DeploymentError("Invalid application topology for this deployment.") from None

    def _require_application(self, existing, application, *, allow_foundation=False):
        current = stack_application(existing.data.variables, self.config) if existing else None
        if current != application and not (allow_foundation and current is None):
            raise DeploymentError("Application topology differs; refusing replacement or downgrade.")

    def destroy(self, confirmation):
        if confirmation != self.config.deployment_id:
            raise DeploymentError("Destroy confirmation must equal DEPLOYMENT_ID.")
        existing = self._discover()
        self._require_foundation(existing)
        if existing is None:
            return False
        self.jobs.destroy(existing.data.id)
        return True

    def destroy_application(self, confirmation, application):
        if confirmation != self.config.deployment_id:
            raise DeploymentError("Destroy confirmation must equal DEPLOYMENT_ID.")
        self._validate_application(application)
        existing = self._discover()
        if existing is None:
            return False
        self._require_application(existing, application)
        self.jobs.destroy(existing.data.id)
        return True
