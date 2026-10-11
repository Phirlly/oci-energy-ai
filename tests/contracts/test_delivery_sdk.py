"""Real pinned OCI request construction, intercepted before any network I/O."""

import base64
import hashlib
from io import BytesIO
import json
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from oci.compute_instance_agent import models as agent
from oci.exceptions import ServiceError
from oci.secrets import models as bundles
from oci.vault import models as vault

from deployment.host_commands import HostCommands
from deployment.oci_identity import DeliveryClients
from deployment.release_artifacts import ReleaseArtifacts
from deployment.resource_jobs import OperationDeadline
from deployment.runtime_secrets import RuntimeSecrets
from tests.fixtures.deployment_environment import configured_environment
from tests.fixtures.host_release import HOST_DIGEST, release
from tests.fixtures.resource_manager import CONFIG, REPOSITORY, response


INSTANCE = 'ocid1.instance.oc1.iad.'+'i'*32
COMMAND = 'ocid1.instanceagentcommand.oc1.iad.'+'c'*32
VAULT, KEY, SECRET = ['ocid1.'+kind+'.oc1.iad.'+'s'*32 for kind in ('vault', 'key', 'vaultsecret')]


class DeliverySdkContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.environment = configured_environment() | {'OCI_PRIVATE_KEY': key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()}

    def setUp(self):
        self.clients = self.enterContext(DeliveryClients(self.environment))
        self.deadline = OperationDeadline(30, lambda: 0, lambda _: None)

    def test_vault_create_and_current_read_use_actual_request_models_headers_and_query(self):
        store = RuntimeSecrets(self.clients.vaults, self.clients.secrets, CONFIG, REPOSITORY, VAULT, KEY, self.deadline)
        secret = vault.Secret(id=SECRET, compartment_id=CONFIG.compartment_ocid, vault_id=VAULT, key_id=KEY,
            secret_name='oci-energy-ai-energy-demo-demo-password', lifecycle_state='ACTIVE', freeform_tags=store.tags)
        bundle = bundles.SecretBundle(secret_id=SECRET, stages=['CURRENT'], secret_bundle_content=
            bundles.Base64SecretBundleContentDetails(content=base64.b64encode(b'admin').decode()))
        def respond(**request):
            return response([]) if request['operation_name'] == 'list_secrets' else response(secret, etag='guard')
        with (patch.object(self.clients.vaults.base_client, 'call_api', side_effect=respond) as write,
              patch.object(self.clients.secrets.base_client, 'call_api', return_value=response(bundle)) as read):
            self.assertEqual(store.synchronize({'demo_password': 'admin'}), {'demo_password': SECRET})
        requests = {call.kwargs['operation_name']: call.kwargs for call in write.call_args_list}
        self.assertEqual(requests['list_secrets']['query_params'], {'compartmentId': CONFIG.compartment_ocid, 'vaultId': VAULT})
        self.assertIn('opc-retry-token', requests['create_secret']['header_params'])
        self.assertEqual(requests['create_secret']['body'].secret_content.stage, 'CURRENT')
        self.assertEqual(read.call_args.kwargs['query_params'], {'stage': 'CURRENT'})

    def test_agent_create_and_execution_use_actual_target_and_nested_exit_content(self):
        commands = HostCommands(self.clients.agent, CONFIG, REPOSITORY, INSTANCE, HOST_DIGEST, self.deadline)
        current = None
        metadata_reads = 0
        state = dict(version=1, status='ready', host_digest=HOST_DIGEST, current=None, previous=None, candidate=None, release=None)
        def respond(**request):
            nonlocal current, metadata_reads
            operation = request['operation_name']
            if operation == 'list_instance_agent_commands':
                return response([])
            if operation == 'create_instance_agent_command':
                details = request['body']
                current = agent.InstanceAgentCommand(id=COMMAND, compartment_id=details.compartment_id,
                    display_name=details.display_name, target=details.target, content=details.content,
                    execution_time_out_in_seconds=details.execution_time_out_in_seconds)
                return response(current)
            if operation == 'get_instance_agent_command':
                metadata_reads += 1
                if metadata_reads == 1:
                    raise ServiceError(429, 'TooManyRequests', {}, 'private-service-detail')
                return response(current)
            return response(agent.InstanceAgentCommandExecution(instance_agent_command_id=COMMAND,
                instance_id=INSTANCE, lifecycle_state='SUCCEEDED', content=
                agent.InstanceAgentCommandExecutionOutputViaTextDetails(exit_code=0, text=json.dumps(state))))
        with patch.object(self.clients.agent.base_client, 'call_api', side_effect=respond) as transport:
            self.assertEqual(commands.status('fresh-observation'), state)
        requests = {call.kwargs['operation_name']: call.kwargs for call in transport.call_args_list}
        operations = [call.kwargs['operation_name'] for call in transport.call_args_list]
        self.assertEqual(operations.count('create_instance_agent_command'), 1)
        self.assertEqual(operations.count('get_instance_agent_command'), 2)
        for call in transport.call_args_list:
            if call.kwargs['operation_name'] == 'get_instance_agent_command':
                self.assertEqual(call.kwargs['path_params'], {'instanceAgentCommandId': COMMAND})
        self.assertEqual(requests['create_instance_agent_command']['body'].target.instance_id, INSTANCE)
        self.assertEqual(requests['get_instance_agent_command_execution']['path_params'],
                         {'instanceAgentCommandId': COMMAND})
        self.assertEqual(requests['get_instance_agent_command_execution']['query_params'], {'instanceId': INSTANCE})

    def test_object_put_translates_conditional_sha256_contract_to_service_headers(self):
        digest, payload, _, _ = release()
        store = ReleaseArtifacts(self.clients.storage, 'fixture', 'fixture-bucket', self.deadline, HOST_DIGEST)
        heads = 0
        checksum = base64.b64encode(hashlib.sha256(payload).digest()).decode()
        def respond(**request):
            nonlocal heads
            if request['method'] == 'HEAD':
                heads += 1
                if heads == 1:
                    raise ServiceError(404, 'NotFound', {}, '')
                return response(None, **{'content-length': str(len(payload)), 'etag': 'guard', 'opc-content-sha256': checksum})
            return response(None)
        with patch.object(self.clients.storage.base_client, 'call_api', side_effect=respond) as transport:
            store.put('releases/'+digest+'.json', BytesIO(payload), len(payload), digest)
        request = next(call.kwargs for call in transport.call_args_list if call.kwargs['method'] == 'PUT')
        self.assertEqual(request['header_params']['if-none-match'], '*')
        self.assertEqual(request['header_params']['opc-content-sha256'], checksum)
        self.assertEqual(request['header_params']['opc-checksum-algorithm'], 'SHA256')
        self.assertEqual(request['header_params']['Content-Length'], len(payload))
