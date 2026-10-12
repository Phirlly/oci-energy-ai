"""Conditional immutable object writes with bounded checksum readback."""

import base64
import hashlib

from oci.exceptions import ServiceError

from deployment.configuration import DeploymentError


class ImmutableObjects:
    def __init__(self, client, namespace, bucket, deadline):
        self.client, self.namespace, self.bucket = client, namespace, bucket
        self.deadline = deadline

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

    def _put(self, name, stream, size, checksum):
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
