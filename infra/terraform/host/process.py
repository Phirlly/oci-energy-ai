"""Bounded fixed host commands with no inherited OCI or shell configuration."""

import os
import resource
import selectors
import signal
import subprocess
import time

from .contracts import HostError

SAFE_ENVIRONMENT = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root", "LANG": "C.UTF-8"}


def _remaining(end):
    remaining = end - time.monotonic()
    if remaining <= 0:
        raise HostError("A bounded host command timed out.")
    return remaining


def _capture(process, end):
    content = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            if not selector.select(_remaining(end)):
                continue
            chunk = os.read(process.stdout.fileno(), min(8192, 65537 - len(content)))
            if not chunk:
                return bytes(content)
            content.extend(chunk)
            if len(content) > 65536:
                raise HostError("A bounded host command exceeded its output limit.")


def run_command(arguments, *, timeout, file_limit=None):
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
    process = None
    try:
        end = time.monotonic() + timeout
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=SAFE_ENVIRONMENT, bufsize=0,
                                   start_new_session=True, preexec_fn=limits if file_limit is not None else None)
        try:
            content = _capture(process, end)
            if process.wait(timeout=_remaining(end)) != 0:
                raise HostError("A bounded host command failed; inspect host readiness.")
            return content.decode("utf-8")
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            raise
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise HostError("A bounded host command failed or timed out.") from None
    finally:
        if process is not None:
            process.stdout.close()
