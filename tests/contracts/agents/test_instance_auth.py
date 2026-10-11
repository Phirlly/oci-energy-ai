import asyncio
import base64
import hashlib
import threading
import re
from types import SimpleNamespace
import unittest

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from oci.auth.signers.security_token_signer import X509FederationClientBasedSecurityTokenSigner

from energy_ai.agents.instance_auth import InstanceAuth


class InstanceSigningTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_signer_refreshes_token_and_key_and_signs_exact_body(self):
        keys = [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)]
        generation = [0]
        federation = SimpleNamespace(
            get_security_token=lambda: f'token-{generation[0]}',
            session_key_supplier=SimpleNamespace(get_key_pair=lambda: {'private': keys[generation[0]]}))
        signer = X509FederationClientBasedSecurityTokenSigner(federation)
        auth = InstanceAuth(signer)
        self.addCleanup(auth.close)
        sent = []
        def respond(request):
            sent.append(request)
            return httpx.Response(200)
        body = b'{"private":"text","amount":12}'
        async with httpx.AsyncClient(auth=auth, transport=httpx.MockTransport(respond)) as client:
            for generation[0] in range(2):
                await client.post('https://inference.example/responses', content=body,
                                  headers={'authorization': 'Bearer discarded', 'x-api-key': 'discarded',
                                           'content-type': 'application/json'})
        for index, request in enumerate(sent):
            self.assertIn(f'keyId="ST$token-{index}"', request.headers['authorization'])
            self.assertEqual(request.headers['x-content-sha256'], base64.b64encode(hashlib.sha256(body).digest()).decode())
            self.assertEqual(request.content, body)
            self.assertNotIn('x-api-key', request.headers)
            self.assertNotIn('discarded', str(request.headers))
            fields = dict(re.findall(r'([a-z]+)="([^"]+)"', request.headers['authorization']))
            signing_lines = [f'{name}: {request.method.lower()} {request.url.raw_path.decode()}'
                             if name == '(request-target)' else f'{name}: {request.headers[name]}'
                             for name in fields['headers'].split()]
            keys[index].public_key().verify(base64.b64decode(fields['signature']),
                '\n'.join(signing_lines).encode(), padding.PKCS1v15(), hashes.SHA256())
        self.assertIs(signer.private_key, keys[1])

    async def test_401_is_returned_without_authentication_replay(self):
        calls = []
        auth = InstanceAuth(lambda request: request)
        self.addCleanup(auth.close)
        def denied(request):
            calls.append(request)
            return httpx.Response(401)
        async with httpx.AsyncClient(auth=auth, transport=httpx.MockTransport(denied)) as client:
            response = await client.post('https://inference.example/responses', json={})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(calls), 1)


class SigningLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_retains_capacity_and_cleanup_waits_for_real_completion(self):
        entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def blocked(request):
            calls.append(request)
            entered.set()
            release.wait(2)
            raise RuntimeError('private SDK detail')
        auth = InstanceAuth(blocked, timeout=.1, cleanup=cleaned.set)
        client = httpx.AsyncClient(auth=auth, transport=httpx.MockTransport(lambda request: httpx.Response(200)))
        self.addAsyncCleanup(client.aclose)
        self.addCleanup(auth.close)
        first = asyncio.create_task(client.get('https://inference.example'))
        try:
            async with asyncio.timeout(1):
                while not entered.is_set():
                    await asyncio.sleep(.001)
            # The loop remains responsive while synchronous signing is blocked.
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            with self.assertRaisesRegex(httpx.RequestError, 'authentication') as error:
                await client.get('https://inference.example')
            self.assertNotIn('private SDK', str(error.exception))
            self.assertEqual(len(calls), 1)
            auth.close()
            self.assertFalse(cleaned.is_set())
            with self.assertRaises(httpx.RequestError):
                await client.get('https://inference.example')
        finally:
            release.set()
        async with asyncio.timeout(1):
            while not cleaned.is_set():
                await asyncio.sleep(.001)

    async def test_timeout_does_not_admit_more_work_until_worker_finishes(self):
        release, finished = threading.Event(), threading.Event()
        calls = []
        def sign(request):
            calls.append(request)
            if len(calls) == 1:
                release.wait(2)
                finished.set()
            return request
        auth = InstanceAuth(sign, timeout=.03)
        self.addCleanup(auth.close)
        async with httpx.AsyncClient(auth=auth, transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
            try:
                for _ in range(2):
                    with self.assertRaises(httpx.RequestError):
                        await client.get('https://inference.example')
                self.assertEqual(len(calls), 1)
            finally:
                release.set()
            async with asyncio.timeout(1):
                while not finished.is_set():
                    await asyncio.sleep(.001)
            self.assertEqual((await client.get('https://inference.example')).status_code, 200)
        self.assertEqual(len(calls), 2)
