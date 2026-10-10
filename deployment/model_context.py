"""Read and verify the owned OCI project before the isolated model check."""

from contextlib import ExitStack

from oci.generative_ai import GenerativeAiClient
from oci.resource_manager import ResourceManagerClient
from oci.retry import NoneRetryStrategy

from deployment.configuration import DeploymentConfiguration, DeploymentError
from deployment.oci_identity import deployment_identity
from deployment.resource_manager import ResourceManager


def load_oci_model_context(environment):
    identity, signer = deployment_identity(environment)
    config = DeploymentConfiguration(environment["DEPLOYMENT_ID"], environment["OCI_REGION"],
                                     environment["OCI_COMPARTMENT_OCID"])
    options = dict(signer=signer, timeout=(10, 30), retry_strategy=NoneRetryStrategy())
    with ExitStack() as cleanup:
        resource = ResourceManagerClient(identity, **options)
        cleanup.callback(resource.base_client.session.close)
        manager = ResourceManager(
            resource, config, environment.get("GITHUB_REPOSITORY", ""),
            f"{environment.get('GITHUB_RUN_ID', '')}-{environment.get('GITHUB_RUN_ATTEMPT', '')}", timeout=60,
        )
        outputs = manager.foundation_outputs()
        project_id = outputs["generative_ai_project_ocid"]
        genai = GenerativeAiClient(identity, **options)
        cleanup.callback(genai.base_client.session.close)
        project = manager.deadline.call(genai.get_generative_ai_project, project_id).data
        tags = {"application": "oci-energy-ai", "deployment_id": config.deployment_id,
                "managed_by": "terraform"}
        if (project.id != project_id or project.lifecycle_state != "ACTIVE"
                or project.compartment_id != config.compartment_ocid
                or project.display_name != manager.name
                or any((project.freeform_tags or {}).get(key) != value for key, value in tags.items())):
            raise DeploymentError("OCI project is inactive or does not match the owned foundation.")
    return dict(oci_region=config.region, oci_project=project_id, oci_signer=signer)
