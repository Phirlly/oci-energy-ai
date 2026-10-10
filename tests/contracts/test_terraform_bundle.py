import hashlib
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from deployment.terraform_bundle import build_bundle
from tests.fixtures.terraform_source import EXPECTED_MEMBERS, write_terraform_source


class TerraformBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = write_terraform_source(self.root)

    def test_exact_members_exclude_local_data_and_keep_provider_lock(self):
        for name in ("terraform.tfstate", "secret.tfvars", "private.key", "extra.tf"):
            (self.source / name).write_text("private-marker", encoding="utf-8")
        (self.root / "PLAN.md").write_text("local-only", encoding="utf-8")
        output = self.root / "bundle.zip"
        digest = build_bundle(self.root, output)
        with ZipFile(output) as archive:
            self.assertEqual(archive.namelist(), list(EXPECTED_MEMBERS))
            for name in EXPECTED_MEMBERS:
                self.assertEqual(archive.read(name), (self.source / name).read_bytes())
        self.assertEqual(digest, hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertNotIn(b"private-marker", output.read_bytes())

    def test_identical_source_gives_identical_bytes_despite_source_metadata(self):
        first, second = self.root / "one.zip", self.root / "two.zip"
        first_digest = build_bundle(self.root, first)
        (self.source / "storage.tf").chmod(0o700)
        (self.source / "storage.tf").touch()
        self.assertEqual(build_bundle(self.root, second), first_digest)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_existing_output_is_preserved(self):
        output = self.root / "existing.zip"
        output.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            build_bundle(self.root, output)
        self.assertEqual(output.read_bytes(), b"preserve")

    def test_missing_member_leaves_no_partial_archive(self):
        (self.source / "storage.tf").unlink()
        output = self.root / "failed.zip"
        with self.assertRaises(ValueError):
            build_bundle(self.root, output)
        self.assertFalse(output.exists())
