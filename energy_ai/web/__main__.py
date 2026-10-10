"""Start the loopback-only presenter. Build frontend first with npm run build."""

import argparse
import logging
import os
from pathlib import Path
import secrets

import uvicorn

from energy_ai.web.app import create_app
from energy_ai.web.runtime import configured_providers, extract_configured, analyze_configured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a port between 1024 and 65535.")
    if not (Path(__file__).resolve().parents[2] / "frontend/dist/index.html").is_file():
        parser.error("Build the browser application first: cd frontend && npm ci && npm run build")
    code = os.environ.get("ENERGY_ACCESS_CODE") or secrets.token_urlsafe(18)
    origin = f"http://127.0.0.1:{args.port}"
    runtime = Path(__file__).resolve().parents[2] / 'runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    app = create_app(access_code=code, origin=origin, providers=configured_providers(os.environ),
                     extractor=extract_configured,
                     office_analyzer=analyze_configured, office_database=runtime / 'office.sqlite3',
                     model_ids={p: os.environ.get(f"{p.upper()}_MODEL") for p in configured_providers(os.environ)})
    # Standalone process: prevent SDK, transport and server tracebacks from logging bill content.
    # No request toggles, raw request logs or response artifacts.
    logging.disable(logging.CRITICAL)
    print(f"Open {origin}\nLaunch code: {code}\nSession lasts 30 minutes. Private bills clear on sign-out/restart. "
          "Public office history is shared and kept for 7 days (100 runs).", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, access_log=False, log_config=None)


if __name__ == "__main__":
    main()
