"""Construct the GitHub deployment identity without credential files or profiles."""

from contextlib import ExitStack

from oci.apigateway import GatewayClient
from oci.compute_instance_agent import ComputeInstanceAgentClient
from oci.core import ComputeClient, VirtualNetworkClient
from oci.generative_ai import GenerativeAiClient
from oci.identity import IdentityClient
from oci.key_management import KmsManagementClient, KmsVaultClient
from oci.object_storage import ObjectStorageClient
from oci.resource_manager import ResourceManagerClient
from oci.retry import NoneRetryStrategy
from oci.secrets import SecretsClient
from oci.signer import Signer
from oci.vault import VaultsClient

from deployment.configuration import DeploymentError
from deployment.preflight import check_deployment_setup


def deployment_identity(environment):
    if not check_deployment_setup(environment).complete:
        raise DeploymentError("Deployment configuration is incomplete or invalid; run Check deployment setup.")
    try:
        signer = Signer(
            tenancy=environment["OCI_TENANCY_OCID"], user=environment["OCI_USER_OCID"],
            fingerprint=environment["OCI_FINGERPRINT"], private_key_file_location=None,
            private_key_content=environment["OCI_PRIVATE_KEY"],
            pass_phrase=environment.get("OCI_PRIVATE_KEY_PASSPHRASE") or None,
        )
    except Exception:
        raise DeploymentError("OCI signing key could not be loaded; check key format and passphrase.") from None
    config = {"region": environment["OCI_REGION"], "tenancy": environment["OCI_TENANCY_OCID"],
              "user": environment["OCI_USER_OCID"], "fingerprint": environment["OCI_FINGERPRINT"],
              "key_content": environment["OCI_PRIVATE_KEY"]}
    return config, signer


def resource_manager_client(environment):
    config, signer = deployment_identity(environment)
    return ResourceManagerClient(
        config, signer=signer,
        timeout=(10, 30), retry_strategy=NoneRetryStrategy(),
    )


class DeliveryClients:
    """One operation owns and closes all deployment SDK transport sessions."""

    SERVICES = dict(resource=ResourceManagerClient, identity=IdentityClient, compute=ComputeClient,
                    network=VirtualNetworkClient, kms=KmsVaultClient, vaults=VaultsClient,
                    secrets=SecretsClient, storage=ObjectStorageClient, agent=ComputeInstanceAgentClient,
                    genai=GenerativeAiClient, gateway=GatewayClient)

    def __init__(self, environment):
        self.config, signer = deployment_identity(environment)
        self.options = dict(signer=signer, timeout=(10, 30), retry_strategy=NoneRetryStrategy())
        self.cleanup, self.key_clients = ExitStack(), {}

    def _client(self, factory, **options):
        client = factory(self.config, **self.options, **options)
        self.cleanup.callback(client.base_client.session.close)
        return client

    def __enter__(self):
        try:
            for name, factory in self.SERVICES.items():
                setattr(self, name, self._client(factory))
            return self
        except Exception:
            self.cleanup.close()
            raise

    def keys(self, endpoint):
        if endpoint not in self.key_clients:
            self.key_clients[endpoint] = self._client(KmsManagementClient, service_endpoint=endpoint)
        return self.key_clients[endpoint]

    def __exit__(self, *args):
        return self.cleanup.__exit__(*args)
