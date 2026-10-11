"""Invented hosted configuration and Vault responses; no live identities or secrets."""

import base64

from oci.secrets.models import Base64SecretBundleContentDetails, SecretBundle
from oci.response import Response

SECRET = 'ocid1.vaultsecret.oc1.iad.' + 'a' * 32
CONFIG = dict(version=1, region='us-ashburn-1', project='ocid1.generativeaiproject.oc1.iad.' + 'b' * 32,
              origin='https://demo.example', backend_host='10.40.1.8:8080',
              secret_ids={'demo_password': SECRET}, model_ids={})
PASSWORD = 'invented-fixture-password-123'


def bundle(secret_id=SECRET, value=PASSWORD, **changes):
    return Response(200, {}, SecretBundle(**(dict(secret_id=secret_id, stages=['CURRENT'], version_number=1,
        secret_bundle_content=Base64SecretBundleContentDetails(
            content=base64.b64encode(value.encode()).decode())) | changes)), None)
