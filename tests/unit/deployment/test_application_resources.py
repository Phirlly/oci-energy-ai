from dataclasses import replace
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from oci.object_storage.models import Bucket
from oci.apigateway.models import GatewaySummary, GatewayCollection
from oci.core.models import Instance, InstanceSourceViaImageDetails, Vnic, VnicAttachment
from oci.generative_ai.models import GenerativeAiProject
from oci.key_management.models import Vault, Key, KeyShape

from deployment.application_resources import ApplicationResources
from deployment.configuration import DeploymentError
from deployment.resource_jobs import OperationDeadline
from tests.fixtures.resource_manager import CONFIG, Clock, response
from tests.fixtures.resource_manager import APPLICATION_OUTPUTS, PROJECT_ID


TENANCY = 'ocid1.tenancy.oc1..' + 't'*32
IMAGE = 'ocid1.image.oc1.iad.' + 'm'*32
INSTANCE = 'ocid1.instance.oc1.iad.' + 'i'*32
VAULT = 'ocid1.vault.oc1.iad.' + 'v'*32
KEY = 'ocid1.key.oc1.iad.' + 'k'*32


class ApplicationResourceFixture:
    def setUp(self):
        self.clients, self.clock = Mock(), Clock()
        self.resources = ApplicationResources(self.clients, CONFIG,
            OperationDeadline(60, self.clock.monotonic, self.clock.sleep))
        self.clients.identity.list_region_subscriptions.return_value = response([
            NS(region_name=CONFIG.region, status='READY', is_home_region=True)])
        self.clients.identity.list_availability_domains.return_value = response([NS(name='z:AD2'), NS(name='a:AD1')])
        self.image = NS(id=IMAGE, compartment_id=None, operating_system='Oracle Linux',
                        operating_system_version='9.8', lifecycle_state='AVAILABLE')
        self.clients.compute.list_images.return_value = response([self.image])
        self.clients.compute.get_image.return_value = response(self.image)
        self.clients.compute.get_image_shape_compatibility_entry.return_value = response(NS(image_id=IMAGE, shape='VM.Standard.E5.Flex'))
        self.clients.compute.list_instances.return_value = response([])
        self.clients.kms.list_vaults.return_value = response([])
        self.clients.storage.get_namespace.return_value = response('fixture')
        self.bucket = Bucket(name=self.resources.name+'-artifacts', namespace='fixture', compartment_id=CONFIG.compartment_ocid,
                            public_access_type='NoPublicAccess', versioning='Disabled', freeform_tags=self.resources.tags)
        self.clients.storage.get_bucket.return_value = response(self.bucket)

    def owned(self, kind, **extra):
        return NS(id={'instance': INSTANCE, 'vault': VAULT, 'key': KEY}[kind],
                  compartment_id=CONFIG.compartment_ocid, display_name=self.resources.name + ('-secrets' if kind=='key' else ''),
                  freeform_tags=self.resources.tags, **extra)


