"""Single-writer activation and rollback with a durable readiness commit."""

from .contracts import HostError, digest_value


class Activator:
    def __init__(self, state, service, artifacts):
        self.state, self.service, self.artifacts = state, service, artifacts

    def _restore(self, current):
        self.service.stop()
        self.state.clear_candidate()
        if current is not None:
            self.service.start()
            self.service.health(self.state.manifest(current))

    def _reconcile(self):
        current = self.state.read()["current"]
        candidate = self.state.candidate()
        if candidate is not None:
            if candidate == current:
                self.state.clear_candidate()
            else:
                self._restore(current)
        self.artifacts.prune()

    def activate(self, digest, *, restart_current=True):
        if not digest_value(digest):
            raise HostError("Invalid release identifier.")
        with self.state.lock():
            self._reconcile()
            self.artifacts.prepare(digest)
            self._activate(digest, restart_current=restart_current)

    def confirm_current(self, digest):
        if not digest_value(digest):
            raise HostError("Invalid release identifier.")
        with self.state.lock():
            if self.state.read()["current"] != digest or self.state.candidate() not in (None, digest):
                return False
            manifest = self.state.manifest(digest)
            self.service.verify_image(manifest)
            self.service.health(manifest)
            return True

    def rollback(self):
        with self.state.lock():
            self._reconcile()
            previous = self.state.read()["previous"]
            if previous is None:
                raise HostError("No previous compatible release is available.")
            self.artifacts.verify(previous)
            self._activate(previous)

    def _activate(self, digest, *, restart_current=True):
        committed = self.state.read()
        manifest = self.state.manifest(digest)
        if committed["current"] == digest:
            if restart_current:
                self.service.stop()
                self.service.start()
            self.service.health(manifest)
            return
        # Stop must prove absence before publishing any new writer selection.
        self.service.stop()
        try:
            self.state.set_candidate(digest)
            self.service.start()
            self.service.health(manifest)
            self.state.commit(digest, committed["current"])
        except Exception:
            # A failed fsync after replace has an ambiguous durability result.
            # Never revert a state file that already publishes the new release.
            if self.state.read()["current"] == digest:
                raise HostError("Release committed; completion check failed. Reconcile before retrying.") from None
            try:
                self._restore(committed["current"])
            except Exception:
                raise HostError("Candidate failed and recovery needs inspection; no new writer admitted.") from None
            raise HostError("Candidate failed; the previously committed selection was restored.") from None
        try:
            self.state.clear_candidate()
            self.artifacts.prune()
        except Exception:
            raise HostError("Release committed; artifact cleanup is pending before the next deployment.") from None

    def stop(self):
        with self.state.lock():
            self.service.stop()
            self.state.clear_candidate()
