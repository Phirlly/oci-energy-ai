import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
from zipfile import ZipFile

from oci.exceptions import ServiceError

from deployment.configuration import DeploymentError
from deployment.console_publication import PublicArtifacts, publish_assets
from deployment.resource_jobs import OperationDeadline
from tests.fixtures.resource_manager import response


ROOT = Path(__file__).resolve().parents[3]


class PublicArtifactTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.deadline = OperationDeadline(60, lambda: 0, lambda _: None)
        self.store = PublicArtifacts(self.client, 'fixture', 'public-builds', self.deadline)
        self.payload = b'checked-public-bytes'
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.head = response(None, **{'content-length': str(len(self.payload)), 'etag': 'guard',
            'opc-content-sha256': base64.b64encode(bytes.fromhex(self.digest)).decode()})
        self.client.head_object.return_value = self.head

    def test_public_names_exclude_runtime_manifests_bills_and_mismatched_hashes(self):
        for name in [f'releases/{self.digest}.json', 'bill.pdf', f'templates/{"a"*64}.zip']:
            with self.subTest(name=name), self.assertRaises(DeploymentError):
                self.store.put(name, BytesIO(self.payload), len(self.payload), self.digest)
        self.client.head_object.assert_not_called()
        self.assertFalse(hasattr(self.store, 'prune'))
        self.assertFalse(hasattr(self.store, 'publish'))

    def test_exact_collision_readback_and_ambiguous_upload_never_replay(self):
        name = f'templates/{self.digest}.zip'
        self.client.head_object.side_effect = [ServiceError(404, 'NotFound', {}, ''), self.head]
        self.client.put_object.side_effect = ServiceError(500, 'Internal', {}, 'private-marker')
        self.store.put(name, BytesIO(self.payload), len(self.payload), self.digest)
        self.client.put_object.assert_called_once()
        self.assertEqual(self.client.put_object.call_args.kwargs['if_none_match'], '*')
        self.client.head_object.side_effect = None
        self.store.put(name, BytesIO(self.payload), len(self.payload), self.digest)
        self.client.put_object.assert_called_once()
        self.head.headers['opc-content-sha256'] = 'collision'
        with self.assertRaisesRegex(DeploymentError, 'collision'):
            self.store.put(name, BytesIO(self.payload), len(self.payload), self.digest)

    def test_missing_service_checksum_stream_is_bounded_guarded_and_closed(self):
        del self.head.headers['opc-content-sha256']
        stream = NS(raw=BytesIO(self.payload), close=Mock())
        self.client.get_object.return_value = response(stream)
        self.store.put(f'images/{self.digest}.tar', BytesIO(self.payload), len(self.payload), self.digest)
        self.assertEqual(self.client.get_object.call_args.kwargs, {'if_match': 'guard'})
        stream.close.assert_called_once()

    def test_upload_stops_before_another_read_after_deadline_without_closing_source(self):
        now, source = [0], BytesIO(self.payload)
        self.store.deadline = OperationDeadline(60, lambda: now[0], lambda _: None)
        self.client.head_object.side_effect = ServiceError(404, 'NotFound', {}, '')
        def consume(*args, **kwargs):
            body = args[3]
            self.assertEqual(body.read(1), self.payload[:1])
            now[0] = 60
            body.read(1)
        self.client.put_object.side_effect = consume
        with self.assertRaisesRegex(DeploymentError, 'deadline'):
            self.store.put(f'images/{self.digest}.tar', source, len(self.payload), self.digest)
        self.assertEqual(source.tell(), 1)
        self.assertFalse(source.closed)
        self.client.put_object.assert_called_once()

    def test_expiry_during_read_does_not_supply_late_bytes_to_transport(self):
        now, supplied = [0], []
        class SlowSource(BytesIO):
            def read(self, size=-1):
                result = super().read(size)
                now[0] = 60
                return result
        source = SlowSource(self.payload)
        self.store.deadline = OperationDeadline(60, lambda: now[0], lambda _: None)
        self.client.head_object.side_effect = ServiceError(404, 'NotFound', {}, '')
        self.client.put_object.side_effect = lambda *args, **kwargs: supplied.append(args[3].read(1))
        with self.assertRaisesRegex(DeploymentError, 'deadline'):
            self.store.put(f'images/{self.digest}.tar', source, len(self.payload), self.digest)
        self.assertEqual(supplied, [])
        self.assertFalse(source.closed)

    def test_progress_is_bounded_byte_counts_and_success_requires_checksum(self):
        payload = b'x' * (33 * 1024 * 1024)
        digest, messages = hashlib.sha256(payload).hexdigest(), []
        store = PublicArtifacts(self.client, 'fixture', 'public-builds', self.deadline, emit=messages.append)
        head = response(None, **{'content-length': str(len(payload)), 'etag': 'guard',
                                'opc-content-sha256': 'wrong-checksum'})
        self.client.head_object.side_effect = [ServiceError(404, 'NotFound', {}, ''), head]
        def consume(*args, **kwargs):
            while args[3].read(1024 * 1024):
                pass
        self.client.put_object.side_effect = consume
        with self.assertRaisesRegex(DeploymentError, 'collision'):
            store.put(f'images/{digest}.tar', BytesIO(payload), len(payload), digest)
        self.assertEqual(messages, [
            f'Artifact bytes supplied to transport: {32 * 1024 * 1024}/{len(payload)}.',
            f'Artifact bytes supplied to transport: {len(payload)}/{len(payload)}.',
        ])


