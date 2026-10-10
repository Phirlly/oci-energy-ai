"""Bounded POSIX subprocess parsing, with kill/reap on timeout or cancellation."""

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import sys

MAX_BYTES = 4 * 1024 * 1024


class PdfError(ValueError):
    def __init__(self):
        super().__init__("Use an unencrypted text PDF: at most 4 MiB, 20 nonempty text pages and 60,000 characters. Scans need OCR first.")


async def start_child(*arguments, **options):
    spawning = asyncio.create_task(asyncio.create_subprocess_exec(*arguments, **options))
    try:
        return await asyncio.shield(spawning)
    except asyncio.CancelledError:
        process = await spawning
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await process.wait()
        raise


async def resident_kib(pid):
    inspector = await start_child(
        "/bin/ps", "-o", "rss=", "-p", str(pid), env={},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=128)
    try:
        async with asyncio.timeout(.5):
            output = await inspector.stdout.read(65)
            await inspector.wait()
            if inspector.returncode != 0 or len(output) > 64 or not output.strip().isdigit():
                raise PdfError()
            return int(output)
    finally:
        if inspector.returncode is None:
            with suppress(ProcessLookupError):
                inspector.kill()
        await inspector.wait()


async def watch_memory(process):
    while process.returncode is None:
        try:
            if await resident_kib(process.pid) > 256 * 1024:
                raise PdfError()
        except (PdfError, TimeoutError, OSError):
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                raise PdfError() from None
            return
        await asyncio.sleep(.1)


async def extract_pdf(raw, *, timeout=12):
    if sys.platform not in {"darwin", "linux"} or len(raw) > MAX_BYTES or not raw.startswith(b"%PDF-"):
        raise PdfError()
    process = await start_child(
        sys.executable, "-I", "-B", str(Path(__file__).with_name("pdf_worker.py")),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env={}, limit=512 * 1024)
    watchdog = asyncio.create_task(watch_memory(process)) if sys.platform == "darwin" else None
    try:
        async with asyncio.timeout(min(timeout, 12)):
            process.stdin.write(raw)
            await process.stdin.drain()
            process.stdin.close()
            # Read a hard upper bound, not communicate()'s unbounded accumulator.
            try:
                output = await process.stdout.readexactly(400001)
                raise PdfError()
            except asyncio.IncompleteReadError as done:
                output = done.partial
            await process.wait()
            if watchdog and watchdog.done():
                await watchdog
    except (TimeoutError, BrokenPipeError, ConnectionResetError):
        raise PdfError() from None
    finally:
        if watchdog:
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await process.wait()
    if process.returncode != 0 or len(output) > 400000:
        raise PdfError()
    try:
        pages = json.loads(output)
        if (not isinstance(pages, list) or not 1 <= len(pages) <= 20
                or any(not isinstance(p, str) or not p.strip() for p in pages)
                or sum(map(len, pages)) > 60000):
            raise ValueError()
        return pages
    except (ValueError, TypeError):
        raise PdfError() from None
