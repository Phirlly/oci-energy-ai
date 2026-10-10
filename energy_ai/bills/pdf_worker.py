"""Isolated PDF text worker. Receives bytes via stdin; never inherits credentials."""

import io
import json
import logging
import resource
import sys

# Set hard limits before importing or parsing untrusted PDF data.
resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
if sys.platform == "linux":
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
elif sys.platform != "darwin":
    raise SystemExit(1)
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
logging.disable(logging.CRITICAL)

from pypdf import PdfReader  # noqa: E402


def main():
    try:
        raw = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024 or not raw.startswith(b"%PDF-"):
            return 1
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
            return 1
        pages = []
        length = 0
        for page in reader.pages:
            text = page.extract_text()
            length += len(text)
            if not text.strip() or length > 60000:
                return 1
            pages.append(text)
        sys.stdout.write(json.dumps(pages, ensure_ascii=True))
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
