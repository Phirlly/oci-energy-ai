"""Fake GitHub setup values shared by unit and CLI contract tests."""


def configured_environment():
    return {
        "DEPLOYMENT_ID": "fixture-demo",
        "OCI_REGION": "us-ashburn-1",
        "OCI_COMPARTMENT_OCID": "ocid1.compartment.oc1.." + "a" * 32,
        "OCI_TENANCY_OCID": "ocid1.tenancy.oc1.." + "b" * 32,
        "OCI_USER_OCID": "ocid1.user.oc1.." + "c" * 32,
        "OCI_FINGERPRINT": ":".join(["ab"] * 16),
        "OCI_PRIVATE_KEY": "fake-private-key-presence-only",
    }
