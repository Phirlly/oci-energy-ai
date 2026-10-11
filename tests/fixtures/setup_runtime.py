"""In-memory Vault service with invented settings for setup contracts and browser tests."""

import base64
from copy import deepcopy
import json
from unittest.mock import Mock

from oci.exceptions import ServiceError
from oci.response import Response
from oci.vault.models import Secret

from tests.fixtures.hosted_runtime import CONFIG, SECRET, bundle

CODE = 'invented-setup-code-32-characters'
PENDING = {'version': 1, 'setup_code': CODE}
SETTINGS_CONFIG = CONFIG | {'version': 2, 'secret_ids': {'settings': SECRET},
                            'model_ids': {'openai': 'public-model-fixture'}}


class MemoryVault:
    def __init__(self, value=None):
        self.value = deepcopy(PENDING if value is None else value)
        self.tags = {'application': 'oci-energy-ai'}
        if 'password' in self.value:
            self.tags['energy_ai_setup'] = 'complete'
        self.version = 1
        self.writes = []
        self.base_client = Mock()

    def get_secret(self, secret_id, **kwargs):
        return Response(200, {'etag': str(self.version)}, Secret(
            id=secret_id, lifecycle_state='ACTIVE', current_version_number=self.version,
            freeform_tags=dict(self.tags)), None)

    def get_secret_bundle(self, secret_id, *, version_number, **kwargs):
        if version_number != self.version:
            raise ServiceError(404, 'NotFound', {}, 'invented-private-detail')
        return bundle(secret_id=secret_id, value=json.dumps(self.value), version_number=self.version)

    def update_secret(self, secret_id, details, *, if_match, **kwargs):
        self.writes.append((secret_id, details, if_match))
        if if_match != str(self.version):
            raise ServiceError(412, 'NoEtagMatch', {}, 'invented-private-detail')
        self.value = json.loads(base64.b64decode(details.secret_content.content))
        self.tags = dict(details.freeform_tags)
        self.version += 1
        return self.get_secret(secret_id)
