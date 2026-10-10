from pathlib import Path
import tempfile
import unittest

from deployment.terraform_bundle import build_bundle
from tests.fixtures.terraform_source import write_terraform_source


class BundleSourceSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = write_terraform_source(self.root)
        self.output = self.root / "bundle.zip"

    def test_symlinked_member_is_rejected(self):
        member = self.source / "storage.tf"
        member.unlink()
        member.symlink_to(self.source / "project.tf")
        with self.assertRaisesRegex(ValueError, "symlink"):
            build_bundle(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_symlinked_parent_directory_is_rejected(self):
        original = self.root / "original-infra"
        (self.root / "infra").rename(original)
        (self.root / "infra").symlink_to(original, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            build_bundle(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_directory_in_place_of_member_is_rejected(self):
        member = self.source / "storage.tf"
        member.unlink()
        member.mkdir()
        with self.assertRaises(ValueError):
            build_bundle(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_oversized_member_is_rejected_before_writing(self):
        (self.source / "storage.tf").write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "large"):
            build_bundle(self.root, self.output)
        self.assertFalse(self.output.exists())
