"""Coordinate the owned OCI demo lifecycle; SDK, host and HTTP boundaries stay separate."""

from pathlib import Path
import re
import tempfile
import time
from uuid import uuid4

import httpx

from deployment.application_resources import ApplicationResources
from deployment.configuration import DeploymentError
from deployment.host_commands import HostCommands, HostCommandFailed
from deployment.release_artifacts import ReleaseArtifacts, host_digest, image_manifest, manifest_bytes
from deployment.resource_jobs import OperationDeadline
from deployment.resource_manager import ResourceManager
from deployment.runtime_secrets import RuntimeSecrets
from deployment.terraform_bundle import build_bundle
from deployment.verify_hosted import HostedVerifier
from energy_ai.web.hosted_configuration import HostedConfiguration


OPERATION_TIMEOUT = 7200
BOOTSTRAP_TIMEOUT = 1800


class Delivery:
    def __init__(self, clients, config, environment, root, *, monotonic=time.monotonic,
                 sleep=time.sleep, emit=print):
        self.clients, self.config, self.environment, self.root = clients, config, environment, Path(root)
        self.repository = environment.get('GITHUB_REPOSITORY', '')
        self.run, self.attempt = environment.get('GITHUB_RUN_ID', ''), int(environment.get('GITHUB_RUN_ATTEMPT', '0'))
        self.model_ids = {role: environment[setting] for role, setting in
            [('oci', 'OCI_MODEL'), ('openai', 'OPENAI_MODEL'), ('anthropic', 'ANTHROPIC_MODEL')]
            if environment.get(setting) and (role == 'oci' or environment.get(role.upper() + '_API_KEY'))}
        self.emit = emit
        self.deadline = OperationDeadline(OPERATION_TIMEOUT, monotonic, sleep)
        self.manager = ResourceManager(clients.resource, config, self.repository, f'{self.run}-{self.attempt}',
            timeout=OPERATION_TIMEOUT, monotonic=monotonic, sleep=sleep, emit=emit)
        self.resources = ApplicationResources(clients, config, self.deadline)
        self.helper_digest = host_digest(self.root)

    def _child_deadline(self, seconds):
        return OperationDeadline(min(seconds, self.deadline.end - self.deadline.monotonic()),
                                 self.deadline.monotonic, self.deadline.sleep)

    def _commands(self, instance, deadline=None):
        return HostCommands(self.clients.agent, self.config, self.repository, instance.id,
                            self.helper_digest, deadline or self.deadline)

    def _status(self, commands):
        # Stored Run Command output is not a new observation on replay.
        return commands.status(f'status-{self.run}-{self.attempt}-{uuid4().hex}')

    def _ready(self, instance):
        budget = self._child_deadline(BOOTSTRAP_TIMEOUT)
        commands = self._commands(instance, budget)
        while True:
            try:
                result = self._status(commands)
                if result['status'] == 'ready':
                    return result
            except HostCommandFailed:
                pass  # Fixed helper can be unavailable until cloud-init finishes.
            budget.pause()

    def _secrets(self, inventory):
        return RuntimeSecrets(self.clients.vaults, self.clients.secrets, self.config, self.repository,
            inventory['vault'].id, inventory['key'].id if inventory['key'] else None, self.deadline)

    def _artifacts(self, inventory):
        if inventory['bucket'] is None:
            raise DeploymentError('Owned artifact bucket is missing.')
        return ReleaseArtifacts(self.clients.storage, inventory['namespace'], inventory['bucket'].name,
                                self.deadline, self.helper_digest)

    def _http(self, manifest, *, full=False):
        runtime = HostedConfiguration.from_bytes(manifest_bytes(manifest['runtime']))
        with httpx.Client(base_url=runtime.origin, timeout=30, trust_env=False, follow_redirects=False) as client:
            return HostedVerifier(client, runtime, self.environment['DEMO_PASSWORD'], manifest['release'],
                                  self.deadline).check(full=full)

    def _selection(self, commands, digest, manifest):
        state = self._status(commands)
        if (state.get('status') != 'ready' or state['current'] != digest or state['candidate'] is not None
                or state['release'] != manifest['release']):
            raise DeploymentError('Fresh host state does not match the requested release.')
        return state

    def _manifest(self, artifacts, digest, outputs, secrets):
        manifest = artifacts.get_manifest(digest)
        runtime = manifest['runtime']
        expected = dict(region=self.config.region, project=outputs['generative_ai_project_ocid'],
                        origin=outputs['application_origin'], backend_host=outputs['backend_host'])
        inventory = secrets.inventory()
        if (any(runtime.get(k) != v for k, v in expected.items())
                or any(role not in inventory or inventory[role].data.id != identifier
                       or inventory[role].data.lifecycle_state != 'ACTIVE'
                       for role, identifier in runtime['secret_ids'].items())):
            raise DeploymentError('Retained release runtime does not match the owned deployment.')
        return manifest

    def apply(self, archive, image_id, release):
        if any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value)
               for value in self.model_ids.values()):
            raise DeploymentError('Invalid configured runtime model identifier.')
        pinned = self.manager.application_configuration()
        topology = self.resources.topology(self.environment['OCI_TENANCY_OCID'], self.environment, pinned=pinned)
        existing = self.resources.discover()
        if existing['instance'] is not None:
            self._commands(existing['instance']).settle()
            self._ready(existing['instance'])  # Helper compatibility before Terraform or credential changes.
        self.emit('Applying verified Terraform configuration through Resource Manager.')
        with tempfile.TemporaryDirectory(prefix='energy-terraform-') as temporary:
            bundle = Path(temporary) / 'terraform.zip'
            build_bundle(self.root, bundle)
            outputs = self.manager.apply_application(bundle.read_bytes(), topology)
        inventory = self.resources.verify_outputs(outputs, topology)
        self.emit('Waiting for the private host bootstrap and runtime identity.')
        self._ready(inventory['instance'])
        values = {'demo_password': self.environment['DEMO_PASSWORD']}
        for role, setting in [('openai', 'OPENAI_API_KEY'), ('anthropic', 'ANTHROPIC_API_KEY')]:
            if self.environment.get(setting):
                values[role] = self.environment[setting]
        secret_ids = self._secrets(inventory).synchronize(values)
        runtime = dict(version=1, region=self.config.region, project=outputs['generative_ai_project_ocid'],
                       origin=outputs['application_origin'], backend_host=outputs['backend_host'],
                       secret_ids=secret_ids, model_ids=self.model_ids)
        manifest = image_manifest(archive, image_id, release, runtime, self.helper_digest)
        artifacts = self._artifacts(inventory)
        digest = artifacts.publish(archive, manifest)
        commands = self._commands(inventory['instance'])
        retry_until, number = self.deadline.monotonic() + BOOTSTRAP_TIMEOUT, 0
        while True:
            try:
                commands.activate(digest, f'apply-{self.run}-{self.attempt}-retry-{number}')
                break
            except HostCommandFailed:
                if self.deadline.monotonic() >= retry_until:
                    raise
                self.emit('Completed activation failed; allowing bounded runtime IAM propagation before retry.')
                self.deadline.sleep(min(30, retry_until - self.deadline.monotonic()))
                self.deadline.check()
                number += 1
        state = self._selection(commands, digest, manifest)
        checks = self._http(manifest)
        commands.settle()
        artifacts.prune({state['current'], state['previous']} - {None})
        return dict(operation='apply', origin=outputs['application_origin'], release=release, checks=checks)

    def _live(self):
        topology = self.manager.application_configuration()
        if topology is None:
            raise DeploymentError('No application deployment is configured.')
        outputs = self.manager.application_outputs()
        inventory = self.resources.verify_outputs(outputs, topology)
        commands = self._commands(inventory['instance'])
        commands.settle()
        state = self._ready(inventory['instance'])
        return outputs, inventory, commands, state

    def rollback(self):
        outputs, inventory, commands, state = self._live()
        identity = f'rollback-{self.run}'
        target = commands.rollback_target(identity, attempt=self.attempt, previous=state['previous'])
        artifacts = self._artifacts(inventory)
        manifest = self._manifest(artifacts, target, outputs, self._secrets(inventory))
        commands.activate(target, identity)
        state = self._selection(commands, target, manifest)
        checks = self._http(manifest)
        commands.settle()
        artifacts.prune({state['current'], state['previous']} - {None})
        return dict(operation='rollback', origin=outputs['application_origin'], release=manifest['release'], checks=checks)

    def verify(self):
        outputs, inventory, commands, state = self._live()
        manifest = self._manifest(self._artifacts(inventory), state['current'], outputs, self._secrets(inventory))
        self._selection(commands, state['current'], manifest)
        checks = self._http(manifest, full=True)
        return dict(operation='verify', origin=outputs['application_origin'], release=manifest['release'], checks=checks)

    def destroy(self, confirmation):
        if confirmation != self.config.deployment_id:
            raise DeploymentError('Destroy confirmation must equal DEPLOYMENT_ID.')
        topology = self.manager.application_configuration(require_stack=True)
        inventory = self.resources.discover()
        secrets = self._secrets(inventory) if inventory['vault'] else None
        secret_inventory = secrets.inventory() if secrets else None
        artifacts = self._artifacts(inventory) if inventory['bucket'] else None
        objects = artifacts.inventory() if artifacts else None
        if topology is None and (inventory['instance'] or inventory['vault']):
            raise DeploymentError('Hosting resources exist without owned application topology; cleanup refused.')
        # Full child inventories above must pass before stopping anything.
        if inventory['instance']:
            self.resources.stop(inventory['instance'])
        if secrets:
            secrets.schedule_deletion(secret_inventory)
        if artifacts:
            artifacts.prune(set(), inventory=objects)
        if topology is None:
            self.manager.destroy(confirmation)
        else:
            self.manager.destroy_application(confirmation, topology)
        return dict(operation='destroy', stack='retained', history='deleted',
                    credential_deletion='scheduled; OCI waiting periods still apply',
                    already_retired_vaults=inventory['retired_vaults'])
