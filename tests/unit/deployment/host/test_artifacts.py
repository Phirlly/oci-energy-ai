import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from infra.terraform.host.artifacts import ArtifactStore, ObjectDownload
from infra.terraform.host.contracts import HostError
from infra.terraform.host.state import HostState
from tests.fixtures.host_release import HOST_DIGEST, release


class VerifiedObjectDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.target = Path(temporary.name) / "download"
        self.calls = []
        self.content = b"public-image"
        def runner(arguments, **kwargs):
            self.calls.append((arguments, kwargs))
            Path(arguments[arguments.index("--file") + 1]).write_bytes(self.content)
        self.download = ObjectDownload({"region": "us-ashburn-1", "namespace": "example",
                                        "bucket": "oci-energy-ai-demo-artifacts"}, runner=runner)

    def test_exact_instance_auth_and_hash_size_without_cli_configuration(self):
        digest = hashlib.sha256(self.content).hexdigest()
        self.download.fetch("images/" + digest + ".tar", self.target, digest, max_bytes=100,
                            expected_size=len(self.content))
        arguments, options = self.calls[0]
        for flag, value in (("--auth", "instance_principal"), ("--region", "us-ashburn-1"),
                            ("--config-file", "/dev/null"), ("--cli-rc-file", "/dev/null"),
                            ("--namespace-name", "example"), ("--bucket-name", "oci-energy-ai-demo-artifacts")):
            self.assertEqual(arguments[arguments.index(flag) + 1], value)
        self.assertIn("--no-multipart", arguments)
        self.assertIn("--no-retry", arguments)
        self.assertLessEqual(options["timeout"], 600)
        self.assertLessEqual(options["file_limit"], 101)

    def test_hash_size_and_limit_mismatch_are_rejected(self):
        digest = hashlib.sha256(self.content).hexdigest()
        for expected, size, limit in (("a" * 64, len(self.content), 100),
                                      (digest, 1, 100), (digest, None, 1)):
            with self.subTest(size=size), self.assertRaises(HostError):
                self.download.fetch("images/" + digest + ".tar", self.target, expected,
                                    max_bytes=limit, expected_size=size)


class ArtifactRetentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.state = HostState(root / "state", root / "run", HOST_DIGEST)
        self.service = Mock()
        self.store = ArtifactStore(self.state, Mock(), self.service)
        self.releases = [release(number) for number in (1, 2, 3)]
        for digest, payload, _, _ in self.releases:
            self.state.save_release(digest, payload)

    def test_cleanup_keeps_current_previous_and_removes_only_recorded_obsolete_image(self):
        self.state.commit(self.releases[2][0], self.releases[1][0])
        self.store.prune()
        self.service.remove_image.assert_called_once_with(self.releases[0][2]["image_id"])
        self.assertFalse(self.state.release_path(self.releases[0][0]).exists())
        self.assertTrue(self.state.release_path(self.releases[1][0]).exists())
        self.assertTrue(self.state.release_path(self.releases[2][0]).exists())

    def test_candidate_is_protected(self):
        self.state.commit(self.releases[1][0], self.releases[0][0])
        self.state.set_candidate(self.releases[2][0])
        self.store.prune()
        self.service.remove_image.assert_not_called()

    def test_obsolete_snapshot_sharing_current_image_does_not_remove_image(self):
        manifest = dict(self.releases[2][2], release="4" * 40)
        payload = json.dumps(manifest, sort_keys=True).encode()
        digest = hashlib.sha256(payload).hexdigest()
        self.state.save_release(digest, payload)
        self.state.commit(self.releases[2][0], self.releases[1][0])
        self.store.prune()
        self.service.remove_image.assert_called_once_with(self.releases[0][2]["image_id"])
        self.assertFalse(self.state.release_path(digest).exists())

    def test_interrupted_downloads_and_snapshots_are_removed_before_next_admission(self):
        self.state.commit(self.releases[2][0], self.releases[1][0])
        for name in ("download-interrupted", "snapshot-interrupted"):
            path = self.state.root / "staging" / name
            path.mkdir(parents=True, exist_ok=True)
            (path / "partial").write_bytes(b"incomplete")
        self.store.prune()
        self.assertEqual(list((self.state.root / "staging").iterdir()), [])
        self.assertTrue(self.state.release_path(self.releases[2][0]).is_dir())

    def test_in_use_image_or_unrecognized_directory_stops_cleanup_without_erasing_record(self):
        self.state.commit(self.releases[2][0], self.releases[1][0])
        self.service.remove_image.side_effect = HostError("Image is in use.")
        with self.assertRaises(HostError):
            self.store.prune()
        self.assertTrue(self.state.release_path(self.releases[0][0]).exists())
        (self.state.releases / "unrelated").mkdir()
        self.service.reset_mock()
        with self.assertRaises(HostError):
            self.store.prune()
        self.service.remove_image.assert_not_called()


class ArtifactPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.state = HostState(root / "state", root / "run", HOST_DIGEST)
        self.digest, self.payload, self.manifest, self.archive = release()
        self.download, self.service = Mock(), Mock()
        def fetch(name, path, digest, **kwargs):
            Path(path).write_bytes(self.payload if name.startswith("releases/") else self.archive)
        self.download.fetch.side_effect = fetch
        self.store = ArtifactStore(self.state, self.download, self.service)

    def test_missing_runtime_snapshot_is_repaired_before_activation(self):
        self.state.save_release(self.digest, self.payload)
        runtime = self.state.release_path(self.digest) / "runtime.json"
        runtime.unlink()
        self.store.prepare(self.digest)
        self.assertEqual(json.loads(runtime.read_bytes()), self.manifest["runtime"])
        self.download.fetch.assert_not_called()

    def test_missing_recorded_image_can_be_downloaded_again(self):
        self.state.save_release(self.digest, self.payload)
        self.service.verify_image.side_effect = [HostError("Image missing."), None]
        with patch("infra.terraform.host.artifacts.shutil.disk_usage", return_value=Mock(free=20 * 2**30)):
            self.store.prepare(self.digest)
        self.assertEqual(self.download.fetch.call_count, 2)
        self.service.load_image.assert_called_once()
        self.assertEqual(list(self.state.staging.iterdir()), [])

    def test_snapshot_failure_does_not_publish_incomplete_release(self):
        with patch("infra.terraform.host.state.atomic_write", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.state.save_release(self.digest, self.payload)
        self.assertFalse(self.state.release_path(self.digest).exists())
