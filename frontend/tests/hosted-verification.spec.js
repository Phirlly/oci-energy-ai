import { test, expect } from '@playwright/test';
import { execFile } from 'node:child_process';
import { createServer } from 'node:http';
import { promisify } from 'node:util';

const execute = promisify(execFile);
// Share the isolated bill fixture server, leaving the plain app's ten-login
// window for its existing public journeys. No extraction is started here.
const upstream = 'http://127.0.0.1:8766';

async function checker(origin, password = 'admin', args = ['--local-test']) {
  try {
    const result = await execute(process.execPath, ['check-hosted.mjs', ...args], {
      cwd: process.cwd(), timeout: 45000, maxBuffer: 16384,
      env: { PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR,
        ENERGY_DEMO_ORIGIN: origin, ENERGY_DEMO_RELEASE: 'a'.repeat(40), DEMO_PASSWORD: password,
        DEBUG: 'pw:api', PWDEBUG: '1' }
    });
    return { ...result, code: 0 };
  } catch (error) {
    return { stdout: error.stdout, stderr: error.stderr, code: error.code };
  }
}

// A bounded loopback proxy drives real browser failures without live credentials.
async function withProxy(intercept, action) {
  const requests = [];
  const server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    requests.push({ method: request.method, path: request.url });
    if (await intercept(request, response)) return;
    try {
      const headers = { ...request.headers, host: new URL(upstream).host, origin: upstream };
      delete headers['content-length']; delete headers['accept-encoding'];
      const result = await fetch(upstream + request.url, { method: request.method, headers,
        body: chunks.length ? Buffer.concat(chunks) : undefined, redirect: 'manual',
        signal: AbortSignal.timeout(10000) });
      response.writeHead(result.status, Object.fromEntries([...result.headers].filter(([name]) =>
        !['content-encoding', 'content-length', 'transfer-encoding'].includes(name))));
      response.end(Buffer.from(await result.arrayBuffer()));
    } catch { response.writeHead(502); response.end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try { await action(`http://127.0.0.1:${server.address().port}`, requests); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

test('standalone checker completes office, PDF, bill review, mobile and logout journeys', async () => {
  const result = await checker(upstream);
  expect(result).toEqual({ code: 0, stdout: 'browser: passed (local-test)\n', stderr: '' });
});

test('wrong password is redacted and cleanup is attempted after rejected login', async () => {
  await withProxy(async () => false, async (origin, requests) => {
    const result = await checker(origin, 'private-password-marker');
    expect(result.code).toBe(1);
    expect(result.stdout).toBe('');
    expect(result.stderr).toBe('browser: failed at login\n');
    expect(requests).toContainEqual({ method: 'DELETE', path: '/api/session' });
    expect(result.stderr).not.toContain('private-password-marker');
  });
});

test('unsupported origins are rejected before starting a browser or sending credentials', async () => {
  for (const [origin, args] of [[upstream, []], ['https://user@example.com', []],
    ['https://example.com/path', []], ['http://localhost:8766', ['--local-test']],
    ['https://example.com', ['--unknown']]]) {
    expect(await checker(origin, 'private-password-marker', args)).toEqual({
      code: 1, stdout: '', stderr: 'browser: failed at configuration\n'
    });
  }
});

test('unresponsive server cleanup is bounded and reported without response details', async () => {
  await withProxy(async request => request.method === 'DELETE', async (origin, requests) => {
    const result = await checker(origin, 'private-password-marker');
    expect(result).toEqual({ code: 1, stdout: '', stderr: 'browser: failed at cleanup\n' });
    expect(requests).toContainEqual({ method: 'DELETE', path: '/api/session' });
  });
});

test('navigation, login and cleanup redirects are not followed, including direct cleanup requests', async () => {
  for (const [method, path] of [['GET', '/'], ['POST', '/api/session'], ['DELETE', '/api/session']]) {
    await withProxy(async (request, response) => {
      if (request.url !== path || request.method !== method) return false;
      response.writeHead(307, { Location: '/unexpected-private-marker' }); response.end(); return true;
    }, async (origin, requests) => {
      const result = await checker(origin);
      expect(result.code).toBe(1);
      expect(result.stderr).toMatch(/^browser: failed at (request-policy|cleanup)\n$/);
      expect(requests.some(request => request.path === '/unexpected-private-marker')).toBe(false);
      expect(requests).toContainEqual({ method: 'DELETE', path: '/api/session' });
    });
  }
});

test('model requests and requests outside the selected origin never reach their destination', async () => {
  await withProxy(async (_, response) => { response.writeHead(200); response.end(); return true; },
    async (destination, received) => {
      for (const path of ['/api/office/runs', '/api/documents/fixture/extract', destination + '/private-marker']) {
        await withProxy(async (request, response) => {
          if (request.url !== '/') return false;
          response.writeHead(200, { 'Content-Type': 'text/html' });
          response.end(`<script>fetch(${JSON.stringify(path)}, {method:'POST'}).catch(()=>{})</script>`);
          return true;
        }, async (origin, requests) => {
          const result = await checker(origin);
          expect(result.code).toBe(1);
          expect(result.stderr).toBe('browser: failed at request-policy\n');
          expect(requests.some(request => request.method === 'POST')).toBe(false);
        });
      }
      expect(received).toEqual([]);
    });
});
