"""Bounded fixed Run Commands with recoverable intent and verified completion."""

import re

from oci.compute_instance_agent import models
from oci.exceptions import ServiceError

from deployment.application_configuration import regional_identifier
from deployment.configuration import DeploymentError
from deployment.resource_jobs import retry_token
from infra.terraform.host.contracts import bounded_json, digest_value


_ENTRYPOINT = 'sudo /usr/local/sbin/oci-energy-ai '
# Covers download/load plus interrupted-candidate reconciliation and failed-candidate
# recovery. Coordinator and workflow budgets also include infrastructure/IAM waits.
ACTIVATION_TIMEOUT = 3600


class HostCommandFailed(DeploymentError):
    """A concrete completed process failed; distinct from ambiguous completion."""


class HostCommands:
    def __init__(self, client, config, repository, instance_id, helper_digest, deadline):
        self.client, self.config, self.instance_id = client, config, instance_id
        self.helper_digest, self.deadline = helper_digest, deadline
        if not regional_identifier(instance_id, 'instance', config.region) or not digest_value(helper_digest):
            raise DeploymentError('Invalid host command identity.')
        self.prefix = 'energy-' + retry_token(repository, config.compartment_ocid, instance_id)[:32] + '-'

    def _name(self, operation, identity):
        if not isinstance(identity, str) or not identity or len(identity) > 256:
            raise DeploymentError('Invalid deployment command intent.')
        return self.prefix + operation + '-' + retry_token(identity)[:32]

    def _verify(self, command, name):
        try:
            source, output = command.content.source, command.content.output
            operation = name[len(self.prefix):].split('-')[0]
            body = source.text
            valid_body = (body == _ENTRYPOINT + 'status' if operation == 'status' else
                          bool(re.fullmatch(re.escape(_ENTRYPOINT) + r'activate [a-f0-9]{64}', body)))
            if (not regional_identifier(command.id, 'instanceagentcommand', self.config.region)
                    or command.display_name != name or command.compartment_id != self.config.compartment_ocid
                    or command.target.instance_id != self.instance_id
                    or source.source_type != 'TEXT' or output.output_type != 'TEXT' or not valid_body
                    or command.execution_time_out_in_seconds != (60 if operation == 'status' else ACTIVATION_TIMEOUT)):
                raise ValueError()
            return command
        except (ValueError, AttributeError, TypeError):
            raise DeploymentError('Host command identity or original intent does not match.') from None

    def _commands(self):
        result = {}
        for summary in self.deadline.pages(self.client.list_instance_agent_commands,
                                          compartment_id=self.config.compartment_ocid):
            name = summary.display_name
            if not isinstance(name, str) or not name.startswith(self.prefix):
                continue
            if not re.fullmatch(re.escape(self.prefix) + r'(?:activate|status)-[a-f0-9]{32}', name):
                raise DeploymentError('Unknown deployment command marker; inspect before retrying.')
            if name in result:
                raise DeploymentError('Found duplicate deployment command markers.')
            command = self.deadline.call(self.client.get_instance_agent_command, summary.instance_agent_command_id).data
            if command.id != summary.instance_agent_command_id:
                raise DeploymentError('Host command identity changed.')
            result[name] = self._verify(command, name)
        return result

    def _wait(self, command, *, success):
        def request():
            try:
                return self.client.get_instance_agent_command_execution(command.id, self.instance_id)
            except ServiceError as error:
                if error.status == 404:
                    return None  # Delivery may not have an execution yet; bounded read-only wait.
                raise
        while True:
            response = self.deadline.call(request)
            if response is None:
                self.deadline.pause()
                continue
            execution = response.data
            if (execution.instance_agent_command_id != command.id or execution.instance_id != self.instance_id):
                raise DeploymentError('Host execution identity does not match.')
            state = execution.lifecycle_state
            if state in {'ACCEPTED', 'IN_PROGRESS'}:
                self.deadline.pause()
                continue
            content = execution.content
            if (state not in {'SUCCEEDED', 'FAILED'} or content is None
                    or type(content.exit_code) is not int):
                raise DeploymentError('Host process completion is uncertain; inspect or cleanly redeploy.')
            if not success:
                return None
            if state != 'SUCCEEDED' or content.exit_code != 0 or content.output_type != 'TEXT':
                raise HostCommandFailed('Host command failed; inspect bootstrap or release readiness.')
            return self._status(content.text)

    def _status(self, text):
        try:
            if not isinstance(text, str):
                raise ValueError()
            value = bounded_json(text.encode('utf-8'), 1024)
            if value == {'version': 1, 'status': 'bootstrapping'} and type(value['version']) is int:
                return value
            if (not isinstance(value, dict) or set(value) != {
                    'version', 'status', 'host_digest', 'current', 'previous', 'candidate', 'release'}
                    or type(value['version']) is not int or value['version'] != 1 or value['status'] != 'ready'
                    or value['host_digest'] != self.helper_digest
                    or any(v is not None and not digest_value(v) for v in
                           (value['current'], value['previous'], value['candidate']))
                    or (value['current'] is None) != (value['release'] is None)
                    or value['release'] is not None and not re.fullmatch(r'[a-f0-9]{40}', value['release'])):
                raise ValueError()
            return value
        except (ValueError, TypeError, KeyError, RecursionError):
            raise DeploymentError('Host status or installed helper compatibility could not be verified.') from None

    def settle(self, *, commands=None, exclude=None):
        """Only a concrete process exit proves an older mutation can no longer run."""
        for name, command in (self._commands() if commands is None else commands).items():
            if name != exclude and name.startswith(self.prefix + 'activate-'):
                self._wait(command, success=False)

    def rollback_target(self, identity, *, attempt, previous):
        name = self._name('activate', identity)
        command = self._commands().get(name)
        if command is not None:
            return command.content.source.text.removeprefix(_ENTRYPOINT + 'activate ')
        if attempt != 1:
            raise DeploymentError('Original rollback intent is unavailable; do not resolve a different previous release.')
        if not digest_value(previous):
            raise DeploymentError('No previous compatible release is available.')
        return previous

    def _run(self, operation, identity, digest=None):
        if operation == 'activate' and not digest_value(digest):
            raise DeploymentError('Invalid release activation target.')
        name = self._name(operation, identity)
        body = _ENTRYPOINT + operation + (' ' + digest if digest is not None else '')
        commands = self._commands()
        if operation == 'activate':
            self.settle(commands=commands, exclude=name)
        command = commands.get(name)
        if command is None:
            try:
                result = self.deadline.call(self.client.create_instance_agent_command,
                    models.CreateInstanceAgentCommandDetails(
                        compartment_id=self.config.compartment_ocid, display_name=name,
                        execution_time_out_in_seconds=60 if operation == 'status' else ACTIVATION_TIMEOUT,
                        target=models.InstanceAgentCommandTarget(instance_id=self.instance_id),
                        content=models.InstanceAgentCommandContent(
                            source=models.InstanceAgentCommandSourceViaTextDetails(text=body),
                            output=models.InstanceAgentCommandOutputViaTextDetails())),
                    opc_retry_token=retry_token(name))
            except DeploymentError:
                # Recover the submitted intent; never blindly submit a second mutating command.
                while command is None:
                    command = self._commands().get(name)
                    if command is None:
                        self.deadline.pause()
            else:
                command = self.deadline.call(self.client.get_instance_agent_command, result.data.id).data
                if command.id != result.data.id:
                    raise DeploymentError('Host command identity changed.')
                self._verify(command, name)
        if command.content.source.text != body:
            raise DeploymentError('Original host command intent differs; refusing replay.')
        return self._wait(command, success=True)

    def status(self, identity):
        return self._run('status', identity)

    def activate(self, digest, identity):
        return self._run('activate', identity, digest)
