import hashlib
import json
import unittest

from infra.terraform.host.contracts import HostError, parse_manifest
from tests.fixtures.host_release import HOST_DIGEST, release


class ReleaseManifestTests(unittest.TestCase):
    def test_settings_runtime_requires_version_two_and_exact_settings_secret_shape(self):
        _, _, manifest, _ = release()
        manifest['runtime']['version'] = 2
        secret_id = manifest['runtime']['secret_ids'].pop('demo_password')
        manifest['runtime']['secret_ids'] = {'settings': secret_id}
        manifest['runtime']['model_ids'] = {'anthropic': 'public-model-fixture'}
        payload = json.dumps(manifest).encode()
        self.assertEqual(parse_manifest(payload, hashlib.sha256(payload).hexdigest(), HOST_DIGEST), manifest)
        for change in ({'version': 1}, {'secret_ids': {'settings': secret_id, 'openai': secret_id + 'x'}},
                       {'secret_ids': {'demo_password': secret_id}}, {'version': 3}):
            changed = dict(manifest, runtime=manifest['runtime'] | change)
            payload = json.dumps(changed).encode()
            with self.subTest(change=change), self.assertRaises(HostError):
                parse_manifest(payload, hashlib.sha256(payload).hexdigest(), HOST_DIGEST)

    def test_verified_manifest_preserves_nonsecret_runtime_configuration(self):
        digest, payload, manifest, _ = release()
        self.assertEqual(parse_manifest(payload, digest, HOST_DIGEST), manifest)

    def test_hash_helper_and_shape_fail_before_any_runtime_action(self):
        digest, payload, manifest, _ = release()
        for value, expected, helper in ((payload, "b" * 64, HOST_DIGEST),
                                        (payload, digest, "b" * 64),
                                        (b"x" * 65537, digest, HOST_DIGEST)):
            with self.subTest(expected=expected), self.assertRaises(HostError):
                parse_manifest(value, expected, helper)
        for change in ({"version": True}, {"image_bytes": True}, {"image_bytes": 2**31 + 1},
                       {"image_id": "--private-marker"}, {"release": "../bad"},
                       {"password": "private-marker"}, {"runtime": {"password": "private-marker"}}):
            changed = dict(manifest, **change)
            content = json.dumps(changed).encode()
            with self.subTest(change=change), self.assertRaises(HostError) as raised:
                parse_manifest(content, hashlib.sha256(content).hexdigest(), HOST_DIGEST)
            self.assertNotIn("private-marker", str(raised.exception))

    def test_duplicate_json_keys_and_embedded_credential_values_are_rejected(self):
        _, payload, manifest, _ = release()
        duplicate = payload[:-1] + b',"version":1}'
        manifest["runtime"]["secret_ids"]["demo_password"] = "private-marker"
        for content in (duplicate, json.dumps(manifest).encode()):
            with self.assertRaises(HostError):
                parse_manifest(content, hashlib.sha256(content).hexdigest(), HOST_DIGEST)
