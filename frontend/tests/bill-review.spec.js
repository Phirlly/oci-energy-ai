import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

test.afterEach(async ({ page, baseURL }) => {
  const response = await page.request.delete(`${baseURL}/api/session`, {
    headers: { Origin: new URL(baseURL).origin, 'x-energy-action': '1' }
  });
  expect(response.ok()).toBe(true);
});

test('unsaved corrections protect intake and keyboard can save them', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: 'Try the example' }).click();
  await page.getByLabel('Consumption', { exact: true }).fill('700');
  await expect(page.getByRole('button', { name: 'Try the example' })).toBeDisabled();
  await expect(page.getByLabel('Upload bill PDFs')).toBeDisabled();
  const save = page.getByRole('button', { name: 'Save corrections' });
  await save.focus();
  await expect(save).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Consumption', { exact: true })).toHaveValue('700');
  await expect(page.getByRole('button', { name: 'Approve reviewed facts' })).toBeEnabled();
});

test('selection cannot change during an outstanding calculation', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: 'Try the example' }).click();
  await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
  let release;
  const hold = new Promise(resolve => { release = resolve; });
  await page.route('**/api/insights', async route => { await hold; await route.continue(); });
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByLabel('Include bill 1 in insights')).toBeDisabled();
  release();
  await expect(page.getByTestId('daily-usage')).toBeVisible();
});

test('late heartbeat cannot restore a signed-out session', async ({ page }) => {
  await page.clock.install();
  await login(page);
  let release, intercepted;
  const hold = new Promise(resolve => { release = resolve; });
  const ready = new Promise(resolve => { intercepted = resolve; });
  await page.route('**/api/session', async route => {
    if (route.request().method() === 'GET') {
      const response = await route.fetch();
      intercepted(); await hold; await route.fulfill({ response });
    } else await route.continue();
  });
  await page.clock.fastForward(16000);
  await ready;
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByLabel('Launch code')).toBeVisible();
  const delivered = page.waitForResponse(response => response.url().endsWith('/api/session') && response.request().method() === 'GET');
  release();
  await delivered;
  await expect(page.getByLabel('Launch code')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign out' })).toHaveCount(0);
});

test.describe('scripted provider browser contract', () => {
  test.use({ baseURL: 'http://127.0.0.1:8766' });
  test('proposal shows evidence and provider changes require renewed consent', async ({ page }) => {
    await login(page);
    await page.getByRole('button', { name: 'Try the example' }).click();
    await expect(page.locator('.ai-panel').getByText('Model: gpt-4.1-mini-2025-04-14', { exact: false })).toBeVisible();
    const consent = page.getByLabel('Send this bill’s extracted text', { exact: false });
    await consent.check();
    await page.locator('.ai-panel').getByLabel('AI provider').selectOption('anthropic');
    await expect(consent).not.toBeChecked();
    await consent.check();
    await page.getByRole('button', { name: 'Extract with AI' }).click();
    await expect(page.getByText('Proposal ready', { exact: false })).toBeVisible();
    await expect(page.getByText('Source · page 1', { exact: false }).first()).toBeVisible();
    await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
    await page.getByRole('button', { name: 'Calculate insights' }).click();
    await expect(page.getByTestId('daily-usage')).toHaveText('20.00 kWh/day');
    const included = page.getByLabel('Include bill 1 in insights');
    await expect(included).toBeChecked();
    await page.getByRole('button', { name: 'Extract with AI' }).click();
    await expect(page.getByRole('button', { name: 'Cancel extraction' })).toBeVisible();
    await expect(page.getByText('Proposal ready', { exact: false })).toBeVisible();
    await expect(included).not.toBeChecked();
    await expect(included).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Calculate insights' })).toBeDisabled();
    await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
    await expect(included).toBeChecked();
    await expect(page.getByRole('button', { name: 'Calculate insights' })).toBeEnabled();
  });
  test('cancelled extraction allows manual corrections', async ({ page }) => {
    await login(page);
    await page.getByRole('button', { name: 'Try the example' }).click();
    await page.getByLabel('Send this bill’s extracted text', { exact: false }).check();
    await page.getByRole('button', { name: 'Extract with AI' }).click();
    await page.getByRole('button', { name: 'Cancel extraction' }).click();
    await page.getByLabel('Consumption', { exact: true }).fill('725');
    await page.getByRole('button', { name: 'Save corrections' }).click();
    await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
    await page.getByRole('button', { name: 'Calculate insights' }).click();
    await expect(page.getByTestId('daily-usage')).toHaveText('25.00 kWh/day');
  });
});


async function login(page) {
  await page.goto('/');
  await page.getByLabel('Launch code').fill('admin');
  await page.getByRole('button', { name: 'Start session' }).click();
  await expect(page.getByRole('heading', { name: 'Your electricity, understood.' })).toBeVisible();
  await page.getByRole('button', { name: 'Review your bills', exact: true }).click();
}

