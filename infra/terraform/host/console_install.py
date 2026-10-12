"""Durable admission for one Console installer; activation owns container changes."""

import fcntl
import json
import os
from pathlib import Path
import sys

from .activation import Activator
from .artifacts import ArtifactStore
from .console_contract import parse_installation
from .console_sources import ConsoleDownload, MetadataSource
from .contracts import HostError, bounded_json, digest_value
from .control import CONFIG_PATH, RUN_ROOT, STATE_ROOT, bootstrap_error, load_host_configuration
from .process import run_command
from .service import HostService
from .state import HostState, atomic_write


class ConsoleInstaller:
    def __init__(self, state, activator, config_directory, *, runner=run_command):
        self.state, self.activator = state, activator
        self.config_directory, self.runner = Path(config_directory), runner
        self.journal = state.root / "installation.json"

    def _read(self):
        if not self.journal.exists():
            return None
        try:
            with self.journal.open("rb") as source:
                value = bounded_json(source.read(2049), 2048)
            if (not isinstance(value, dict) or set(value) != {"version", "target", "generation", "attempts", "complete"}
                    or type(value["version"]) is not int or value["version"] != 1
                    or not digest_value(value["target"])
                    or type(value["generation"]) is not int or not 0 <= value["generation"] <= 1000000
                    or type(value["attempts"]) is not int or not 1 <= value["attempts"] <= 12
                    or type(value["complete"]) is not bool):
                raise ValueError()
            return value
        except (OSError, ValueError, TypeError):
            raise HostError("Installer state is invalid; inspect before retrying.") from None

    def _write(self, value):
        atomic_write(self.journal, json.dumps(value, sort_keys=True).encode())

    def run(self, desired):
        with (self.state.run / "installation.lock").open("a") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HostError("Another Console installation is running.") from None
            try:
                return self._install(desired)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _install(self, desired):
        record = self._read()
        if record is not None and desired.generation < record["generation"]:
            raise HostError("Installer generation decreased; inspect stack configuration.")
        if record is None or (record["target"], record["generation"]) != (desired.target, desired.generation):
            record = {"version": 1, "target": desired.target, "generation": desired.generation,
                      "attempts": 0, "complete": False}
        if record["complete"]:
            return "installed"
        if record["attempts"]:
            try:
                confirmed = self.activator.confirm_current(desired.digest)
            except HostError:
                confirmed = False
            if confirmed:
                self._write(dict(record, complete=True))
                return "installed"
        ready, failed = self.config_directory / "ready", self.config_directory / "failed"
        if record["attempts"] >= 12:
            detail = str(bootstrap_error(self.config_directory)) if not ready.is_file() or failed.exists() else (
                "Inspect the preceding installer errors.")
            raise HostError("Installer attempts exhausted. " + detail +
                            " Resolve the cause and increase the retry generation.")
        record["attempts"] += 1
        self._write(record)  # Reserve durably before any package or application operation.
        if not ready.is_file() or failed.exists():
            try:
                self.runner(["/bin/bash", "/opt/oci-energy-ai/host/bootstrap.sh"], timeout=1900)
            except HostError:
                raise bootstrap_error(self.config_directory) from None
        if not ready.is_file() or failed.exists():
            raise bootstrap_error(self.config_directory)
        self.activator.activate(desired.digest, restart_current=False)
        self._write(dict(record, complete=True))
        return "installed"


def main():
    try:
        if os.geteuid() != 0 or len(sys.argv) != 1:
            raise HostError("The Console installer requires its fixed root service.")
        config = load_host_configuration()
        content, vnics = MetadataSource().read()
        desired = parse_installation(content, vnics, config["host_digest"], config["region"])
        state = HostState(STATE_ROOT, RUN_ROOT, config["host_digest"])
        service = HostService(state)
        artifacts = ArtifactStore(state, ConsoleDownload(desired), service)
        status = ConsoleInstaller(state, Activator(state, service, artifacts), CONFIG_PATH.parent).run(desired)
        print(json.dumps({"version": 1, "status": status}))
        return 0
    except HostError as error:
        print(json.dumps({"version": 1, "status": "pending", "detail": str(error)}))
    except Exception:
        print(json.dumps({"version": 1, "status": "pending", "detail": "Installation could not be verified; inspect host readiness."}))
    return 2
