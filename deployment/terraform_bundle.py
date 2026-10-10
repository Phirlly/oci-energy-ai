"""Build a fixed-member Resource Manager configuration archive."""

import argparse
import hashlib
from io import BytesIO
from pathlib import Path
import stat
from zipfile import ZIP_STORED, ZipFile, ZipInfo


_MEMBERS = (
    ".terraform.lock.hcl", "locals.tf", "outputs.tf", "project.tf",
    "providers.tf", "storage.tf", "variables.tf", "versions.tf",
)
_MAX_MEMBER_BYTES = 1024 * 1024


def _read_member(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"Terraform source cannot contain symlinks: {path.name}")
    if not path.is_file():
        raise ValueError(f"Missing regular Terraform source file: {path.name}")
    with path.open("rb") as source:
        content = source.read(_MAX_MEMBER_BYTES + 1)
    if len(content) > _MAX_MEMBER_BYTES:
        raise ValueError(f"Terraform source file is too large: {path.name}")
    return content


def build_bundle(repository_root: Path, output: Path) -> str:
    """Return SHA256; reject unsafe source and never replace an existing output."""
    source = Path(repository_root).absolute() / "infra" / "terraform"
    members = [(name, _read_member(source / name)) for name in _MEMBERS]
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, content in members:
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(entry, content)
    payload = buffer.getvalue()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        destination.write(payload)
    return hashlib.sha256(payload).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="New ZIP path; existing files are preserved.")
    arguments = parser.parse_args()
    try:
        digest = build_bundle(Path(__file__).resolve().parents[1], arguments.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    print(f"SHA256 {digest}")


if __name__ == "__main__":
    main()
