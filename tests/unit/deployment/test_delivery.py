from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from deployment.configuration import DeploymentError
from deployment.delivery import Delivery
from deployment.host_commands import HostCommandFailed
from tests.fixtures.deployment_environment import configured_environment
from tests.fixtures.host_release import release, HOST_DIGEST
from tests.fixtures.resource_manager import CONFIG, Clock, REPOSITORY, APPLICATION_OUTPUTS, PROJECT_ID
from tests.fixtures.resource_manager import client as resource_client
from deployment.resource_manager import ResourceManager as RealResourceManager


class DeliveryOrderingTests(unittest.TestCase):
    def setUp(self):
        self.environment = configured_environment() | dict(GITHUB_REPOSITORY=REPOSITORY,
            GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', DEMO_PASSWORD='admin', DEPLOYMENT_ID=CONFIG.deployment_id)
        self.mocks = {name: self.enterContext(patch('deployment.delivery.' + name)) for name in (
            'ResourceManager', 'ApplicationResources', 'HostCommands', 'RuntimeSecrets',
            'ReleaseArtifacts', 'host_digest', 'image_manifest', 'HostedVerifier')}
        self.clock = Clock()
        self.delivery = Delivery(Mock(), CONFIG, self.environment, Path('.'), monotonic=self.clock.monotonic,
                                 sleep=self.clock.sleep, emit=lambda _: None)
        self.manager = self.mocks['ResourceManager'].return_value
        self.resources = self.mocks['ApplicationResources'].return_value
        self.commands = self.mocks['HostCommands'].return_value
        self.artifacts = self.mocks['ReleaseArtifacts'].return_value
        self.secrets = self.mocks['RuntimeSecrets'].return_value
        self.digest, _, self.manifest, _ = release()
        self.mocks['host_digest'].return_value = HOST_DIGEST
        self.mocks['image_manifest'].return_value = self.manifest
        self.delivery.helper_digest = HOST_DIGEST
        self.inventory = dict(instance=NS(id=APPLICATION_OUTPUTS['instance_ocid']),
                              vault=NS(id=APPLICATION_OUTPUTS['vault_ocid']), key=NS(id=APPLICATION_OUTPUTS['key_ocid']),
                              namespace='fixture', bucket=NS(name='oci-energy-ai-energy-demo-artifacts'), retired_vaults=0)
        self.resources.discover.return_value = self.inventory
        self.resources.verify_outputs.return_value = self.inventory
        self.outputs = APPLICATION_OUTPUTS | dict(object_storage_namespace='fixture',
            artifact_bucket_name=self.inventory['bucket'].name, generative_ai_project_ocid=self.manifest['runtime']['project'])
        self.manager.apply_application.return_value = self.outputs
        self.manager.application_outputs.return_value = self.outputs
        self.secrets.synchronize.return_value = self.manifest['runtime']['secret_ids']
        self.secrets.inventory.return_value = {role: NS(data=NS(id=identifier, lifecycle_state='ACTIVE'))
            for role, identifier in self.manifest['runtime']['secret_ids'].items()}
        self.artifacts.publish.return_value = self.digest
        self.artifacts.get_manifest.return_value = self.manifest
        self.state = dict(version=1, status='ready', host_digest=HOST_DIGEST,
                          current=self.digest, previous=None, candidate=None, release=self.manifest['release'])
        self.commands.status.return_value = self.state
        self.commands.activate.return_value = self.state
        self.order = Mock()
        for name, item in [('manager', self.manager), ('resources', self.resources), ('commands', self.commands),
                           ('artifacts', self.artifacts), ('secrets', self.secrets)]:
            self.order.attach_mock(item, name)

    def apply(self):
        with patch('deployment.delivery.build_bundle'), patch('pathlib.Path.read_bytes', return_value=b'zip'):
            return self.delivery.apply(Path('image.tar'), self.manifest['image_id'], self.manifest['release'])

    def test_apply_checks_existing_host_before_terraform_and_upload_before_activation(self):
        self.apply()
        names = [call[0] for call in self.order.mock_calls]
        self.assertLess(names.index('commands.status'), names.index('manager.apply_application'))
        self.assertLess(names.index('secrets.synchronize'), names.index('artifacts.publish'))
        self.assertLess(names.index('artifacts.publish'), names.index('commands.activate'))
        self.assertLess(names.index('commands.activate'), names.index('artifacts.prune'))
        observations = [call.args[0] for call in self.commands.status.call_args_list]
        self.assertEqual(len(observations), len(set(observations)))

    def test_incompatible_existing_helper_fails_before_infrastructure_or_secret_changes(self):
        self.commands.status.side_effect = DeploymentError('Host compatibility failed.')
        with self.assertRaises(DeploymentError):
            self.apply()
        self.manager.apply_application.assert_not_called()
        self.secrets.synchronize.assert_not_called()

    def test_failed_completed_activation_can_retry_but_ambiguous_completion_cannot(self):
        self.commands.activate.side_effect = [HostCommandFailed('fixture'), self.state]
        self.apply()
        intents = [call.args[1] for call in self.commands.activate.call_args_list]
        self.assertEqual(len(set(intents)), 2)
        self.commands.activate.reset_mock(side_effect=True)
        self.commands.activate.side_effect = DeploymentError('Completion uncertain.')
        with self.assertRaises(DeploymentError):
            self.apply()
        self.commands.activate.assert_called_once()

    def test_stale_post_activation_state_prevents_success_and_pruning(self):
        self.commands.status.side_effect = [self.state, self.state, self.state | {'current': 'b'*64}]
        with self.assertRaises(DeploymentError):
            self.apply()
        self.artifacts.prune.assert_not_called()

    def test_rollback_recovers_fixed_run_identity_without_infrastructure_or_secret_mutation(self):
        self.commands.rollback_target.return_value = self.digest
        self.delivery.rollback()
        self.commands.rollback_target.assert_called_once_with('rollback-123', attempt=1, previous=None)
        self.commands.activate.assert_called_once_with(self.digest, 'rollback-123')
        self.manager.apply_application.assert_not_called()
        self.secrets.synchronize.assert_not_called()

    def test_rollback_refuses_foreign_runtime_or_inactive_secret_before_activation(self):
        from copy import deepcopy
        self.commands.rollback_target.return_value = self.digest
        for variant in ('origin', 'secret_id', 'pending_secret'):
            manifest = deepcopy(self.manifest)
            secret = self.secrets.inventory.return_value['demo_password'].data
            secret.lifecycle_state = 'ACTIVE'
            if variant == 'origin':
                manifest['runtime']['origin'] = 'https://foreign.example'
            elif variant == 'secret_id':
                manifest['runtime']['secret_ids']['demo_password'] += 'foreign'
            else:
                secret.lifecycle_state = 'PENDING_DELETION'
            self.artifacts.get_manifest.return_value = manifest
            with self.subTest(variant=variant), self.assertRaisesRegex(DeploymentError, 'runtime'):
                self.delivery.rollback()
        self.commands.activate.assert_not_called()
        self.artifacts.prune.assert_not_called()

    def test_destroy_inventories_every_child_before_stop_and_retains_stack(self):
        self.delivery.destroy(CONFIG.deployment_id)
        names = [call[0] for call in self.order.mock_calls]
        self.assertLess(names.index('secrets.inventory'), names.index('resources.stop'))
        self.assertLess(names.index('artifacts.inventory'), names.index('resources.stop'))
        self.assertLess(names.index('resources.stop'), names.index('secrets.schedule_deletion'))
        self.assertLess(names.index('artifacts.prune'), names.index('manager.destroy_application'))

    def test_unknown_child_or_wrong_confirmation_causes_no_cleanup_mutation(self):
        with self.assertRaises(DeploymentError):
            self.delivery.destroy('wrong')
        self.resources.discover.assert_not_called()
        self.secrets.inventory.side_effect = DeploymentError('Unknown child.')
        with self.assertRaises(DeploymentError):
            self.delivery.destroy(CONFIG.deployment_id)
        self.resources.stop.assert_not_called()
        self.secrets.schedule_deletion.assert_not_called()
        self.manager.destroy_application.assert_not_called()

    def test_missing_owned_stack_cannot_purge_even_a_matching_populated_bucket(self):
        self.delivery.manager = RealResourceManager(resource_client(), CONFIG, REPOSITORY, '123-1')
        self.resources.discover.return_value = self.inventory | {'instance': None, 'vault': None, 'key': None}
        with self.assertRaisesRegex(DeploymentError, 'owned stack'):
            self.delivery.destroy(CONFIG.deployment_id)
        self.artifacts.prune.assert_not_called()
        self.resources.stop.assert_not_called()

    def test_owned_foundation_cleanup_and_destroy_ignore_unused_invalid_model_setting(self):
        self.environment['OCI_MODEL'] = 'invalid model'
        delivery = Delivery(Mock(), CONFIG, self.environment, Path('.'), monotonic=self.clock.monotonic,
                            sleep=self.clock.sleep, emit=lambda _: None)
        self.manager.application_configuration.return_value = None
        self.resources.discover.return_value = self.inventory | {'instance': None, 'vault': None, 'key': None}
        delivery.destroy(CONFIG.deployment_id)
        self.manager.application_configuration.assert_called_once_with(require_stack=True)
        self.manager.destroy.assert_called_once_with(CONFIG.deployment_id)

    def test_explicit_provider_model_is_preserved_in_runtime_manifest(self):
        self.environment['OCI_MODEL'] = 'fixture.model-v2'
        delivery = Delivery(Mock(), CONFIG, self.environment, Path('.'), monotonic=self.clock.monotonic,
                            sleep=self.clock.sleep, emit=lambda _: None)
        with patch('deployment.delivery.build_bundle'), patch('pathlib.Path.read_bytes', return_value=b'zip'):
            delivery.apply(Path('image.tar'), self.manifest['image_id'], self.manifest['release'])
        runtime = self.mocks['image_manifest'].call_args.args[3]
        self.assertEqual(runtime['model_ids'], {'oci': 'fixture.model-v2'})
