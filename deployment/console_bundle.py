"""Package a checked public build for fresh Resource Manager Console installs."""

import argparse
import json
from pathlib import Path
import re

from deployment.release_artifacts import host_digest
from deployment.terraform_bundle import _MEMBERS, _read_member, _write_archive
from infra.terraform.host.contracts import bounded_json, digest_value


def validate_release(value, helper_digest):
    try:
        if not isinstance(value, dict) or set(value) != {
                'artifact_base', 'release', 'host_digest', 'image_id', 'image_sha256', 'image_bytes'}:
            raise ValueError()
        if (not isinstance(value['artifact_base'], str) or not re.fullmatch(
                r'https://objectstorage\.[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?\.oraclecloud\.com'
                r'/n/[A-Za-z0-9_-]{1,255}/b/[A-Za-z0-9_-]{1,255}/o/', value['artifact_base'])
                or value['host_digest'] != helper_digest or not digest_value(helper_digest)
                or not isinstance(value['release'], str) or not re.fullmatch(r'[a-f0-9]{40}', value['release'])
                or not isinstance(value['image_id'], str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', value['image_id'])
                or not digest_value(value['image_sha256']) or type(value['image_bytes']) is not int
                or not 0 < value['image_bytes'] <= 2**31):
            raise ValueError()
    except (TypeError, ValueError, KeyError):
        raise ValueError('Console release must identify one checked public image and matching host.') from None


def build_console_bundle(repository_root, output, release):
    root = Path(repository_root).absolute()
    validate_release(release, host_digest(root))
    source = root / 'infra/terraform'
    members = [(name, _read_member(source / name)) for name in _MEMBERS]
    members.append(('schema.yaml', _read_member(source / 'schema.yaml')))
    content = json.dumps({'console_install': True, 'console_release': release},
                         sort_keys=True, separators=(',', ':')).encode()
    members.append(('console.auto.tfvars.json', content))
    return _write_archive(members, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--descriptor', required=True, type=Path,
                        help='Nonsecret checked public release JSON; at most 16 KiB.')
    parser.add_argument('--output', required=True, type=Path, help='New Console ZIP path.')
    args = parser.parse_args()
    try:
        with args.descriptor.open('rb') as stream:
            release = bounded_json(stream.read(16385), 16384)
        digest = build_console_bundle(Path(__file__).resolve().parents[1], args.output, release)
    except (OSError, ValueError):
        parser.exit(2, 'error: Console package inputs are invalid or output already exists.\n')
    print(f'SHA256 {digest}')


if __name__ == '__main__':
    main()
