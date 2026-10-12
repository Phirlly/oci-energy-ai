"""One admitted setup operation survives caller cancellation and persists before login."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from energy_ai.web.hosted_runtime import HostedRuntime
from energy_ai.web.setup_secrets import AlreadyConfigured, SettingsChanged, SetupError


class HostedSetup(HostedRuntime):
    def __init__(self, config, signer, settings):
        initial = settings.read().value
        super().__init__(config, signer, {'demo_password': ''})
        self.providers, self.models = [], {}
        self.settings = settings
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='oci-setup')
        self.pending = None
        self.closed = False
        self.settings_available = False
        if 'password' in initial:
            self._install(initial)

    @property
    def required(self):
        return not bool(self.password)

    def _install(self, value):
        self.keys.clear()
        self.keys.update(value['keys'])
        self.providers[:] = ['oci'] + [p for p in ('openai', 'anthropic') if p in self.keys]
        self.models.clear()
        self.models.update({p: self.config.models()[p] for p in self.providers})
        self.password = value['password']
        self.settings_available = value['version'] == 2

    async def _finish(self, operation, arguments):
        try:
            if self.closed:
                raise SetupError()
            future = asyncio.get_running_loop().run_in_executor(self.executor, operation, *arguments)
            value = await asyncio.shield(future)
        except (AlreadyConfigured, SettingsChanged) as error:
            if not self.closed:
                self._install(error.value)
            raise
        except SetupError:
            raise
        except Exception:
            raise SetupError() from None
        if self.closed:
            raise SetupError()
        self._install(value)

    def _finished(self, task):
        if not task.cancelled():
            task.exception()  # Consume even when a disconnected caller cannot observe the result.
        if self.pending is task:
            self.pending = None

    async def complete(self, code, password, keys):
        if not self.required:
            raise SetupError(409, 'Setup is already complete. Sign in with the demo password.')
        await self._submit(self.settings.complete, code, password, dict(keys))

    async def update_keys(self, code, changes):
        if not self.settings_available:
            raise SetupError(409, 'Owner settings are unavailable for this installation.')
        await self._submit(self.settings.update_keys, code, dict(changes))

    async def _submit(self, operation, *arguments):
        if self.closed:
            raise SetupError()
        if self.pending is not None:
            raise SetupError(409, 'A settings operation is in progress. Wait a moment before trying again.')
        self.pending = asyncio.create_task(self._finish(operation, arguments))
        self.pending.add_done_callback(self._finished)
        try:
            async with asyncio.timeout(90):
                await asyncio.shield(self.pending)
        except TimeoutError:
            raise SetupError() from None

    def close(self):
        if not self.closed:
            self.closed = True
            def finish():
                self.settings.close()
                super(HostedSetup, self).close()
            self.executor.submit(finish)
            self.executor.shutdown(wait=False)
