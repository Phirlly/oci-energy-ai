"""Cold hosted import probe; launched by the CLI contract in an isolated interpreter."""

import builtins
from contextlib import redirect_stderr
from io import StringIO
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
original_import = builtins.__import__
checked = []
violations = []
network_attempts = []


def guarded_import(name, *args, **kwargs):
    if name == 'uvicorn' or name == 'oci' or name.startswith('oci.'):
        checked.append(name)
        if any(key in os.environ for key in ('OCI_METADATA_BASE_URL', 'OPENAI_API_KEY', 'HTTPS_PROXY')):
            violations.append(name)
            raise AssertionError('Hosted import happened before environment isolation.')
    return original_import(name, *args, **kwargs)


def no_network(event, arguments):
    if event == 'socket.connect':
        network_attempts.append(event)
        raise AssertionError('Network is forbidden in this fixture.')


sys.addaudithook(no_network)
builtins.__import__ = guarded_import
from energy_ai.web.serve import main

with redirect_stderr(StringIO()):
    status = main(configuration_path=Path(sys.argv[1]))
if status != 2 or not checked or violations or network_attempts:
    raise AssertionError('Expected isolated import and failure before credentials/network.')
print('isolated-import-verified')
