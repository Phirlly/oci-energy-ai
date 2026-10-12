import base64
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
from zipfile import ZipFile

from oci.exceptions import ServiceError
from oci.resource_manager import models

from deployment.configuration import DeploymentError
from deployment.distribution import DistributionManager, distribution_config, build_distribution_bundle
from tests.fixtures.resource_manager import CONFIG, REPOSITORY, client, response, stack


ROOT = Path(__file__).resolve().parents[3]


class DistributionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.config = distribution_config(REPOSITORY, CONFIG.region, CONFIG.compartment_ocid)
        self.client, self.storage = client(), Mock()
        self.manager = DistributionManager(self.client, self.config, REPOSITORY, '123-1')
        self.owned = stack(display_name=self.manager.name, variables=self.config.terraform_variables(),
                           freeform_tags=self.manager.tags)
        self.client.get_stack.return_value = response(self.owned, etag='guard')
        self.client.create_stack.return_value = response(self.owned)
        self.bucket = NS(name=f'oci-energy-ai-{self.config.deployment_id}-artifacts', namespace='fixture',
            compartment_id=CONFIG.compartment_ocid, public_access_type='ObjectReadWithoutList',
            storage_tier='Standard', versioning='Disabled', freeform_tags={
                'application': 'oci-energy-ai', 'deployment_id': self.config.deployment_id,
                'managed_by': 'terraform', 'purpose': 'console-distribution'})
        self.storage.get_namespace.return_value = response('fixture')
        self.storage.get_bucket.return_value = response(self.bucket)
        self.outputs = [models.JobOutputSummary(output_name=k, output_value=json.dumps(v),
                         output_type='string', is_sensitive=False) for k, v in {
            'artifact_bucket_name': self.bucket.name, 'object_storage_namespace': 'fixture'}.items()]
        self.client.list_job_outputs.return_value = response(models.JobOutputsCollection(items=self.outputs))

    def test_separate_identity_and_exact_two_outputs_without_unused_project(self):
        self.assertNotEqual(self.config.deployment_id, CONFIG.deployment_id)
        self.assertEqual(self.config, distribution_config(REPOSITORY.upper(), CONFIG.region, CONFIG.compartment_ocid))
        result = self.manager.provision(ROOT, self.storage)
        self.assertEqual(result, {'artifact_bucket_name': self.bucket.name, 'object_storage_namespace': 'fixture'})
        details = self.client.create_stack.call_args.args[0]
        self.assertEqual(details.freeform_tags['purpose'], 'console-distribution')
        self.assertEqual(details.variables, self.config.terraform_variables())
        self.assertTrue(base64.b64decode(details.config_source.zip_file_base64_encoded).startswith(b'PK'))
        self.client.get_stack_tf_state.assert_not_called()

    def test_private_foreign_moved_or_reconfigured_bucket_stops_before_stack_mutation(self):
        for field, value in [('public_access_type', 'NoPublicAccess'), ('freeform_tags', {}),
                             ('compartment_id', 'foreign'), ('namespace', 'other'),
                             ('versioning', 'Enabled'), ('storage_tier', 'Archive')]:
            original = getattr(self.bucket, field)
            setattr(self.bucket, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(DeploymentError, 'bucket'):
                self.manager.provision(ROOT, self.storage)
            self.client.create_stack.assert_not_called()
            self.client.create_job.assert_not_called()
            setattr(self.bucket, field, original)

    def test_new_bucket_is_verified_again_after_plan_bound_apply(self):
        self.storage.get_bucket.side_effect = [ServiceError(404, 'NotFound', {}, ''), response(self.bucket)]
        self.manager.provision(ROOT, self.storage)
        self.assertEqual(self.storage.get_bucket.call_count, 2)
        self.assertEqual([x.args[0].job_operation_details.operation for x in self.client.create_job.call_args_list],
                         ['PLAN', 'APPLY'])

    def test_empty_bucket_metadata_is_rejected_before_apply_and_after_creation(self):
        for stage in ('before', 'after'):
            self.storage.get_bucket.side_effect = ([response(None), response(self.bucket)] if stage == 'before'
                                                   else [response(self.bucket), response(None)])
            self.client.create_stack.reset_mock()
            with self.subTest(stage=stage):
                with self.assertRaisesRegex(DeploymentError, 'bucket'):
                    self.manager.provision(ROOT, self.storage)
                if stage == 'before':
                    self.assertFalse(self.client.create_stack.called)

    def test_stack_requires_purpose_and_exact_variables_and_update_etag(self):
        self.client.list_stacks.return_value = response([self.owned])
        self.manager.provision(ROOT, self.storage)
        self.assertEqual(self.client.update_stack.call_args.kwargs['if_match'], 'guard')
        for changes in [dict(freeform_tags={}), dict(variables=self.owned.variables | {'application': 'null'})]:
            current = dict(display_name=self.manager.name, variables=self.config.terraform_variables(),
                           freeform_tags=self.manager.tags) | changes
            self.client.get_stack.return_value = response(stack(**current), etag='guard')
            self.client.update_stack.reset_mock()
            with self.subTest(changes=changes), self.assertRaises(DeploymentError):
                self.manager.provision(ROOT, self.storage)
            self.client.update_stack.assert_not_called()

    def test_missing_duplicate_sensitive_and_mismatched_namespace_outputs_fail(self):
        variants = [self.outputs[:1], self.outputs + [self.outputs[0]],
                    [models.JobOutputSummary(output_name='artifact_bucket_name', output_type='string',
                         output_value=self.bucket.name, is_sensitive=True), self.outputs[1]],
                    [self.outputs[0], models.JobOutputSummary(output_name='object_storage_namespace',
                         output_type='string', output_value='other', is_sensitive=False)]]
        for values in variants:
            self.client.list_job_outputs.return_value = response(models.JobOutputsCollection(items=values))
            with self.subTest(count=len(values)), self.assertRaises(DeploymentError):
                self.manager.provision(ROOT, self.storage)


class DistributionPackagingTests(unittest.TestCase):
    def test_exact_deterministic_members_use_same_provider_lock_and_preserve_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            a, b = Path(temporary)/'a.zip', Path(temporary)/'b.zip'
            self.assertEqual(build_distribution_bundle(ROOT, a), build_distribution_bundle(ROOT, b))
            with ZipFile(a) as bundle:
                self.assertEqual(set(bundle.namelist()), {'.terraform.lock.hcl', 'main.tf', 'variables.tf', 'versions.tf'})
                self.assertEqual(bundle.read('.terraform.lock.hcl'), (ROOT/'infra/terraform/.terraform.lock.hcl').read_bytes())
                self.assertEqual(bundle.read('.terraform.lock.hcl'), (ROOT/'infra/distribution/.terraform.lock.hcl').read_bytes())
            with self.assertRaises(FileExistsError):
                build_distribution_bundle(ROOT, a)
