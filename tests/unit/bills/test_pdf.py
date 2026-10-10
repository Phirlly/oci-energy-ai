import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from energy_ai.bills.pdf import extract_pdf, PdfError, resident_kib, watch_memory
from tests.fixtures.bills import pdf_bytes


class PdfInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_extracts_pages_from_a_real_text_pdf(self):
        pages = await extract_pdf(pdf_bytes())
        self.assertEqual(len(pages), 1)
        self.assertIn("Consumption 580 kWh", pages[0])

    async def test_rejects_unsafe_or_unreadable_inputs(self):
        for label, data in (("not_pdf", b"hello"), ("malformed", b"%PDF-1.7\nno objects"),
                            ("encrypted", pdf_bytes(encrypted=True)),
                            ("blank", pdf_bytes(text="")),
                            ("pages", pdf_bytes(pages=21)),
                            ("bytes", b"%PDF-" + b"x" * (4 * 1024 * 1024))):
            with self.subTest(label=label), self.assertRaises(PdfError):
                await extract_pdf(data)

    async def test_deadline_is_enforced(self):
        with self.assertRaises(PdfError):
            await extract_pdf(pdf_bytes(), timeout=0.0001)

    async def test_unsupported_platform_is_rejected_without_spawning(self):
        with patch("energy_ai.bills.pdf.sys.platform", "win32"), self.assertRaises(PdfError):
            await extract_pdf(pdf_bytes())


class ParserMemoryWatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def test_over_threshold_and_failed_inspection_kill_parser(self):
        for result in (300000, PdfError(), TimeoutError()):
            process = SimpleNamespace(pid=123, returncode=None, kill=Mock())
            reader = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
            with self.subTest(result=type(result)), patch("energy_ai.bills.pdf.resident_kib", reader):
                with self.assertRaises(PdfError):
                    await watch_memory(process)
                process.kill.assert_called_once()

    async def test_normal_exit_racing_inspection_is_not_failure(self):
        process = SimpleNamespace(pid=123, returncode=None, kill=Mock())
        async def finished(pid):
            process.returncode = 0
            raise PdfError()
        with patch("energy_ai.bills.pdf.resident_kib", finished):
            await watch_memory(process)
        process.kill.assert_not_called()

    async def test_inspector_is_reaped_on_cancellation_and_hang(self):
        for cancel in (True, False):
            started = asyncio.Event()
            async def never(length):
                started.set()
                await asyncio.Event().wait()
            process = SimpleNamespace(stdout=SimpleNamespace(read=never), returncode=None,
                                      kill=Mock(), wait=AsyncMock())
            with self.subTest(cancel=cancel), patch("energy_ai.bills.pdf.start_child", AsyncMock(return_value=process)):
                task = asyncio.create_task(resident_kib(123))
                await started.wait()
                if cancel:
                    task.cancel()
                with self.assertRaises(asyncio.CancelledError if cancel else TimeoutError):
                    await task
                process.kill.assert_called_once()
                process.wait.assert_awaited_once()

    async def test_inspector_rejects_malformed_or_excessive_output(self):
        for output in (b"", b"wrong", b"1" * 65):
            process = SimpleNamespace(stdout=SimpleNamespace(read=AsyncMock(return_value=output)),
                                      returncode=0, wait=AsyncMock())
            with self.subTest(output=output), patch("energy_ai.bills.pdf.start_child", AsyncMock(return_value=process)):
                with self.assertRaises(PdfError):
                    await resident_kib(123)
