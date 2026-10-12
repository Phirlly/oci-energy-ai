"""Refresh native OCI instance credentials without blocking the serving event loop."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import httpx
import requests
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner


class CoordinatedInstanceSigner(InstancePrincipalsSecurityTokenSigner):
    """Keep token/key reset, signing and forced refresh atomic across SDK users."""

    def __init__(self, **kwargs):
        self._signing_guard = threading.RLock()
        super().__init__(**kwargs)

    def __call__(self, request, enforce_content_headers=True):
        with self._signing_guard:
            return super().__call__(request, enforce_content_headers)

    def refresh_security_token(self):
        with self._signing_guard:
            return super().refresh_security_token()


class InstanceAuth(httpx.Auth):
    def __init__(self, signer, *, timeout=30, cleanup=lambda: None):
        self.signer = signer
        self.timeout = timeout
        self.cleanup = cleanup
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='oci-signing')
        self.capacity = asyncio.Semaphore(1)
        self.pending = None
        self.closed = False

    def _sign(self, method, url, headers, body):
        prepared = requests.Request(method, url, headers=headers, data=body).prepare()
        self.signer(prepared)  # __call__ refreshes both security token and signing key.
        return dict(prepared.headers)

    def _finished(self, future):
        if not future.cancelled():
            future.exception()  # Consume failures even when the caller has left.
        self.pending = None
        self.capacity.release()

    async def async_auth_flow(self, request):
        try:
            async with asyncio.timeout(self.timeout):
                if self.closed:
                    raise RuntimeError()
                await request.aread()
                await self.capacity.acquire()
                if self.closed:
                    self.capacity.release()
                    raise RuntimeError()
                headers = dict(request.headers)
                for name in ('authorization', 'x-api-key', 'x-goog-api-key'):
                    headers.pop(name, None)
                try:
                    self.pending = asyncio.get_running_loop().run_in_executor(
                        self.executor, self._sign, request.method, str(request.url), headers, request.content)
                except Exception:
                    self.capacity.release()
                    raise
                self.pending.add_done_callback(self._finished)
                signed = await asyncio.shield(self.pending)
            request.headers.clear()
            request.headers.update(signed)
        except Exception:
            raise httpx.RequestError('OCI instance authentication unavailable.', request=request) from None
        yield request  # No replay, including on HTTP401.

    def sync_auth_flow(self, request):
        raise RuntimeError('Instance authentication requires an asynchronous client.')

    def close(self):
        if not self.closed:
            self.closed = True
            # One finalizer, ordered after any active call; never close its sessions early.
            self.executor.submit(self.cleanup)
            self.executor.shutdown(wait=False)