class ApplicationResourceTests(ApplicationResourceFixture, unittest.TestCase):
    def test_root_discovery_matches_tenancy_and_rejects_foreign_root_before_calls(self):
        self.resources.config = replace(CONFIG, compartment_ocid=TENANCY)
        self.assertEqual(self.resources.topology(TENANCY, {}).tenancy_ocid, TENANCY)
        self.clients.reset_mock()
        with self.assertRaisesRegex(DeploymentError, 'root compartment'):
            self.resources.topology('ocid1.tenancy.oc1..' + 'f' * 32, {})
        self.assertEqual(self.clients.mock_calls, [])

    def test_discovery_chooses_sorted_ad_and_platform_image_then_validates_compatibility(self):
        custom = NS(**(vars(self.image) | {'compartment_id': CONFIG.compartment_ocid, 'id': IMAGE+'custom'}))
        self.clients.compute.list_images.return_value = response([custom, self.image])
        selected = self.resources.topology(TENANCY, {})
        self.assertEqual((selected.availability_domain, selected.image_ocid), ('a:AD1', IMAGE))
        self.clients.compute.get_image_shape_compatibility_entry.assert_called_once_with(IMAGE, 'VM.Standard.E5.Flex')

    def test_pinned_older_image_uses_get_not_rotating_list_and_rejects_override(self):
        selected = self.resources.topology(TENANCY, {})
        self.clients.compute.list_images.reset_mock()
        self.clients.compute.list_images.return_value = response([])
        self.assertEqual(self.resources.topology(TENANCY, {}, pinned=selected), selected)
        self.clients.compute.list_images.assert_not_called()
        with self.assertRaisesRegex(DeploymentError, 'pinned'):
            self.resources.topology(TENANCY, {'OCI_AVAILABILITY_DOMAIN': 'z:AD2'}, pinned=selected)

    def test_unsubscribed_region_custom_image_or_incompatible_shape_is_rejected(self):
        for field, value in [('compartment_id', CONFIG.compartment_ocid), ('operating_system_version', '8.9'),
                             ('lifecycle_state', 'DELETED')]:
            original = getattr(self.image, field)
            setattr(self.image, field, value)
            with self.subTest(field=field), self.assertRaises(DeploymentError):
                self.resources.topology(TENANCY, {'OCI_IMAGE_OCID': IMAGE})
            setattr(self.image, field, original)
        self.clients.identity.list_region_subscriptions.return_value.data[0].status = 'IN_PROGRESS'
        with self.assertRaises(DeploymentError):
            self.resources.topology(TENANCY, {})

    def test_retired_owned_vault_and_terminated_host_do_not_block_fresh_discovery(self):
        self.clients.compute.list_instances.return_value = response([self.owned('instance', lifecycle_state='TERMINATED')])
        self.clients.kms.list_vaults.return_value = response([self.owned('vault', lifecycle_state='PENDING_DELETION')])
        inventory = self.resources.discover()
        self.assertIsNone(inventory['instance'])
        self.assertIsNone(inventory['vault'])
        self.assertEqual(inventory['retired_vaults'], 1)

    def test_foreign_or_duplicate_current_resources_and_public_bucket_refuse_adoption(self):
        instance = self.owned('instance', lifecycle_state='RUNNING')
        self.clients.compute.list_instances.return_value = response([instance, instance])
        with self.assertRaises(DeploymentError):
            self.resources.discover()
        instance.freeform_tags = {}
        self.clients.compute.list_instances.return_value = response([instance])
        with self.assertRaises(DeploymentError):
            self.resources.discover()
        self.clients.compute.list_instances.return_value = response([])
        self.bucket.public_access_type = 'ObjectRead'
        with self.assertRaises(DeploymentError):
            self.resources.discover()

    def test_vault_inventory_rejects_unknown_key_before_any_mutation(self):
        vault = self.owned('vault', lifecycle_state='ACTIVE', vault_type='DEFAULT', management_endpoint='https://fixture.oraclecloud.com')
        self.clients.kms.list_vaults.return_value = response([vault])
        self.clients.kms.get_vault.return_value = response(vault)
        self.clients.keys.return_value.list_keys.return_value = response([
            self.owned('key', lifecycle_state='ENABLED'), NS(display_name='foreign')])
        with self.assertRaisesRegex(DeploymentError, 'key'):
            self.resources.discover()
        self.clients.compute.instance_action.assert_not_called()

    def test_stop_uses_fresh_owned_instance_and_etag_then_waits_for_poweroff(self):
        running = self.owned('instance', lifecycle_state='RUNNING')
        stopped = self.owned('instance', lifecycle_state='STOPPED')
        self.clients.compute.get_instance.side_effect = [response(running, etag='guard'), response(stopped)]
        self.resources.stop(running)
        options = self.clients.compute.instance_action.call_args.kwargs
        self.assertEqual(options['if_match'], 'guard')
        self.assertEqual(self.clients.compute.instance_action.call_args.args, (INSTANCE, 'STOP'))

    def test_missing_stop_etag_or_different_get_identity_prevents_power_action(self):
        instance = self.owned('instance', lifecycle_state='RUNNING')
        self.clients.compute.get_instance.return_value = response(instance)
        with self.assertRaises(DeploymentError):
            self.resources.stop(instance)
        self.clients.compute.instance_action.assert_not_called()

    def test_stop_after_restart_has_new_intent_while_each_guarded_action_is_stable(self):
        running = self.owned('instance', lifecycle_state='RUNNING')
        stopped = self.owned('instance', lifecycle_state='STOPPED')
        self.clients.compute.get_instance.side_effect = [response(running, etag='first'), response(stopped),
                                                         response(running, etag='restarted'), response(stopped)]
        self.resources.stop(running)
        self.resources.stop(running)
        calls = self.clients.compute.instance_action.call_args_list
        self.assertNotEqual(calls[0].kwargs['opc_retry_token'], calls[1].kwargs['opc_retry_token'])


