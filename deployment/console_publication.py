"""Publish only a checked public image and an allowlisted native Console package."""

import hashlib
from pathlib import Path
import re
import tempfile
from urllib.parse import quote

from deployment.configuration import DeploymentError
from deployment.console_bundle import build_console_bundle, validate_release
from deployment.immutable_objects import ImmutableObjects
from deployment.release_artifacts import host_digest


class PublicArtifacts(ImmutableObjects):
    def put(self, name, stream, size, checksum):
        if (not isinstance(name, str) or not re.fullmatch(
                r'(?:images/[a-f0-9]{64}\.tar|templates/[a-f0-9]{64}\.zip)', name)
                or not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum)
                or type(size) is not int or not 0 < size <= (2**20 if name.startswith('templates/') else 2**31)
                or name.split('/')[1].split('.')[0] != checksum):
            raise DeploymentError('Invalid public build artifact identity.')
        self._put(name, stream, size, checksum)


def publish_assets(root, archive, image_id, release, outputs, region, client, deadline):
    namespace, bucket = outputs['object_storage_namespace'], outputs['artifact_bucket_name']
    base = f'https://objectstorage.{region}.oraclecloud.com/n/{namespace}/b/{bucket}/o/'
    archive = Path(archive)
    with archive.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    helper = host_digest(root)
    descriptor = dict(artifact_base=base, release=release, host_digest=helper, image_id=image_id,
                      image_sha256=checksum, image_bytes=archive.stat().st_size)
    validate_release(descriptor, helper)
    store = PublicArtifacts(client, namespace, bucket, deadline)
    with tempfile.TemporaryDirectory() as directory:
        template = Path(directory)/'console.zip'
        digest = build_console_bundle(root, template, descriptor)
        if template.stat().st_size > 2**20:
            raise DeploymentError('Console template exceeds the public package size limit.')
        with archive.open('rb') as stream:
            store.put(f'images/{checksum}.tar', stream, descriptor['image_bytes'], checksum)
        name = f'templates/{digest}.zip'
        with template.open('rb') as stream:
            store.put(name, stream, template.stat().st_size, digest)
    return dict(release=release, image_sha256=checksum, template_sha256=digest,
                source_url=base + quote(name, safe=''))
