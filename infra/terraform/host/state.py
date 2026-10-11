"""Root-owned committed release selection, snapshots and operation lock."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile

from .contracts import HostError, bounded_json, digest_value, parse_manifest


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path, content):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


class HostState:
    def __init__(self, root, run, host_digest):
        self.root, self.run, self.host_digest = Path(root), Path(run), host_digest
        self.releases = self.root / "releases"
        self.staging = self.root / "staging"
        for path in (self.root, self.run, self.releases, self.staging):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def lock(self):
        with (self.run / "operation.lock").open("a") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HostError("Another host operation is running.") from None
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def read(self):
        path = self.root / "state.json"
        if not path.exists():
            return {"version": 1, "current": None, "previous": None}
        try:
            with path.open("rb") as source:
                data = bounded_json(source.read(1025), 1024)
            if (not isinstance(data, dict) or set(data) != {"version", "current", "previous"}
                    or type(data["version"]) is not int or data["version"] != 1
                    or not digest_value(data["current"])
                    or (data["previous"] is not None and not digest_value(data["previous"]))
                    or data["current"] == data["previous"]):
                raise ValueError()
            return data
        except (OSError, ValueError, TypeError):
            raise HostError("Committed host state is invalid; no release changed.") from None

    def commit(self, current, previous):
        if not digest_value(current) or (previous is not None and not digest_value(previous)) or current == previous:
            raise HostError("Invalid release commit.")
        atomic_write(self.root / "state.json", json.dumps(
            {"version": 1, "current": current, "previous": previous}, sort_keys=True).encode())

    def candidate(self):
        path = self.run / "candidate"
        if not path.exists():
            return None
        with path.open("r", encoding="ascii") as source:
            value = source.read(66).strip()
        if not digest_value(value):
            raise HostError("Interrupted candidate state is invalid.")
        return value

    def set_candidate(self, digest):
        if not digest_value(digest):
            raise HostError("Invalid candidate identifier.")
        atomic_write(self.run / "candidate", digest.encode())

    def clear_candidate(self):
        (self.run / "candidate").unlink(missing_ok=True)

    def selected(self):
        return self.candidate() or self.read()["current"]

    def release_path(self, digest):
        if not digest_value(digest):
            raise HostError("Invalid release identifier.")
        return self.releases / digest

    def save_release(self, digest, content):
        manifest = parse_manifest(content, digest, self.host_digest)
        target = self.release_path(digest)
        runtime = json.dumps(manifest["runtime"], sort_keys=True).encode()
        if target.exists():
            if self.manifest_content(digest) != content:
                raise HostError("An immutable release snapshot differs.")
            self._runtime_snapshot(target, runtime)
            return
        # Publish the complete snapshot together; killed preparation stays in staging.
        with tempfile.TemporaryDirectory(prefix="snapshot-", dir=self.staging) as temporary:
            directory = Path(temporary)
            atomic_write(directory / "manifest.json", content)
            self._runtime_snapshot(directory, runtime)
            os.replace(directory, target)
            sync_directory(self.releases)

    @staticmethod
    def _runtime_snapshot(target, content):
        path = target / "runtime.json"
        if not path.exists() or path.read_bytes() != content:
            atomic_write(path, content)
        # The nonsecret mount must be readable by container UID10001.
        path.chmod(0o444)

    def manifest_content(self, digest):
        with (self.release_path(digest) / "manifest.json").open("rb") as source:
            return source.read(65537)

    def manifest(self, digest):
        return parse_manifest(self.manifest_content(digest), digest, self.host_digest)