class ConsolePublicationTests(unittest.TestCase):
    def test_image_descriptor_and_generated_package_match_only_checked_public_inputs(self):
        objects = {}
        storage = Mock()
        def head(namespace, bucket, name):
            if name not in objects:
                raise ServiceError(404, 'NotFound', {}, '')
            payload = objects[name]
            return response(None, **{'content-length': str(len(payload)), 'etag': 'guard',
                'opc-content-sha256': base64.b64encode(hashlib.sha256(payload).digest()).decode()})
        def put(namespace, bucket, name, stream, **kwargs):
            objects[name] = stream.read()
        storage.head_object.side_effect, storage.put_object.side_effect = head, put
        deadline = OperationDeadline(60, lambda: 0, lambda _: None)
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary).resolve()/'image.tar'
            image.write_bytes(b'public CI archive')
            args = (ROOT, image, 'sha256:'+'b'*64, 'a'*40,
                    {'artifact_bucket_name': 'public-builds', 'object_storage_namespace': 'fixture'},
                    'us-ashburn-1', storage, deadline)
            messages = []
            first = publish_assets(*args, emit=messages.append)
            self.assertEqual([message for message in messages if not message.startswith('Artifact bytes')], [
                'Preparing checked public package.', 'Verifying checked image publication.',
                'Verifying Console template publication.',
            ])
            self.assertEqual(first, publish_assets(*args))
            self.assertEqual(storage.put_object.call_count, 2)
            self.assertEqual(len(objects), 2)
            template = next(value for name, value in objects.items() if name.startswith('templates/'))
            with ZipFile(BytesIO(template)) as archive:
                config = json.loads(archive.read('console.auto.tfvars.json'))
                self.assertTrue(config['console_install'])
                descriptor = config['console_release']
                self.assertEqual(descriptor['image_sha256'], hashlib.sha256(image.read_bytes()).hexdigest())
                self.assertEqual(descriptor['image_bytes'], image.stat().st_size)
                self.assertEqual(descriptor['release'], 'a'*40)
                self.assertNotIn('runtime', descriptor)
            self.assertEqual(first['template_sha256'], hashlib.sha256(template).hexdigest())
            self.assertTrue(first['source_url'].startswith('https://objectstorage.us-ashburn-1.oraclecloud.com/'))
