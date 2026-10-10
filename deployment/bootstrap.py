"""Apply or destroy the Terraform foundation using the GitHub demo environment."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from deployment.configuration import DeploymentConfiguration, DeploymentError
from deployment.oci_identity import resource_manager_client
from deployment.preflight import check_deployment_setup, format_setup_report
from deployment.resource_manager import ResourceManager
from deployment.terraform_bundle import build_bundle


def main(arguments=None, *, environment=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("apply", "destroy"))
    parser.add_argument("--confirm", default="", help="Required for destroy: exact DEPLOYMENT_ID.")
    args = parser.parse_args(arguments)
    environment = os.environ if environment is None else environment
    report = check_deployment_setup(environment)
    if not report.complete:
        print(format_setup_report(report))
        return 2
    if args.operation == "destroy" and args.confirm != environment["DEPLOYMENT_ID"]:
        print("error: Destroy confirmation must equal DEPLOYMENT_ID.", file=sys.stderr)
        return 2
    try:
        config = DeploymentConfiguration(environment["DEPLOYMENT_ID"], environment["OCI_REGION"],
                                         environment["OCI_COMPARTMENT_OCID"])
        manager = ResourceManager(
            resource_manager_client(environment), config, environment.get("GITHUB_REPOSITORY", ""),
            f"{environment.get('GITHUB_RUN_ID', '')}-{environment.get('GITHUB_RUN_ATTEMPT', '')}",
            emit=lambda message: print(message, flush=True),
        )
        if args.operation == "destroy":
            destroyed = manager.destroy(args.confirm)
            print("Foundation destroy succeeded; empty stack retained." if destroyed else "No owned stack found; nothing changed.")
        else:
            with tempfile.TemporaryDirectory(prefix="oci-energy-ai-") as temporary:
                archive = Path(temporary) / "terraform.zip"
                build_bundle(Path(__file__).resolve().parents[1], archive)
                outputs = manager.apply(archive.read_bytes())
            print("Foundation apply succeeded; application and model integration remain pending.")
            print(json.dumps(outputs, sort_keys=True))
        return 0
    except DeploymentError as error:
        print(f"error: {error}", file=sys.stderr)
    except Exception:
        print("error: Bootstrap failed; inspect reported stack/job IDs before retrying. Raw details suppressed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
