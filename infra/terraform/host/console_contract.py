"""Nonsecret Console installation inputs bound to this host and one public build."""

from dataclasses import dataclass
import hashlib
from ipaddress import IPv4Address, IPv4Network
import json
import re

from .contracts import HostError, bounded_json, parse_manifest


@dataclass(frozen=True)
class Installation:
    generation: int
    artifact_base: str
    manifest: bytes
    digest: str
    target: str


def parse_installation(content, vnics_content, host_digest, region):
    try:
        value = bounded_json(content, 16384)
        if (not isinstance(value, dict) or set(value) != {"version", "generation", "artifact_base", "manifest"}
                or type(value["version"]) is not int or value["version"] != 1
                or type(value["generation"]) is not int or not 0 <= value["generation"] <= 1000000):
            raise ValueError()
        base = value["artifact_base"]
        if not isinstance(base, str) or not re.fullmatch(
                r"https://objectstorage\.[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?\.oraclecloud\.com"
                r"/n/[A-Za-z0-9_-]{1,255}/b/[A-Za-z0-9_-]{1,255}/o/", base):
            raise ValueError()
        vnics = bounded_json(vnics_content, 16384)
        if not isinstance(vnics, list) or len(vnics) != 1 or not isinstance(vnics[0], dict):
            raise ValueError()
        address = IPv4Address(vnics[0]["privateIp"])
        subnet = IPv4Network("10.40.1.0/24")
        if (address not in subnet or address in (subnet.network_address, subnet.broadcast_address)
                or vnics[0].get("subnetCidrBlock") != str(subnet)):
            raise ValueError()
        manifest = value["manifest"]
        runtime = manifest["runtime"]
        if (not isinstance(runtime, dict) or "backend_host" in runtime
                or runtime.get("version") != 2 or runtime.get("region") != region):
            raise ValueError()
        runtime["backend_host"] = str(address) + ":8080"
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(payload).hexdigest()
        parse_manifest(payload, digest, host_digest)
        target = hashlib.sha256(base.encode() + b"\n" + payload).hexdigest()
        return Installation(value["generation"], base, payload, digest, target)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, HostError):
        raise HostError("Console installation configuration is invalid or incompatible.") from None
