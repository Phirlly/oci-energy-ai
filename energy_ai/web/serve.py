"""Hosted process entrypoint. The local presenter remains python -m energy_ai.web."""

# Only stdlib imports here: OCI has import-time environment/configuration hooks.
import logging
import os
from pathlib import Path
import re
import sys

APP_ROOT = Path(__file__).resolve().parents[2]


def main(*, configuration_path=Path('/etc/energy-ai/runtime.json'),
         release_path=Path('/app/release.txt'), database_path=Path('/data/office.sqlite3')):
    os.environ.clear()
    os.environ.update(PATH='/usr/local/bin:/usr/bin:/bin', LANG='C.UTF-8',
                      PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    logging.disable(logging.CRITICAL)
    runtime = None
    try:
        import uvicorn
        from energy_ai.web.app import create_app
        from energy_ai.web.hosted_configuration import HostedConfiguration
        from energy_ai.web.hosted_runtime import load_runtime

        config = HostedConfiguration.load(configuration_path)
        with Path(release_path).open('r', encoding='ascii') as source:
            release = source.read(42)
        if not re.fullmatch(r'[a-f0-9]{40}\n?', release) or not (APP_ROOT / 'frontend/dist/index.html').is_file():
            raise ValueError()
        release = release.strip()
        runtime = load_runtime(config)
        app = create_app(access_code=runtime.password, origin=config.origin, backend_host=config.backend_host,
                         release=release, providers=runtime.providers, model_ids=config.models(),
                         extractor=runtime.extract, office_analyzer=runtime.analyze, office_database=database_path)
        uvicorn.run(app, host='0.0.0.0', port=8080, workers=1, proxy_headers=False,
                    access_log=False, log_config=None, timeout_graceful_shutdown=15)
        return 0
    except (Exception, SystemExit):
        print('Hosted startup or serving failed. Check runtime configuration, OCI identity and Vault access.', file=sys.stderr)
        return 2
    finally:
        if runtime is not None:
            runtime.close()


if __name__ == '__main__':
    raise SystemExit(main())
