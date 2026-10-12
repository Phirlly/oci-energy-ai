"""Real pinned request preparation and chunk consumption, without network access."""

import base64
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from oci._vendor.requests import Response
from oci.exceptions import ServiceError
from urllib3.util.request import body_to_chunks

from deployment.configuration import DeploymentError
from deployment.oci_identity import DistributionClients
from deployment.release_artifacts import ReleaseArtifacts
from deployment.resource_jobs import OperationDeadline
from tests.fixtures.deployment_environment import configured_environment
from tests.fixtures.host_release import HOST_DIGEST
from tests.fixtures.resource_manager import response


class ArtifactUploadSdkContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.environment = configured_environment() | {'OCI_PRIVATE_KEY': key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()}

    def setUp(self):
        self.clients = self.enterContext(DistributionClients(self.environment))
        self.now = 0
        self.deadline = OperationDeadline(60, lambda: self.now, lambda _: None)
        self.store = ReleaseArtifacts(self.clients.storage, 'fixture', 'fixture-bucket', self.deadline, HOST_DIGEST)
        self.payload = b'public build bytes' * 4096
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.checksum = base64.b64encode(bytes.fromhex(self.digest)).decode()

    def publish(self, stream, consume):
        prepared, observations = [], []
        head = response(None, **{'content-length': str(len(self.payload)), 'etag': 'guard',
                                'opc-content-sha256': self.checksum})
        def send(request, **kwargs):
            prepared.append(request)
            observations.append(consume(request.body))
            result = Response()
            result.status_code, result._content = 200, b''
            result.headers, result.request, result.url = {}, request, request.url
            return result
        with (patch.object(self.clients.storage, 'head_object', side_effect=[
                ServiceError(404, 'NotFound', {}, ''), head]),
              patch.object(self.clients.storage.base_client.session, 'send', side_effect=send) as network):
            try:
                self.store.put(f'images/{self.digest}.tar', stream, len(self.payload), self.digest)
            finally:
                network.assert_called_once()
                self.assertEqual(len(prepared), 1)
                request = prepared[0]
                self.assertIsNot(request.body, stream)
                self.assertEqual(request.method, 'PUT')
                self.assertEqual(request.headers['Content-Length'], str(len(self.payload)))
                self.assertEqual(request.headers['if-none-match'], '*')
                self.assertEqual(request.headers['opc-content-sha256'], self.checksum)
                self.assertEqual(request.headers['opc-checksum-algorithm'], 'SHA256')
        return observations

    def test_real_file_and_bytesio_preserve_length_position_body_and_source_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'image.tar'
            path.write_bytes(self.payload)
            for source in (BytesIO(self.payload), path.open('rb')):
                with source, self.subTest(source=type(source).__name__):
                    def consume(body):
                        position = body.tell()
                        file = (body.name, body.mode, body.fileno()) if hasattr(source, 'name') else None
                        body.seek(0)
                        payload = b''.join(body_to_chunks(body, method='PUT', blocksize=16384).chunks)
                        return position, file, payload
                    observed = self.publish(source, consume)
                    expected_file = (source.name, source.mode, source.fileno()) if hasattr(source, 'name') else None
                    self.assertEqual(len(observed), 1)
                    position, file, received = observed[0]
                    self.assertEqual((position, file), (0, expected_file))
                    self.assertTrue(received == self.payload, 'Prepared upload bytes changed.')
                    self.assertFalse(source.closed)
                    self.assertEqual(source.tell(), len(self.payload))

    def test_transport_chunk_loop_stops_before_consuming_more_after_expiry(self):
        source, supplied = BytesIO(self.payload), []
        def consume(body):
            chunks = body_to_chunks(body, method='PUT', blocksize=16384).chunks
            supplied.append(next(chunks))
            self.now = 60
            list(chunks)
        with self.assertRaisesRegex(DeploymentError, 'deadline'):
            self.publish(source, consume)
        self.assertEqual(supplied, [self.payload[:16384]])
        self.assertEqual(source.tell(), 16384)
        self.assertFalse(source.closed)
