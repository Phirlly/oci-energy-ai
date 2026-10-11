"""Shared transport limits for presenter-chosen passwords, without strength rules."""

MAX_PASSWORD_CHARACTERS = 200
PASSWORD_GUIDANCE = (
    f"Choose a nonblank password or passphrase of at most {MAX_PASSWORD_CHARACTERS} "
    "printable characters. Spaces and Unicode are supported; matching is exact."
)


def valid_password(value: object) -> bool:
    """Check without trimming or normalizing the supplied value."""
    return (isinstance(value, str) and 1 <= len(value) <= MAX_PASSWORD_CHARACTERS
            and value.isprintable() and bool(value.strip()))
