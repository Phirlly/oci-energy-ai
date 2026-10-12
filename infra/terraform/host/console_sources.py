"""Bounded IMDSv2 inputs and anonymous, checksum-pinned public image downloads."""

import hashlib
import http.client
from io import BytesIO
from pathlib import Path
import time
from urllib.parse import quote, urlsplit

from .contracts import HostError, bounded_json


def _transfer(connection, path, output, *, headers, limit, window, monotonic, expected_size=None):
    end = monotonic() + window
    checksum, count = hashlib.sha256(), 0
    response = None
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        length = response.getheader("Content-Length")
        if (response.status != 200 or response.getheader("Content-Encoding") not in (None, "identity")
                or (length is not None and (not length.isdecimal() or int(length) > limit))
                or (expected_size is not None and length != str(expected_size))):
            raise ValueError()
        while True:
            if monotonic() >= end:
                raise TimeoutError()
            chunk = response.read1(min(1024 * 1024, limit + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            if count > limit:
                raise ValueError()
            output.write(chunk)
            checksum.update(chunk)
        if (length is not None and count != int(length)) or (expected_size is not None and count != expected_size):
            raise ValueError()
        return checksum.hexdigest()
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            connection.close()


class MetadataSource:
    def __init__(self, *, connect=http.client.HTTPConnection, monotonic=time.monotonic):
        self.connect, self.monotonic = connect, monotonic

    def _read(self, path, limit):
        output = BytesIO()
        connection = self.connect("169.254.169.254", timeout=10)
        _transfer(connection, path, output, headers={"Authorization": "Bearer Oracle"},
                  limit=limit, window=30, monotonic=self.monotonic)
        return output.getvalue()

    def read(self):
        try:
            metadata = bounded_json(self._read("/opc/v2/instance/metadata/", 65536))
            content = metadata["energy_ai_install"]
            if not isinstance(content, str) or len(content.encode()) > 16384:
                raise ValueError()
            return content.encode(), self._read("/opc/v2/vnics/", 16384)
        except Exception:
            raise HostError("Console instance metadata is unavailable or invalid.") from None


class ConsoleDownload:
    def __init__(self, installation, *, connect=http.client.HTTPSConnection, monotonic=time.monotonic):
        self.installation = installation
        self.connect, self.monotonic = connect, monotonic
        self.manifest = bounded_json(installation.manifest)

    def fetch(self, name, destination, digest, *, max_bytes, expected_size=None):
        try:
            manifest = self.manifest
            local = name == "releases/" + self.installation.digest + ".json"
            size = len(self.installation.manifest) if local else manifest["image_bytes"]
            checksum = self.installation.digest if local else manifest["image_sha256"]
            if (type(max_bytes) is not int or not 0 < max_bytes <= 2**31 or size > max_bytes
                    or digest != checksum or (expected_size is not None and expected_size != size)
                    or (not local and name != "images/" + checksum + ".tar")):
                raise ValueError()
            with Path(destination).open("xb") as output:
                if local:
                    output.write(self.installation.manifest)
                    return
                url = urlsplit(self.installation.artifact_base)
                connection = self.connect(url.hostname, timeout=30)
                actual = _transfer(connection, url.path + quote(name, safe=""), output,
                    headers={}, limit=size, expected_size=size, window=600, monotonic=self.monotonic)
                if actual != checksum:
                    raise ValueError()
        except Exception:
            raise HostError("Public installation artifact could not be verified.") from None
