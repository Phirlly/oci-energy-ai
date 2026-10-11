"""Public nonsecret manifests for host lifecycle tests (Python 3.9 compatible)."""

import hashlib
import json

HOST_DIGEST = "a" * 64


def release(number=1):
    archive = ("public-image-%d" % number).encode()
    manifest = {
        "version": 1, "host_digest": HOST_DIGEST, "release": "%040x" % number,
        "image_id": "sha256:" + "%064x" % number,
        "image_sha256": hashlib.sha256(archive).hexdigest(), "image_bytes": len(archive),
        "runtime": {
            "version": 1, "region": "us-ashburn-1",
            "project": "ocid1.generativeaiproject.oc1.iad." + "p" * 32,
            "origin": "https://example.apigateway.us-ashburn-1.oci.customer-oci.com",
            "backend_host": "10.40.1.10:8080",
            "secret_ids": {"demo_password": "ocid1.vaultsecret.oc1.iad." + "s" * 32},
            "model_ids": {},
        },
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest(), payload, manifest, archive
