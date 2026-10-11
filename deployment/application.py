"""Deploy, verify, roll back or remove the OCI demo from GitHub's demo environment."""

import argparse
import json
import logging
import os
from pathlib import Path
import re
import sys

from deployment.configuration import DeploymentConfiguration, DeploymentError
from deployment.delivery import Delivery
from deployment.oci_identity import DeliveryClients
from deployment.preflight import check_deployment_setup, format_setup_report


def checked_image(directory, release):
    try:
        directory = Path(directory).absolute()
        if (any(part.is_symlink() for part in (directory, *directory.parents))
                or {path.name for path in directory.iterdir()} != {'image.tar', 'image-id.txt'}
                or not isinstance(release, str) or not re.fullmatch(r'[a-f0-9]{40}', release)):
            raise ValueError()
        archive, identity = directory/'image.tar', directory/'image-id.txt'
        if (any(path.is_symlink() or not path.is_file() for path in (archive, identity))
                or not 0 < archive.stat().st_size <= 2**31):
            raise ValueError()
        with identity.open('rb') as stream:
            image_id = stream.read(256).decode('ascii').strip()
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id) or identity.stat().st_size > 256:
            raise ValueError()
        return archive, image_id, release
    except (OSError, ValueError):
        raise DeploymentError('Expected only the checked image.tar and image-id.txt for this commit.') from None


def main(arguments=None, *, environment=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('apply', 'rollback', 'verify', 'destroy'))
    parser.add_argument('--artifact-dir', default='dist/runtime', type=Path)
    parser.add_argument('--confirm', default='', help='For destroy: exact DEPLOYMENT_ID.')
    args = parser.parse_args(arguments)
    environment = os.environ if environment is None else environment
    report = check_deployment_setup(environment, application=args.operation != 'destroy')
    if not report.complete:
        print(format_setup_report(report))
        return 2
    if args.operation == 'destroy' and args.confirm != environment['DEPLOYMENT_ID']:
        print('error: Destroy confirmation must equal DEPLOYMENT_ID.', file=sys.stderr)
        return 2
    disabled = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        image = checked_image(args.artifact_dir, environment.get('GITHUB_SHA')) if args.operation == 'apply' else None
        config = DeploymentConfiguration(environment['DEPLOYMENT_ID'], environment['OCI_REGION'],
                                         environment['OCI_COMPARTMENT_OCID'])
        with DeliveryClients(environment) as clients:
            delivery = Delivery(clients, config, environment, Path(__file__).resolve().parents[1],
                                emit=lambda message: print(message, flush=True))
            if args.operation == 'apply':
                result = delivery.apply(*image)
            elif args.operation == 'destroy':
                result = delivery.destroy(args.confirm)
            else:
                result = getattr(delivery, args.operation)()
        print(json.dumps(result, sort_keys=True))
        if environment.get('GITHUB_STEP_SUMMARY'):
            with open(environment['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
                summary.write('\n## OCI demo operation\n\n```json\n' + json.dumps(result, indent=2, sort_keys=True) + '\n```\n')
        return 0
    except DeploymentError as error:
        print(f'error: {error}', file=sys.stderr)
    except Exception:
        print('error: OCI demo operation failed; inspect the reported resources and jobs. Raw details suppressed.', file=sys.stderr)
    finally:
        logging.disable(disabled)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
