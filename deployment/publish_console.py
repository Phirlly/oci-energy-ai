"""Publish this workflow's checked build for native Resource Manager installation."""

import argparse
import json
import logging
import os
from pathlib import Path
import sys

from deployment.application import checked_image
from deployment.configuration import DeploymentError
from deployment.console_publication import publish_assets
from deployment.distribution import DistributionManager, distribution_config
from deployment.oci_identity import DistributionClients
from deployment.preflight import check_deployment_setup


def main(arguments=None, *, environment=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', default='dist/runtime', type=Path)
    args = parser.parse_args(arguments)
    environment = dict(os.environ if environment is None else environment)
    try:
        config = distribution_config(environment.get('GITHUB_REPOSITORY'), environment.get('OCI_REGION'),
                                     environment.get('OCI_COMPARTMENT_OCID'))
        environment['DEPLOYMENT_ID'] = config.deployment_id
        if not check_deployment_setup(environment).complete:
            raise ValueError()
    except (ValueError, DeploymentError):
        print('error: Publication requires valid OCI identity, region, compartment and GitHub repository.', file=sys.stderr)
        return 2
    disabled = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        image = checked_image(args.artifact_dir, environment.get('GITHUB_SHA'))
        repository = environment['GITHUB_REPOSITORY']
        run_id = f"{environment.get('GITHUB_RUN_ID')}-{environment.get('GITHUB_RUN_ATTEMPT')}"
        root = Path(__file__).resolve().parents[1]
        with DistributionClients(environment) as clients:
            manager = DistributionManager(clients.resource, config, repository, run_id,
                                          emit=lambda message: print(message, flush=True), timeout=1800)
            outputs = manager.provision(root, clients.storage)
            result = publish_assets(root, *image, outputs, config.region, clients.storage, manager.deadline)
        content = json.dumps(result, indent=2, sort_keys=True)
        print(content)
        if environment.get('GITHUB_STEP_SUMMARY'):
            with open(environment['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
                summary.write('\n## Checked Console installer candidate\n\n```json\n' + content + '\n```\n'
                              '\nPublic assets are retained independently of demo stacks. '
                              'Fresh Console acceptance is required before advertising this build.\n')
        return 0
    except DeploymentError as error:
        print(f'error: {error}', file=sys.stderr)
    except Exception:
        print('error: Console publication failed. Inspect the reported stack/job; raw details suppressed.', file=sys.stderr)
    finally:
        logging.disable(disabled)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
