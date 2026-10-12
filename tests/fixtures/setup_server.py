"""Browser-only first-run fixture; all Vault data is invented and held in memory."""

import json
import argparse
from unittest.mock import Mock

import uvicorn

from energy_ai.web.app import create_app
from energy_ai.web.hosted_configuration import HostedConfiguration
from energy_ai.web.hosted_setup import HostedSetup
from energy_ai.web.setup_secrets import SetupSecrets
from tests.fixtures.hosted_runtime import SECRET
from tests.fixtures.setup_runtime import COMPLETED, MemoryVault, SETTINGS_CONFIG


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--configured', action='store_true')
    configured = parser.parse_args().configured
    port = 8769 if configured else 8768
    vault = MemoryVault(COMPLETED if configured else None)
    runtime = HostedSetup(HostedConfiguration.from_bytes(json.dumps(SETTINGS_CONFIG).encode()),
                          Mock(), SetupSecrets(vault, vault, SECRET))
    try:
        uvicorn.run(create_app(access_code=None, origin=f'http://127.0.0.1:{port}', setup=runtime),
                    host='127.0.0.1', port=port, access_log=False)
    finally:
        runtime.close()
