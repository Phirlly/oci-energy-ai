"""Browser-only first-run fixture; all Vault data is invented and held in memory."""

import json
from unittest.mock import Mock

import uvicorn

from energy_ai.web.app import create_app
from energy_ai.web.hosted_configuration import HostedConfiguration
from energy_ai.web.hosted_setup import HostedSetup
from energy_ai.web.setup_secrets import SetupSecrets
from tests.fixtures.hosted_runtime import SECRET
from tests.fixtures.setup_runtime import MemoryVault, SETTINGS_CONFIG


if __name__ == '__main__':
    vault = MemoryVault()
    runtime = HostedSetup(HostedConfiguration.from_bytes(json.dumps(SETTINGS_CONFIG).encode()),
                          Mock(), SetupSecrets(vault, vault, SECRET))
    try:
        uvicorn.run(create_app(access_code=None, origin='http://127.0.0.1:8768', setup=runtime),
                    host='127.0.0.1', port=8768, access_log=False)
    finally:
        runtime.close()
