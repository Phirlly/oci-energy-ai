"""Construct the GitHub deployment identity without credential files or profiles."""

from oci.resource_manager import ResourceManagerClient
from oci.retry import NoneRetryStrategy
from oci.signer import Signer

from deployment.configuration import DeploymentError
from deployment.preflight import check_deployment_setup


def resource_manager_client(environment):
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
    return ResourceManagerClient(
        config, signer=signer,
        timeout=(10, 30), retry_strategy=NoneRetryStrategy(),
    )
