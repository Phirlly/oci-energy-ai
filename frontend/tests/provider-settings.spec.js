import { test, expect } from '@playwright/test';

const origin = 'http://127.0.0.1:8769';
const owner = 'invented-setup-code-32-characters';
const headers = { Origin: origin, 'x-energy-action': '1' };

test.beforeEach(async ({ page }) => {
  await page.request.post(origin + '/api/session', { headers, data: { code: 'admin' } });
  const reset = await page.request.post(origin + '/api/settings', { headers,
    data: { owner_code: owner, changes: { openai: 'invented-key', anthropic: null } } });
  expect(reset.ok()).toBe(true);
  await page.goto(origin);
});

test('owner keeps, replaces and removes keys without losing bills or stale provider consent', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel('Office AI provider').selectOption('openai');
  await page.getByLabel('Send the public office sample', { exact: false }).check();
  await page.getByRole('button', { name: 'Review your bills', exact: true }).click();
  await page.getByRole('button', { name: 'Try the example', exact: true }).click();
  await page.getByRole('combobox', { name: 'AI provider', exact: true }).selectOption('openai');
  await page.getByLabel('Send this bill’s extracted text', { exact: false }).check();
  const supplier = await page.getByLabel('Supplier', { exact: true }).inputValue();
  await page.getByRole('button', { name: 'Owner settings', exact: true }).click();
  await expect(page.getByText('Saving does not test provider access.', { exact: false })).toBeVisible();
  await page.getByLabel('Owner code', { exact: true }).fill(owner);
  await page.getByLabel('Anthropic key action').selectOption('replace');
  await page.getByLabel('New Anthropic API key').fill('invented-new-key');
  await page.getByLabel('OpenAI key action').selectOption('remove');
  await page.getByRole('button', { name: 'Save provider keys', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('status')).toContainText('Provider keys saved');
  await expect(page.getByLabel('Owner code', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('New Anthropic API key')).toHaveCount(0);
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Office demo', exact: true }).click();
  await expect(page.getByLabel('Office AI provider')).toHaveValue('oci');
  await expect(page.getByLabel('Office AI provider').locator('option')).toHaveText(['oci', 'anthropic']);
  await expect(page.getByLabel('Send the public office sample', { exact: false })).not.toBeChecked();
  await expect(page.getByRole('button', { name: 'Run analysts', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Review your bills', exact: true }).click();
  await expect(page.getByLabel('Supplier', { exact: true })).toHaveValue(supplier);
  await expect(page.getByRole('combobox', { name: 'AI provider', exact: true })).toHaveValue('oci');
  await expect(page.getByLabel('Send this bill’s extracted text', { exact: false })).not.toBeChecked();
  await page.reload();
  await expect(page.getByLabel('Office AI provider').locator('option')).toHaveText(['oci', 'anthropic']);
});

test('wrong owner cannot save and session expiry removes entered credentials', async ({ page }) => {
  await page.getByRole('button', { name: 'Owner settings', exact: true }).click();
  await page.getByLabel('Owner code', { exact: true }).fill('wrong-private-marker');
  await page.getByLabel('OpenAI key action').selectOption('replace');
  await page.getByLabel('New OpenAI API key').fill('private-api-marker');
  await page.getByRole('button', { name: 'Save provider keys', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Incorrect owner code');
  await expect(page.getByRole('alert')).not.toContainText('private');
  await page.request.delete(origin + '/api/session', { headers });
  await page.getByRole('button', { name: 'Save provider keys', exact: true }).click();
  await expect(page.getByLabel('Launch code')).toBeVisible();
  await expect(page.getByLabel('Owner code', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('New OpenAI API key')).toHaveCount(0);
});

test('a delayed session poll cannot overwrite the providers confirmed after saving', async ({ page }) => {
  await expect(page.getByRole('heading', { name: 'Your electricity, understood.' })).toBeVisible();
  let release, captured;
  const held = new Promise(resolve => { captured = resolve; });
  let first = true;
  await page.route('**/api/session', async route => {
    if (!first || route.request().method() !== 'GET') return route.continue();
    first = false;
    const response = await route.fetch();
    await new Promise(resolve => { release = resolve; captured(); });
    await route.fulfill({ response });
  });
  await held; // The real 15-second session poll is now held with the old providers.
  await page.getByRole('button', { name: 'Owner settings', exact: true }).click();
  await page.getByLabel('Owner code', { exact: true }).fill(owner);
  await page.getByLabel('Anthropic key action').selectOption('replace');
  await page.getByLabel('New Anthropic API key').fill('invented-new-key');
  await page.getByLabel('OpenAI key action').selectOption('remove');
  await page.getByRole('button', { name: 'Save provider keys', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Provider keys saved');
  await page.getByRole('button', { name: 'Office demo', exact: true }).click();
  await page.getByLabel('Office AI provider').selectOption('anthropic');
  await page.getByLabel('Send the public office sample', { exact: false }).check();
  const oldResponse = page.waitForResponse(response => response.url().endsWith('/api/session'));
  release();
  await (await oldResponse).finished();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.getByLabel('Office AI provider').locator('option')).toHaveText(['oci', 'anthropic']);
  await expect(page.getByLabel('Office AI provider')).toHaveValue('anthropic');
  await expect(page.getByLabel('Send the public office sample', { exact: false })).toBeChecked();
});
