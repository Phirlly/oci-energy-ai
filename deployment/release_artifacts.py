"""Content-addressed checked images/manifests and conservative private-bucket retention."""

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re

from oci.exceptions import ServiceError

from deployment.configuration import DeploymentError
from deployment.terraform_bundle import _MEMBERS, _read_member
from energy_ai.web.hosted_configuration import HostedConfiguration
from infra.terraform.host.contracts import HostError, parse_manifest


def host_digest(root):
    source = Path(root) / 'infra/terraform'
    return hashlib.sha256(''.join(hashlib.sha256(_read_member(source / name)).hexdigest()
                                  for name in _MEMBERS if name.startswith('host/')).encode()).hexdigest()


def manifest_bytes(manifest):
    return json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()


def image_manifest(path, image_id, release, runtime, helper_digest):
    try:
        path = Path(path)
        if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError()
        size = path.stat().st_size
        if not 0 < size <= 2**31:
            raise ValueError()
        with path.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        HostedConfiguration.from_bytes(manifest_bytes(runtime))
        manifest = dict(version=1, host_digest=helper_digest, release=release, image_id=image_id,
                        image_sha256=checksum, image_bytes=size, runtime=runtime)
        payload = manifest_bytes(manifest)
        return parse_manifest(payload, hashlib.sha256(payload).hexdigest(), helper_digest)
    except (OSError, ValueError, HostError):
        raise DeploymentError('Checked image archive or runtime manifest is invalid.') from None


class ReleaseArtifacts:
    def __init__(self, client, namespace, bucket, deadline, helper_digest):
        self.client, self.namespace, self.bucket = client, namespace, bucket
        self.deadline, self.helper_digest = deadline, helper_digest

    def _head(self, name):
        def request():
            try:
                return self.client.head_object(self.namespace, self.bucket, name)
            except ServiceError as error:
                if error.status == 404:
                    return None
                raise
        return self.deadline.call(request)

    def _headers(self, head, limit):
        try:
            size, etag = int(head.headers['content-length']), head.headers['etag']
            if not 0 < size <= limit or not isinstance(etag, str) or not etag:
                raise ValueError()
            return size, etag
        except (ValueError, KeyError, AttributeError, TypeError):
            raise DeploymentError('Artifact size or ETag is invalid.') from None

    def _stream(self, name, size, etag, *, collect=False):
        result = self.deadline.call(self.client.get_object, self.namespace, self.bucket, name, if_match=etag)
        checksum, count, parts = hashlib.sha256(), 0, []
        try:
            while True:
                self.deadline.check()
                block = result.data.raw.read(min(1024 * 1024, size + 1 - count))
                if not block:
                    break
                count += len(block)
                if count > size:
                    raise ValueError()
                checksum.update(block)
                if collect:
                    parts.append(block)
            if count != size:
                raise ValueError()
            return checksum.hexdigest(), b''.join(parts)
        except Exception:
            raise DeploymentError('Artifact stream could not be verified.') from None
        finally:
            result.data.close()

    def _verify(self, name, head, size, checksum):
        actual, etag = self._headers(head, size)
        if actual != size:
            raise DeploymentError('Artifact checksum or size collision; refusing replacement.')
        encoded = head.headers.get('opc-content-sha256')
        if encoded is not None:
            valid = encoded == base64.b64encode(bytes.fromhex(checksum)).decode('ascii')
        else:
            valid = self._stream(name, size, etag)[0] == checksum
        if not valid:
            raise DeploymentError('Artifact checksum collision; refusing replacement.')

    def put(self, name, stream, size, checksum):
        if (not re.fullmatch(r'(?:images/[a-f0-9]{64}\.tar|releases/[a-f0-9]{64}\.json)', name)
                or not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum)
                or type(size) is not int or not 0 < size <= 2**31
                or name.split('/')[1].split('.')[0] != checksum):
            raise DeploymentError('Invalid immutable artifact identity.')
        head = self._head(name)
        if head is None:
            try:
                self.deadline.call(self.client.put_object, self.namespace, self.bucket, name, stream,
                    content_length=size, if_none_match='*', opc_checksum_algorithm='SHA256',
                    opc_content_sha256=base64.b64encode(bytes.fromhex(checksum)).decode('ascii'))
            except DeploymentError:
                # Reconcile uncertain writes and collisions without another PUT.
                pass
            head = self._head(name)
        self._verify(name, head, size, checksum)

    def publish(self, archive, manifest):
        payload = manifest_bytes(manifest)
        digest = hashlib.sha256(payload).hexdigest()
        parse_manifest(payload, digest, self.helper_digest)
        with Path(archive).open('rb') as stream:
            self.put(f'images/{manifest["image_sha256"]}.tar', stream,
                     manifest['image_bytes'], manifest['image_sha256'])
        self.put(f'releases/{digest}.json', BytesIO(payload), len(payload), digest)
        return digest

    def get_manifest(self, digest):
        if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise DeploymentError('Invalid retained release identifier.')
        name = f'releases/{digest}.json'
        size, etag = self._headers(self._head(name), 65536)
        checksum, payload = self._stream(name, size, etag, collect=True)
        try:
            manifest = parse_manifest(payload, digest, self.helper_digest)
            HostedConfiguration.from_bytes(manifest_bytes(manifest['runtime']))
            return manifest
        except (ValueError, HostError):
            raise DeploymentError('Retained release manifest is invalid.') from None

    def inventory(self):
        start, seen, objects = None, set(), {}
        while True:
            result = self.deadline.call(self.client.list_objects, self.namespace, self.bucket,
                fields='name,size,etag', **({'start': start} if start else {})).data
            for item in result.objects:
                if (not re.fullmatch(r'(?:images/[a-f0-9]{64}\.tar|releases/[a-f0-9]{64}\.json)', item.name)
                        or item.name in objects or not isinstance(item.etag, str) or not item.etag):
                    raise DeploymentError('Artifact bucket has unknown or duplicate objects; cleanup refused.')
                objects[item.name] = item.etag
            start = result.next_start_with
            if not start:
                return objects
            if start in seen:
                raise DeploymentError('Artifact pagination repeated; cleanup refused.')
            seen.add(start)

    def prune(self, retained, *, inventory=None):
        keep = set()
        for digest in retained:
            manifest = self.get_manifest(digest)
            keep.update({f'releases/{digest}.json', f'images/{manifest["image_sha256"]}.tar'})
        objects = self.inventory() if inventory is None else inventory
        for name, etag in objects.items():
            if name not in keep:
                self.deadline.call(self.client.delete_object, self.namespace, self.bucket, name, if_match=etag)
