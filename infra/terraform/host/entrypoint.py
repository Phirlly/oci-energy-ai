#!/usr/bin/python3 -EsB
"""The sole privileged entrypoint allowed to the OCI command agent."""
import sys

sys.path.insert(0, "/opt/oci-energy-ai")
from host.control import main

if __name__ == "__main__":
    raise SystemExit(main())
