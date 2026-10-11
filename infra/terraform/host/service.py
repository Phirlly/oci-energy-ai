"""Podman supervision, single-writer stop and exact application readiness."""

import http.client
import json
import time

from .contracts import HostError
from .process import run_command

PODMAN = "/usr/bin/podman"
UNIT = "oci-energy-ai.service"


def container_arguments(state, digest):
    manifest = state.manifest(digest)
    return [PODMAN, "run", "--name=oci-energy-ai", "--rm", "-d", "--pull=never",
            "--sdnotify=conmon", "--cgroups=split", "--network=host",
            "--user=10001:10001", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=256", "--memory=2g", "--cpus=2",
            "--stop-timeout=20", "--log-driver=journald",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,mode=1777",
            "--volume", str(state.root / "data") + ":/data:rw,Z",
            "--volume", str(state.release_path(digest) / "runtime.json") + ":/etc/energy-ai/runtime.json:ro,Z",
            manifest["image_id"]]


class HostService:
    def __init__(self, state, *, runner=run_command, monotonic=time.monotonic, sleep=time.sleep):
        self.state, self.runner = state, runner
        self.monotonic, self.sleep = monotonic, sleep

    def stop(self):
        self.runner(["/usr/bin/systemctl", "stop", UNIT], timeout=60)
        remaining = self.runner([PODMAN, "ps", "--quiet", "--sync", "--all",
                                 "--filter=name=^oci-energy-ai$"], timeout=15)
        if remaining.strip():
            raise HostError("Application container still exists; another writer was not started.")

    def start(self):
        self.runner(["/usr/bin/systemctl", "reset-failed", UNIT], timeout=10)
        self.runner(["/usr/bin/systemctl", "start", UNIT], timeout=150)

    def verify_image(self, manifest):
        template = ('{"Id":{{json .ID}},"Architecture":{{json .Architecture}},'
                    '"User":{{json .Config.User}},"Release":{{json (index .Labels "org.opencontainers.image.revision")}}}')
        output = self.runner([PODMAN, "image", "inspect", "--format", template, manifest["image_id"]], timeout=30)
        try:
            value = json.loads(output)
            identity = value["Id"]
            if not identity.startswith("sha256:"):
                identity = "sha256:" + identity
            if (identity != manifest["image_id"] or value["Architecture"] != "amd64"
                    or value["User"] != "10001:10001" or value["Release"] != manifest["release"]):
                raise ValueError()
        except (TypeError, ValueError, KeyError, AttributeError):
            raise HostError("Loaded image identity, architecture, user or release does not match.") from None

    def load_image(self, archive):
        self.runner([PODMAN, "load", "--input", str(archive)], timeout=300)

    def remove_image(self, identity):
        self.runner([PODMAN, "rmi", "--ignore", identity], timeout=60)

    def health(self, manifest, *, timeout=120):
        end = self.monotonic() + timeout
        while self.monotonic() < end:
            connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=min(3, end - self.monotonic()))
            try:
                connection.request("GET", "/healthz", headers={"Host": manifest["runtime"]["backend_host"]})
                response = connection.getresponse()
                content = response.read(2049)
                value = json.loads(content) if len(content) <= 2048 else {}
                if (response.status == 200 and value == {
                        "status": "ready", "release": manifest["release"], "schema": 1}):
                    return
            except (OSError, ValueError, http.client.HTTPException):
                pass
            finally:
                connection.close()
            self.sleep(min(2, max(0, end - self.monotonic())))
        raise HostError("Application did not become ready with the expected release and schema.")