class ApplicationOutputOwnershipTests(ApplicationResourceFixture, unittest.TestCase):
    # Actual SDK models verify field names as well as expected ownership.
    def setUp(self):
        super().setUp()
        self.topology = self.resources.topology(TENANCY, {})
        common = dict(compartment_id=CONFIG.compartment_ocid, display_name=self.resources.name,
                      freeform_tags=self.resources.tags)
        self.instance = Instance(**common, id=INSTANCE, lifecycle_state='RUNNING', shape='VM.Standard.E5.Flex',
            availability_domain=self.topology.availability_domain, source_details=InstanceSourceViaImageDetails(image_id=IMAGE))
        self.vault = Vault(**common, id=VAULT, lifecycle_state='ACTIVE', vault_type='DEFAULT',
                           management_endpoint='https://fixture.oraclecloud.com')
        self.key = Key(**(common | {'display_name': self.resources.name+'-secrets'}), id=KEY,
                       lifecycle_state='ENABLED', protection_mode='SOFTWARE', key_shape=KeyShape(algorithm='AES', length=32))
        self.project = GenerativeAiProject(**common, id=PROJECT_ID, lifecycle_state='ACTIVE')
        self.gateway = GatewaySummary(**common, id='ocid1.apigateway.oc1.iad.'+'g'*32,
            lifecycle_state='ACTIVE', endpoint_type='PUBLIC', hostname=APPLICATION_OUTPUTS['application_origin'][8:])
        self.vnic = Vnic(id='ocid1.vnic.oc1.iad.'+'n'*32, compartment_id=CONFIG.compartment_ocid,
                         private_ip='10.40.1.10', public_ip=None)
        self.clients.compute.list_instances.return_value = response([self.instance])
        self.clients.kms.list_vaults.return_value = response([self.vault])
        self.clients.kms.get_vault.return_value = response(self.vault)
        self.clients.keys.return_value.list_keys.return_value = response([self.key])
        self.clients.keys.return_value.get_key.return_value = response(self.key)
        self.clients.genai.get_generative_ai_project.return_value = response(self.project)
        self.clients.gateway.list_gateways.return_value = response(GatewayCollection(items=[self.gateway]))
        self.clients.compute.list_vnic_attachments.return_value = response([
            VnicAttachment(instance_id=INSTANCE, vnic_id=self.vnic.id, lifecycle_state='ATTACHED')])
        self.clients.network.get_vnic.return_value = response(self.vnic)
        self.outputs = APPLICATION_OUTPUTS | dict(instance_ocid=INSTANCE, vault_ocid=VAULT, key_ocid=KEY,
            generative_ai_project_ocid=PROJECT_ID, artifact_bucket_name=self.bucket.name, object_storage_namespace='fixture')

    def test_valid_owned_outputs_accept_modern_image_source_details(self):
        self.assertIsNone(self.instance.image_id)
        self.assertEqual(self.resources.verify_outputs(self.outputs, self.topology)['instance'].id, INSTANCE)

    def test_wrong_project_gateway_private_backend_key_or_image_is_rejected(self):
        variants = [(self.project, 'id', PROJECT_ID+'foreign'), (self.gateway, 'hostname', 'foreign.example'),
                    (self.vnic, 'public_ip', '203.0.113.10'), (self.vnic, 'private_ip', '10.40.1.20'),
                    (self.key, 'protection_mode', 'HSM'), (self.instance.source_details, 'image_id', IMAGE+'foreign')]
        for item, field, value in variants:
            original = getattr(item, field)
            setattr(item, field, value)
            with self.subTest(field=field), self.assertRaises(DeploymentError):
                self.resources.verify_outputs(self.outputs, self.topology)
            setattr(item, field, original)

    def test_retired_gateway_is_ignored_but_duplicate_active_gateway_is_rejected(self):
        from copy import deepcopy
        old = deepcopy(self.gateway)
        old.id += 'retired'
        old.lifecycle_state = 'DELETED'
        self.clients.gateway.list_gateways.return_value.data.items.append(old)
        self.resources.verify_outputs(self.outputs, self.topology)
        old.lifecycle_state = 'ACTIVE'
        with self.assertRaises(DeploymentError):
            self.resources.verify_outputs(self.outputs, self.topology)

    def test_vnic_and_attachment_response_identities_cannot_be_substituted(self):
        attachment = self.clients.compute.list_vnic_attachments.return_value.data[0]
        for item, field in [(attachment, 'instance_id'), (self.vnic, 'id'), (self.vnic, 'compartment_id')]:
            original = getattr(item, field)
            setattr(item, field, original+'foreign')
            with self.subTest(field=field), self.assertRaisesRegex(DeploymentError, 'VNIC'):
                self.resources.verify_outputs(self.outputs, self.topology)
            setattr(item, field, original)
