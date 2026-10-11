import asyncio
from pathlib import Path
import tempfile
import unittest
import sqlite3
import json

from energy_ai.agents.analysis import AnalysisError
from energy_ai.office.runs import RunError, RunRepository
from energy_ai.office.run_service import RunService
from energy_ai.office.sample import Controls

PAYLOAD = dict(provider='openai', model='fixture-model', controls=Controls().model_dump(), question='explain_bill')


class RunRepositoryTests(unittest.TestCase):
    def test_version_zero_history_is_adopted_and_versioned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.db'
            connection = sqlite3.connect(path)
            # Independent pre-versioning schema from a5e35cb; do not build with RunRepository.
            connection.execute('''CREATE TABLE office_runs (
                id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                created REAL NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
                events TEXT NOT NULL DEFAULT '[]', result TEXT, error TEXT)''')
            connection.executemany('INSERT INTO office_runs VALUES(?,?,?,?,?,?,?,?)', [
                ('finished', 'previous', 1000, json.dumps(PAYLOAD), 'complete', '[]', '{"value":"public"}', None),
                ('unfinished', 'pending', 1001, json.dumps(PAYLOAD), 'running', '[]', None, None)])
            connection.commit()
            connection.close()
            store = RunRepository(path, clock=lambda: 1002)
            try:
                self.assertEqual(store.get('finished')['result'], {'value': 'public'})
                self.assertEqual(store.get('unfinished')['status'], 'interrupted')
                self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0], 1)
            finally:
                store.close()

    def test_incompatible_schema_is_rejected_without_changing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            for mutation in ('PRAGMA user_version=2', 'ALTER TABLE office_runs ADD COLUMN future TEXT',
                             'CREATE TABLE unrelated (id TEXT)', 'PRAGMA user_version=-1'):
                with self.subTest(mutation=mutation):
                    path = Path(directory) / f'history-{len(list(Path(directory).iterdir()))}.db'
                    store = RunRepository(path)
                    store.create('unfinished', PAYLOAD)
                    store.close()
                    connection = sqlite3.connect(path)
                    connection.execute(mutation)
                    connection.commit()
                    connection.close()
                    before = path.read_bytes()
                    with self.assertRaisesRegex(RunError, 'schema'):
                        RunRepository(path)
                    self.assertEqual(path.read_bytes(), before)

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
