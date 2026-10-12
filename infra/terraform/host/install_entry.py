#!/usr/bin/python3 -EsB
"""Fixed root service entrypoint for Console installation."""
import sys

sys.path.insert(0, "/opt/oci-energy-ai")
from host.console_install import main

if __name__ == "__main__":
    raise SystemExit(main())
