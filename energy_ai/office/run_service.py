"""Own one bounded office execution, cancellation and conditional completion."""

import asyncio

from energy_ai.agents.analysis import AnalysisError
from energy_ai.office.runs import RunError
from energy_ai.office.sample import Controls


class RunService:
    def __init__(self, repository, analyze):
        self.repository, self.analyze = repository, analyze
        self.task, self.run_id = None, None

    def start(self, key, payload):
        existing = self.repository.existing(key, payload)
        if existing:
            return existing
        if self.task and not self.task.done():
            raise RunError('An office analysis is still active. Wait or cancel it before starting another.')
        run = self.repository.create(key, payload)
        self.run_id = run['id']
        self.task = asyncio.create_task(self.execute(run))
        return run

    async def execute(self, run):
        try:
            result = await self.analyze(run['provider'], Controls(**run['controls']), run['question'],
                                        lambda event: self.repository.event(run['id'], event))
            self.repository.finish(run['id'], 'complete', result=result)
        except asyncio.CancelledError:
            self.repository.finish(run['id'], 'cancelled')
            raise
        except AnalysisError as error:
            self.repository.finish(run['id'], 'failed', error=str(error))
        except Exception:
            self.repository.finish(run['id'], 'failed', error='Office analysis failed; raw details suppressed.')

    def cancel(self, run_id):
        run = self.repository.get(run_id)
        if run['status'] == 'running':
            self.repository.finish(run_id, 'cancelled')
            if self.run_id == run_id and self.task and not self.task.done():
                self.task.cancel()
        return self.repository.get(run_id)

    async def wait(self):
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)

    async def close(self):
        if self.task and not self.task.done():
            self.cancel(self.run_id)
        await self.wait()
