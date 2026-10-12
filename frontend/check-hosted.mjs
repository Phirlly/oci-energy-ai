// Opt-in hosted acceptance. Never use the Playwright reporter with live credentials.
for (const name of ['DEBUG', 'PWDEBUG', 'DEBUG_FILE']) delete process.env[name];

const requestOptions = { timeout: 10000, maxRedirects: 0, maxRetries: 0 };
let stage = 'configuration', browser, context, timer, cleanupFailed = false;
let origin, localTest, release;
const requireThat = value => { if (!value) throw new Error(); };

async function officeJourney(page, expect) {
  await expect(page.getByTestId('office-total')).toHaveText('$6,710.80');
  const [download] = await Promise.all([page.waitForEvent('download'),
    page.getByRole('link', { name: 'Download illustrative bill' }).click()]);
  requireThat(download.suggestedFilename() === 'illustrative-office-bill.pdf');
  const stream = await download.createReadStream();
  requireThat(stream);
  let length = 0, prefix = Buffer.alloc(0);
  for await (const chunk of stream) {
    length += chunk.length;
    requireThat(length <= 4 * 1024 * 1024);
    if (prefix.length < 4) prefix = Buffer.concat([prefix, chunk]).subarray(0, 4);
  }
  requireThat(prefix.toString('ascii') === '%PDF');
  await page.getByRole('button', { name: 'Calculate scenario' }).click();
  await expect(page.getByTestId('office-difference')).toHaveText('$366.69');
  await page.getByLabel('Power (kW)', { exact: true }).fill('0');
  await page.getByRole('button', { name: 'Calculate scenario' }).click();
  await expect(page.getByTestId('office-difference')).toHaveText('$0.00');
  await page.getByRole('button', { name: 'Reset scenario' }).click();
  await expect(page.getByLabel('Power (kW)', { exact: true })).toHaveValue('25');
}

async function billJourney(page, expect) {
  await page.getByRole('button', { name: 'Review your bills', exact: true }).click();
  await page.getByRole('button', { name: 'Try the example' }).click();
  await expect(page.getByLabel('Consumption', { exact: true })).toHaveValue('580');
  await expect(page.getByText('FICTIONAL DEMO - Juniper Power', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Calculate insights' })).toBeDisabled();
  await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByTestId('daily-usage')).toHaveText('20.00 kWh/day');
  await page.getByLabel('Consumption', { exact: true }).fill('870');
  await expect(page.getByRole('button', { name: 'Approve reviewed facts' })).toBeDisabled();
  await page.getByRole('button', { name: 'Save corrections' }).click();
  await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByTestId('daily-usage')).toHaveText('30.00 kWh/day');
  await page.setViewportSize({ width: 390, height: 844 });
  requireThat(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByRole('button', { name: 'Office demo', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'A month in the office.' })).toBeVisible();
  requireThat(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByRole('button', { name: 'Review your bills', exact: true }).click();
  await expect(page.getByLabel('Consumption', { exact: true })).toHaveValue('870');
  await page.getByRole('button', { name: 'Delete bill' }).click();
  await expect(page.getByLabel('Consumption', { exact: true })).toHaveCount(0);
}

async function journey(chromium, expect, rejectPolicy) {
  stage = 'browser';
  // Chromium does not need the presenter password or cloud/provider credentials.
  const env = Object.fromEntries(['PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'SystemRoot', 'DISPLAY', 'XAUTHORITY']
    .filter(name => process.env[name] !== undefined).map(name => [name, process.env[name]]));
  browser = await chromium.launch({ env, timeout: 15000 });
  context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 900 } });
  context.setDefaultTimeout(15000);
  await context.route('**/*', async route => {
    let response;
    try {
      const request = route.request(), url = new URL(request.url());
      requireThat(url.origin === origin && !url.username && !url.password);
      requireThat(!(request.method() === 'POST' &&
        (url.pathname === '/api/office/runs' || /^\/api\/documents\/[^/]+\/extract\/?$/.test(url.pathname))));
      response = await route.fetch(requestOptions);
      requireThat(response.status() < 300 || response.status() >= 400);
      await route.fulfill({ response });
    } catch {
      stage = 'request-policy';
      rejectPolicy(new Error());
      await route.abort().catch(() => {});
    } finally { if (response) await response.dispose().catch(() => {}); }
  });
  if (!localTest) {
    stage = 'health';
    const response = await context.request.get(origin + '/healthz', requestOptions);
    try {
      requireThat(response.status() === 200);
      const value = await response.json();
      requireThat(value.status === 'ready' && value.release === release && value.schema === 1);
    } finally { await response.dispose(); }
  }
  stage = 'login';
  const page = await context.newPage();
  await page.goto(origin);
  await page.getByLabel(/^(Demo password|Launch code)$/).fill(process.env.DEMO_PASSWORD);
  const [login] = await Promise.all([
    page.waitForResponse(response => response.url() === origin + '/api/session' && response.request().method() === 'POST'),
    page.getByRole('button', { name: /^(Sign in|Start session)$/ }).click()]);
  requireThat(login.status() === 200);
  await expect(page.getByRole('heading', { name: 'A month in the office.' })).toBeVisible();
  const cookies = (await context.cookies(origin + '/api/session')).filter(cookie => cookie.name === 'energy_session');
  requireThat(cookies.length === 1 && cookies[0].httpOnly && cookies[0].sameSite === 'Strict' &&
    cookies[0].path === '/api' && (localTest || cookies[0].secure));
  stage = 'office'; await officeJourney(page, expect);
  stage = 'bill-review'; await billJourney(page, expect);
  stage = 'logout';
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByLabel(/^(Demo password|Launch code)$/)).toBeVisible();
  const response = await context.request.get(origin + '/api/session', requestOptions);
  try { requireThat(response.status() === 401); } finally { await response.dispose(); }
}

