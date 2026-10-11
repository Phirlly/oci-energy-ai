"""Bounded nonsecret release manifests and fixed operator errors."""

import hashlib
from ipaddress import IPv4Address, IPv4Network
import json
import re


class HostError(Exception):
    """Only fixed safe guidance may be exposed through Run Command."""


def digest_value(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def bounded_json(content, limit=65536):
    if not isinstance(content, bytes) or len(content) > limit:
        raise ValueError()
    return json.loads(content, object_pairs_hook=unique_object)


def _runtime_valid(value):
    if not isinstance(value, dict) or set(value) != {
            "version", "region", "project", "origin", "backend_host", "secret_ids", "model_ids"}:
        return False
    if type(value["version"]) is not int or value["version"] != 1:
        return False
    region = value["region"]
    if not isinstance(region, str) or not re.fullmatch(r"[a-z]{2,3}-[a-z][a-z0-9-]{1,30}-[1-9][0-9]?", region):
        return False
    def identifier(item, kind):
        return isinstance(item, str) and re.fullmatch(
            r"ocid1\." + kind + r"\.oc1\.[a-z0-9-]+\.[a-z0-9.]{20,255}", item)
    if not identifier(value["project"], "generativeaiproject"):
        return False
    if not isinstance(value["origin"], str) or not re.fullmatch(
            r"https://[a-z0-9-]+\.apigateway\." + re.escape(region) + r"\.oci\.customer-oci\.com", value["origin"]):
        return False
    address, port = value["backend_host"].split(":")
    if port != "8080" or not any(IPv4Address(address) in IPv4Network(network)
                                 for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        return False
    secrets = value["secret_ids"]
    if (not isinstance(secrets, dict) or "demo_password" not in secrets
            or set(secrets) - {"demo_password", "openai", "anthropic"}
            or not all(identifier(item, "vaultsecret") for item in secrets.values())
            or len(set(secrets.values())) != len(secrets)):
        return False
    models = value["model_ids"]
    return (isinstance(models, dict) and not set(models) - ({"oci"} | (set(secrets) - {"demo_password"}))
            and all(isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", item)
                    for item in models.values()))


def parse_manifest(content, expected_digest, host_digest):
    try:
        if not digest_value(expected_digest) or hashlib.sha256(content).hexdigest() != expected_digest:
            raise ValueError()
        data = bounded_json(content)
        if not isinstance(data, dict) or set(data) != {
                "version", "host_digest", "release", "image_id", "image_sha256", "image_bytes", "runtime"}:
            raise ValueError()
        if (type(data["version"]) is not int or data["version"] != 1
                or not digest_value(host_digest) or data["host_digest"] != host_digest
                or not isinstance(data["release"], str) or not re.fullmatch(r"[a-f0-9]{40}", data["release"])
                or not isinstance(data["image_id"], str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", data["image_id"])
                or not digest_value(data["image_sha256"]) or type(data["image_bytes"]) is not int
                or not 0 < data["image_bytes"] <= 2**31 or not _runtime_valid(data["runtime"])):
            raise ValueError()
        return data
    except (TypeError, ValueError, AttributeError, KeyError, RecursionError):
        raise HostError("Release manifest or host compatibility check failed.") from None