test('prepared example can be corrected, approved, compared and deleted', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: 'Try the example' }).click();
  await expect(page.getByLabel('Consumption', { exact: true })).toHaveValue('580');
  await expect(page.getByText('FICTIONAL DEMO - Juniper Power', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByTestId('daily-usage')).toHaveText('20.00 kWh/day');
  await expect(page.getByRole('heading', { name: 'Supplied-period insights' })).toBeFocused();
  await page.getByLabel('Consumption', { exact: true }).fill('870');
  await expect(page.getByTestId('daily-usage')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Approve reviewed facts' })).toBeDisabled();
  await page.getByRole('button', { name: 'Save corrections' }).click();
  await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByTestId('daily-usage')).toHaveText('30.00 kWh/day');
  await page.getByRole('button', { name: 'Delete bill' }).click();
  await expect(page.getByLabel('Consumption', { exact: true })).toHaveCount(0);
});

test('real PDF upload accepts another layout and manual review remains available without keys', async ({ page }) => {
  await login(page);
  const bytes = execFileSync('.venv/bin/python', ['-c',
    'import sys; from tests.fixtures.bills import pdf_bytes; sys.stdout.buffer.write(pdf_bytes("A different fictional layout / Electricity 2024-06-01 to 2024-07-01 / 30 days / 300 kWh / USD 60"))'],
    { cwd: process.cwd() + '/..' , encoding: null });
  await page.getByLabel('Upload bill PDFs').setInputFiles({ name: 'fictional.pdf', mimeType: 'application/pdf', buffer: bytes });
  await expect(page.getByText('AI is not configured', { exact: false })).toBeVisible();
  await page.getByLabel('Service type').selectOption('electricity');
  await page.getByLabel('Usage meaning').selectOption('consumption');
  await page.getByLabel('Usage unit').fill('kWh');
  await page.getByLabel('Start date').fill('2024-06-01');
  await page.getByLabel('End date').fill('2024-07-01');
  await page.getByLabel('Billed days').fill('30');
  await page.getByLabel('Consumption', { exact: true }).fill('300');
  await page.getByLabel('Current electricity charges').fill('60');
  await page.getByLabel('Currency').fill('USD');
  await page.getByRole('button', { name: 'Save corrections' }).click();
  await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByTestId('daily-usage')).toHaveText('10.00 kWh/day');
});

test('malformed upload reports a recoverable error and mobile controls fit', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByLabel('Upload bill PDFs').setInputFiles({
    name: 'invalid.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a pdf')
  });
  await expect(page.getByRole('alert')).toContainText('unencrypted text PDF');
  await page.getByRole('button', { name: 'Try the example' }).click();
  await expect(page.getByLabel('Supplier')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByLabel('Launch code')).toBeVisible();
});

for (const sample of [
  { unit: 'MWh', quantity: '2', service: 'electricity' },
  { unit: 'gallons', quantity: '4200', service: 'water' }
]) {
  test(`review preserves ${sample.unit} quantities without labeling them kWh`, async ({ page }) => {
    await login(page);
    const text = `FICTIONAL DEMO / Unit sample / ${sample.service} consumption ${sample.quantity} ${sample.unit}`;
    const bytes = execFileSync('.venv/bin/python', ['-c',
      'import sys; from tests.fixtures.bills import pdf_bytes; sys.stdout.buffer.write(pdf_bytes(sys.argv[1]))', text],
      { cwd: process.cwd() + '/..', encoding: null });
    await page.getByLabel('Upload bill PDFs').setInputFiles({
      name: 'fictional-unit.pdf', mimeType: 'application/pdf', buffer: bytes
    });
    const consumption = page.getByLabel('Consumption', { exact: true });
    await consumption.fill(sample.quantity);
    await page.getByLabel('Usage unit').fill(sample.unit);
    await page.getByLabel('Service type').selectOption(sample.service);
    await page.getByLabel('Usage meaning').selectOption('consumption');
    await page.getByRole('button', { name: 'Save corrections' }).click();
    await expect(page.getByRole('button', { name: 'Approve reviewed facts' })).toBeEnabled();
    await page.reload();
    await page.getByRole('button', { name: 'Review your bills', exact: true }).click();
    await page.locator('.bill-row').getByRole('button').click();
    await expect(consumption).toHaveValue(sample.quantity);
    await expect(page.getByLabel('Usage unit')).toHaveValue(sample.unit);
    await expect(page.getByLabel('Service type')).toHaveValue(sample.service);
    await expect(page.getByLabel('Consumption (kWh)', { exact: true })).toHaveCount(0);
  });
}
