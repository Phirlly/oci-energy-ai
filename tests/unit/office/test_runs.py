import asyncio
from pathlib import Path
import tempfile
import unittest

from energy_ai.agents.analysis import AnalysisError
from energy_ai.office.runs import RunError, RunRepository
from energy_ai.office.run_service import RunService
from energy_ai.office.sample import Controls

PAYLOAD = dict(provider='openai', model='fixture-model', controls=Controls().model_dump(), question='explain_bill')


class RunRepositoryTests(unittest.TestCase):
    def test_reopen_preserves_results_and_interrupts_unfinished_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runs.db'
            store = RunRepository(path)
            done = store.create('one', PAYLOAD)
            store.finish(done['id'], 'complete', result={'safe': 'public'})
            pending = store.create('two', PAYLOAD)
            store.close()
            store = RunRepository(path)
            try:
                self.assertEqual(store.get(done['id'])['result'], {'safe': 'public'})
                self.assertEqual(store.get(pending['id'])['status'], 'interrupted')
                self.assertFalse(store.finish(pending['id'], 'complete', result={'late': True}))
            finally:
                store.close()

    def test_retention_count_event_bound_and_parameter_identity(self):
        now = [1000000.0]
        store = RunRepository(':memory:', clock=lambda: now[0])
        self.addCleanup(store.close)
        run = store.create('same', PAYLOAD)
        self.assertEqual(store.existing('same', PAYLOAD)['id'], run['id'])
        with self.assertRaisesRegex(RunError, 'different'):
            store.existing('same', PAYLOAD | {'question': 'evaluate_battery'})
        for _ in range(70):
            store.event(run['id'], {'kind': 'model_started', 'agent': 'Energy Analyst', 'elapsed_ms': 1})
        self.assertEqual(len(store.get(run['id'])['events']), 64)
        store.finish(run['id'], 'cancelled')
        store.event(run['id'], {'kind': 'analyst_verified', 'agent': 'Energy Analyst', 'elapsed_ms': 2})
        self.assertEqual(len(store.get(run['id'])['events']), 64)
        for n in range(110):
            now[0] += 1
            item = store.create(str(n), PAYLOAD)
            store.finish(item['id'], 'complete', result={})
        self.assertEqual(len(store.history()), 100)
        now[0] += 7 * 86400 + 1
        self.assertEqual(store.history(), [])


class RunServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repository = RunRepository(':memory:')

    async def asyncTearDown(self):
        self.repository.close()

    async def test_idempotent_start_failure_and_independent_retry(self):
        async def failing(provider, controls, question, publish):
            raise AnalysisError('rate_limit')
        service = RunService(self.repository, failing)
        first = service.start('same', PAYLOAD)
        self.assertEqual(service.start('same', PAYLOAD)['id'], first['id'])
        await service.wait()
        failed = self.repository.get(first['id'])
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('rate limit', failed['error'])
        self.assertIsNone(failed['result'])
        retry = service.start('next', PAYLOAD)
        self.assertNotEqual(retry['id'], first['id'])
        await service.close()

    async def test_cancel_keeps_capacity_until_worker_finishes_and_late_success_cannot_win(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(provider, controls, question, publish):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
            return {'late': True}
        service = RunService(self.repository, slow)
        run = service.start('first', PAYLOAD)
        await started.wait()
        service.cancel(run['id'])
        with self.assertRaisesRegex(RunError, 'active'):
            service.start('second', PAYLOAD)
        release.set()
        await service.wait()
        self.assertEqual(self.repository.get(run['id'])['status'], 'cancelled')
        self.assertIsNone(self.repository.get(run['id'])['result'])
        service.start('second', PAYLOAD)
        await service.close()
