"""Fixed root entrypoints; no shell fragments or credentials in commands/results."""

import json
import os
from pathlib import Path
import re
import sys

from .activation import Activator
from .artifacts import ArtifactStore, ObjectDownload
from .contracts import HostError, bounded_json, digest_value
from .process import SAFE_ENVIRONMENT
from .service import HostService, container_arguments
from .state import HostState

CONFIG_PATH = Path("/etc/oci-energy-ai/host.json")
STATE_ROOT = Path("/var/lib/oci-energy-ai")
RUN_ROOT = Path("/run/oci-energy-ai")


def load_host_configuration(path=CONFIG_PATH):
    try:
        with Path(path).open("rb") as source:
            value = bounded_json(source.read(4097), 4096)
        if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] not in (1, 2)
                or not digest_value(value["host_digest"])):
            raise ValueError()
        patterns = {"region": r"[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?"}
        if value["version"] == 1:
            patterns.update(namespace=r"[A-Za-z0-9_-]{1,255}",
                            bucket=r"oci-energy-ai-[a-z][a-z0-9-]{1,30}[a-z0-9]-artifacts")
        if set(value) != {"version", "host_digest"} | set(patterns):
            raise ValueError()
        for key, pattern in patterns.items():
            if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
                raise ValueError()
        return value
    except (OSError, TypeError, ValueError, KeyError):
        raise HostError("Host bootstrap configuration is unavailable or invalid.") from None


def main(arguments=None, *, config_path=CONFIG_PATH, root=STATE_ROOT, run=RUN_ROOT):
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if os.geteuid() != 0 or not arguments:
            raise HostError("A root-owned deployment operation is required.")
        operation = arguments[0]
        if (operation not in {"status", "activate", "rollback", "stop"}
                or len(arguments) != (2 if operation == "activate" else 1)
                or (operation == "activate" and not digest_value(arguments[1]))):
            raise HostError("Invalid fixed host operation.")
        config = load_host_configuration(config_path)
        if config["version"] == 2 and operation in {"activate", "rollback"}:
            raise HostError("Use the Console installer to change this installation.")
        if (Path(config_path).parent / "failed").exists():
            raise HostError("Host bootstrap failed; inspect cloud-init before retrying.")
        if not (Path(config_path).parent / "ready").is_file():
            if operation == "status":
                print(json.dumps({"version": 1, "status": "bootstrapping"}))
                return 0
            raise HostError("Host bootstrap is not ready.")
        state = HostState(root, run, config["host_digest"])
        service = HostService(state)
        artifacts = ArtifactStore(state, ObjectDownload(config), service) if config["version"] == 1 else None
        activator = Activator(state, service, artifacts)
        if operation == "activate":
            activator.activate(arguments[1])
        elif operation == "rollback":
            activator.rollback()
        elif operation == "stop":
            activator.stop()
        committed = state.read()
        release = state.manifest(committed["current"])["release"] if committed["current"] else None
        print(json.dumps({"version": 1, "status": "ready", "host_digest": config["host_digest"],
                          "current": committed["current"], "previous": committed["previous"],
                          "candidate": state.candidate(), "release": release}, sort_keys=True))
        return 0
    except HostError as error:
        print(json.dumps({"version": 1, "status": "error", "detail": str(error)}))
    except Exception:
        print(json.dumps({"version": 1, "status": "error", "detail": "Host operation failed; reconcile before retrying."}))
    return 2


def serve():
    try:
        if os.geteuid() != 0:
            raise HostError("Root service launcher required.")
        config = load_host_configuration()
        state = HostState(STATE_ROOT, RUN_ROOT, config["host_digest"])
        selected = state.selected()
        if selected is None:
            raise HostError("No committed or admitted release exists.")
        arguments = container_arguments(state, selected)
        environment = dict(SAFE_ENVIRONMENT, PODMAN_SYSTEMD_UNIT="oci-energy-ai.service")
        if os.environ.get("NOTIFY_SOCKET"):
            environment["NOTIFY_SOCKET"] = os.environ["NOTIFY_SOCKET"]
        os.execve(arguments[0], arguments, environment)
    except Exception:
        print("Host service launch failed; inspect release selection and readiness.", file=sys.stderr)
        return 2
