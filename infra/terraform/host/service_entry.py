"""Root-owned launcher invoked only by systemd."""
import sys

sys.path.insert(0, "/opt/oci-energy-ai")
from host.control import serve

if __name__ == "__main__":
    raise SystemExit(serve())
