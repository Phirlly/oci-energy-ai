"""Maintainer-owned Resource Manager distribution, separate from every demo stack."""

import hashlib
import json
from pathlib import Path
import re
import tempfile

from oci.exceptions import ServiceError

from deployment.configuration import DeploymentConfiguration, DeploymentError
from deployment.resource_jobs import ResourceJobs
from deployment.resource_manager import ResourceManager
from deployment.terraform_bundle import _read_member, _write_archive


def distribution_config(repository, region, compartment):
    if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise DeploymentError('A valid owning GitHub repository is required.')
    identity = hashlib.sha256(repository.lower().encode()).hexdigest()[:12]
    return DeploymentConfiguration('releases-' + identity, region, compartment)


def build_distribution_bundle(root, output):
    root = Path(root)
    members = [(name, _read_member(root/'infra/distribution'/name))
               for name in ('main.tf', 'variables.tf', 'versions.tf')]
    members.append(('.terraform.lock.hcl', _read_member(root/'infra/terraform/.terraform.lock.hcl')))
    return _write_archive(members, output)


class DistributionJobs(ResourceJobs):
    def outputs(self, job_id, deployment_id, *, application_region=None):
        expected = {'artifact_bucket_name', 'object_storage_namespace'}
        result = {}
        for item in self.deadline.pages(self.client.list_job_outputs, job_id, collection=True):
            if item.output_name not in expected:
                continue
            if (item.output_name in result or item.is_sensitive is not False or item.output_type != 'string'):
                raise DeploymentError('Distribution output type or sensitivity is invalid.')
            value = item.output_value
            if isinstance(value, str) and value.startswith('"'):
                try:
                    value = json.loads(value)
                except ValueError:
                    raise DeploymentError('Distribution output is malformed.') from None
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', value):
                raise DeploymentError('Distribution output value is invalid.')
            result[item.output_name] = value
        if (set(result) != expected
                or result['artifact_bucket_name'] != f'oci-energy-ai-{deployment_id}-artifacts'):
            raise DeploymentError('Distribution outputs do not identify the expected bucket.')
        return result


class DistributionManager(ResourceManager):
    def __init__(self, client, config, repository, run_id, **options):
        if config != distribution_config(repository, config.region, config.compartment_ocid):
            raise DeploymentError('Distribution identity must be separate from demo deployments.')
        super().__init__(client, config, repository, run_id, **options)
        self.tags['purpose'] = 'console-distribution'
        self.jobs = DistributionJobs(client, self.deadline, repository, run_id, self.emit)

    def _verify(self, stack):
        super()._verify(stack)
        if stack.variables != self.config.terraform_variables():
            raise DeploymentError('Distribution stack variables do not match; refusing adoption.')

    def _bucket(self, storage, namespace, *, allow_missing=False):
        name = f'oci-energy-ai-{self.config.deployment_id}-artifacts'
        absent = object()
        def read():
            try:
                return storage.get_bucket(namespace, name).data
            except ServiceError as error:
                if error.status == 404 and allow_missing:
                    return absent
                raise
        bucket = self.deadline.call(read)
        if bucket is absent:
            return
        if bucket is None:
            raise DeploymentError('Distribution bucket metadata is missing; refusing publication.')
        tags = {key: value for key, value in self.tags.items() if key != 'repository'}
        if (bucket.name != name or bucket.namespace != namespace
                or bucket.compartment_id != self.config.compartment_ocid
                or bucket.public_access_type != 'ObjectReadWithoutList'
                or bucket.storage_tier != 'Standard' or bucket.versioning != 'Disabled'
                or any((bucket.freeform_tags or {}).get(k) != v for k, v in tags.items())):
            raise DeploymentError('Distribution bucket ownership or access differs; refusing publication.')

    def provision(self, root, storage):
        namespace = self.deadline.call(storage.get_namespace).data
        if not isinstance(namespace, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,255}', namespace):
            raise DeploymentError('Object Storage namespace is invalid.')
        self._bucket(storage, namespace, allow_missing=True)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)/'distribution.zip'
            build_distribution_bundle(root, archive)
            outputs = self.apply(archive.read_bytes())
        if outputs['object_storage_namespace'] != namespace:
            raise DeploymentError('Distribution namespace does not match the authenticated tenancy.')
        self._bucket(storage, namespace)
        return outputs