let passed = false;
try {
  const args = process.argv.slice(2);
  requireThat(args.length === 0 || (args.length === 1 && args[0] === '--local-test'));
  localTest = args.length === 1;
  origin = process.env.ENERGY_DEMO_ORIGIN;
  release = process.env.ENERGY_DEMO_RELEASE;
  const parsed = new URL(origin);
  requireThat(origin === parsed.origin && !parsed.username && !parsed.password);
  requireThat(localTest ? /^http:\/\/127\.0\.0\.1:[1-9][0-9]*$/.test(origin) :
    /^https:\/\/[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/.test(origin));
  requireThat(/^[a-f0-9]{40}$/.test(release) && typeof process.env.DEMO_PASSWORD === 'string' && process.env.DEMO_PASSWORD.length > 0);
  const { chromium, expect } = await import('@playwright/test');
  let rejectPolicy;
  const policy = new Promise((_, reject) => { rejectPolicy = reject; });
  const deadline = new Promise((_, reject) => { timer = setTimeout(() => { stage = 'timeout'; reject(new Error()); }, 180000); });
  await Promise.race([journey(chromium, expect, rejectPolicy), policy, deadline]);
  passed = true;
} catch { /* Raw errors can contain credentials, response text or page snapshots. */ }
finally {
  clearTimeout(timer);
  // Playwright close() has no timeout. Its process-exit handler kills the owned
  // browser and removes temporary directories if graceful cleanup cannot finish.
  const cleanupTimer = setTimeout(() => {
    console.error('browser: failed at cleanup'); process.exit(1);
  }, 25000);
  if (context) {
    try {
      const response = await context.request.delete(origin + '/api/session', {
        ...requestOptions, headers: { Origin: origin, 'x-energy-action': '1' }
      });
      try { requireThat(response.status() === 200); } finally { await response.dispose(); }
    } catch { cleanupFailed = true; }
    await context.close().catch(() => { cleanupFailed = true; });
  }
  if (browser) await browser.close().catch(() => { cleanupFailed = true; });
  clearTimeout(cleanupTimer);
}
if (passed && !cleanupFailed) console.log(`browser: passed (${localTest ? 'local-test' : 'hosted'})`);
else { console.error(`browser: failed at ${cleanupFailed ? 'cleanup' : stage}`); process.exitCode = 1; }
