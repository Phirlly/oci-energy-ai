"""Private immutable downloads and retention of this helper's recorded images."""

import hashlib
from pathlib import Path
import re
import shutil
import tempfile

from .contracts import HostError, digest_value, parse_manifest
from .process import run_command


class ObjectDownload:
    def __init__(self, config, *, runner=run_command):
        self.config, self.runner = config, runner

    def fetch(self, name, destination, digest, *, max_bytes, expected_size=None):
        if (not digest_value(digest) or not re.fullmatch(r"(?:images/[a-f0-9]{64}\.tar|releases/[a-f0-9]{64}\.json)", name)
                or type(max_bytes) is not int or not 0 < max_bytes <= 2**31):
            raise HostError("Invalid immutable artifact request.")
        destination = Path(destination)
        self.runner(["/usr/bin/oci", "--config-file", "/dev/null", "--cli-rc-file", "/dev/null",
                     "--auth", "instance_principal", "--region", self.config["region"], "--no-retry",
                     "--connection-timeout", "10", "--read-timeout", "30", "os", "object", "get",
                     "--namespace-name", self.config["namespace"], "--bucket-name", self.config["bucket"],
                     "--name", name, "--file", str(destination), "--no-multipart"],
                    timeout=600, file_limit=max_bytes + 1)
        size = destination.stat().st_size
        if size > max_bytes or (expected_size is not None and size != expected_size):
            raise HostError("Artifact size does not match the reviewed release.")
        checksum = hashlib.sha256()
        with destination.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                checksum.update(chunk)
        if checksum.hexdigest() != digest:
            raise HostError("Artifact checksum does not match the reviewed release.")


class ArtifactStore:
    def __init__(self, state, download, service):
        self.state, self.download, self.service = state, download, service

    def prepare(self, digest):
        if (self.state.release_path(digest) / "manifest.json").exists():
            manifest = self.state.manifest(digest)
            try:
                self.service.verify_image(manifest)
            except HostError:
                pass  # Re-download an unavailable image before changing the service.
            else:
                self.state.save_release(digest, self.state.manifest_content(digest))
                return
        with tempfile.TemporaryDirectory(prefix="download-", dir=self.state.staging) as temporary:
            directory = Path(temporary)
            manifest_path = directory / "release.json"
            self.download.fetch("releases/" + digest + ".json", manifest_path, digest, max_bytes=65536)
            content = manifest_path.read_bytes()
            manifest = parse_manifest(content, digest, self.state.host_digest)
            if shutil.disk_usage(self.state.root).free < 3 * manifest["image_bytes"] + 4 * 2**30:
                raise HostError("Insufficient disk space for safe image preparation and rollback.")
            archive = directory / "image.tar"
            self.download.fetch("images/" + manifest["image_sha256"] + ".tar", archive,
                                manifest["image_sha256"], max_bytes=manifest["image_bytes"],
                                expected_size=manifest["image_bytes"])
            # Record before load so an interrupted/failed load remains scoped for cleanup.
            self.state.save_release(digest, content)
            self.service.load_image(archive)
            self.service.verify_image(manifest)

    def verify(self, digest):
        self.service.verify_image(self.state.manifest(digest))
        self.state.save_release(digest, self.state.manifest_content(digest))

    def prune(self):
        committed = self.state.read()
        keep = {committed["current"], committed["previous"], self.state.candidate()} - {None}
        paths = list(self.state.releases.iterdir())
        if any(path.is_symlink() or not path.is_dir() or not digest_value(path.name) for path in paths):
            raise HostError("Unrecognized release artifacts require inspection; nothing was removed.")
        manifests = {path.name: self.state.manifest(path.name) for path in paths}
        kept_images = {manifests[key]["image_id"] for key in keep}
        staged = list(self.state.staging.iterdir())
        if any(path.is_symlink() or not path.is_dir()
               or not re.fullmatch(r"(?:download|snapshot)-[A-Za-z0-9_-]+", path.name) for path in staged):
            raise HostError("Unrecognized staging artifacts require inspection; nothing was removed.")
        for path in staged:
            shutil.rmtree(path)
        # A killed atomic write may leave a small unpublished temporary file.
        for directory in (self.state.root, self.state.run, *paths):
            for path in directory.glob(".pending-*"):
                if path.is_file() and not path.is_symlink():
                    path.unlink()
        for path in paths:
            if path.name in keep:
                continue
            identity = manifests[path.name]["image_id"]
            if identity not in kept_images:
                self.service.remove_image(identity)
            shutil.rmtree(path)
