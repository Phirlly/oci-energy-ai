import base64
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from oci.exceptions import ServiceError

from deployment.configuration import DeploymentError
from deployment.release_artifacts import ReleaseArtifacts, image_manifest, host_digest
from deployment.resource_jobs import OperationDeadline
from tests.fixtures.host_release import HOST_DIGEST, release
from tests.fixtures.resource_manager import CONFIG, response


class ReleaseArtifactTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.store = ReleaseArtifacts(self.client, 'fixture', 'oci-energy-ai-energy-demo-artifacts',
                                      OperationDeadline(60, lambda: 0, lambda _: None), HOST_DIGEST)
        self.digest, self.payload, self.manifest, self.archive = release()
        self.head = response(None, **{'etag': 'object-guard', 'content-length': str(len(self.payload)),
            'opc-content-sha256': base64.b64encode(hashlib.sha256(self.payload).digest()).decode()})
        self.client.head_object.return_value = self.head
        self.client.get_object.side_effect = lambda *a, **k: response(NS(raw=BytesIO(self.payload), close=Mock()))
        self.client.list_objects.return_value = response(NS(objects=[], next_start_with=None))

    def test_new_upload_uses_server_checksum_and_never_overwrites(self):
        self.client.head_object.side_effect = [ServiceError(404, 'NotFound', {}, 'private'), self.head]
        self.store.put(f'releases/{self.digest}.json', BytesIO(self.payload), len(self.payload), self.digest)
        options = self.client.put_object.call_args.kwargs
        self.assertEqual(options['if_none_match'], '*')
        self.assertEqual(options['content_length'], len(self.payload))
        self.assertEqual(options['opc_checksum_algorithm'], 'SHA256')
        self.assertEqual(options['opc_content_sha256'], self.head.headers['opc-content-sha256'])

    def test_existing_object_is_verified_without_upload_and_collision_is_rejected(self):
        self.store.put(f'releases/{self.digest}.json', BytesIO(self.payload), len(self.payload), self.digest)
        self.client.put_object.assert_not_called()
        self.head.headers['opc-content-sha256'] = base64.b64encode(b'x' * 32).decode()
        with self.assertRaisesRegex(DeploymentError, 'checksum'):
            self.store.put(f'releases/{self.digest}.json', BytesIO(self.payload), len(self.payload), self.digest)

    def test_missing_service_checksum_uses_bounded_etag_guarded_stream(self):
        del self.head.headers['opc-content-sha256']
        self.store.put(f'releases/{self.digest}.json', BytesIO(self.payload), len(self.payload), self.digest)
        self.assertEqual(self.client.get_object.call_args.kwargs['if_match'], 'object-guard')
        self.payload += b'extra'
        with self.assertRaises(DeploymentError):
            self.store.get_manifest(self.digest)

    def test_ambiguous_put_reconciles_verified_object_without_repeating_write(self):
        self.client.head_object.side_effect = [ServiceError(404, 'NotFound', {}, ''), self.head]
        self.client.put_object.side_effect = ServiceError(500, 'Internal', {}, 'private')
        self.store.put(f'releases/{self.digest}.json', BytesIO(self.payload), len(self.payload), self.digest)
        self.client.put_object.assert_called_once()

    def test_retention_preserves_current_previous_images_and_deletes_only_guarded_obsolete(self):
        obsolete = 'images/' + 'c' * 64 + '.tar'
        names = [f'releases/{self.digest}.json', f'images/{self.manifest["image_sha256"]}.tar', obsolete]
        self.client.list_objects.return_value = response(NS(
            objects=[NS(name=name, etag='guard') for name in names], next_start_with=None))
        self.store.prune({self.digest})
        self.client.delete_object.assert_called_once_with('fixture', self.store.bucket, obsolete, if_match='guard')

    def test_unknown_object_blocks_all_deletion_and_pagination_is_followed(self):
        self.client.list_objects.side_effect = [response(NS(objects=[NS(name='images/' + 'c'*64 + '.tar', etag='g')],
                                                           next_start_with='next')),
                                                response(NS(objects=[NS(name='customer.pdf', etag='g')], next_start_with=None))]
        with self.assertRaisesRegex(DeploymentError, 'unknown'):
            self.store.prune(set())
        self.client.delete_object.assert_not_called()
        self.assertEqual(self.client.list_objects.call_args.kwargs['start'], 'next')

    def test_manifest_uses_actual_archive_bytes_and_rejects_symlink_or_invalid_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'image.tar'
            path.write_bytes(self.archive)
            manifest = image_manifest(path, self.manifest['image_id'], self.manifest['release'],
                                      self.manifest['runtime'], HOST_DIGEST)
            self.assertEqual(manifest, self.manifest)
            link = path.parent / 'link.tar'
            link.symlink_to(path)
            with self.assertRaises(DeploymentError):
                image_manifest(link, self.manifest['image_id'], self.manifest['release'], self.manifest['runtime'], HOST_DIGEST)
            with self.assertRaises(DeploymentError):
                image_manifest(path, self.manifest['image_id'], self.manifest['release'], {}, HOST_DIGEST)

    def test_helper_digest_matches_ordered_terraform_asset_formula(self):
        root = Path(__file__).resolve().parents[3]
        names = ['__init__.py', 'activation.py', 'artifacts.py', 'bootstrap.sh', 'contracts.py',
                 'control.py', 'entrypoint.py', 'oci-energy-ai.service', 'process.py', 'service.py',
                 'service_entry.py', 'state.py']
        expected = hashlib.sha256(''.join(hashlib.sha256((root/'infra/terraform/host'/name).read_bytes()).hexdigest()
                                          for name in names).encode()).hexdigest()
        self.assertEqual(host_digest(root), expected)
