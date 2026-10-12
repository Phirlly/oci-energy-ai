import { test, expect } from '@playwright/test';

const origin = 'http://127.0.0.1:8768';
const setupCode = 'invented-setup-code-32-characters';

test('operator claims setup, chooses admin and optional provider, then signs in on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(origin);
  await expect(page.getByRole('heading', { name: 'Set up your demo' })).toBeVisible();
  await page.getByLabel('Owner code', { exact: true }).fill('incorrect-code');
  await page.getByLabel('Demo password', { exact: true }).fill('admin');
  await page.getByLabel('OpenAI API key (optional)', { exact: true }).fill('invented-browser-key');
  await page.getByRole('button', { name: 'Save setup' }).click();
  await expect(page.getByRole('alert')).toContainText('Incorrect setup code');
  await page.getByLabel('Owner code', { exact: true }).fill(setupCode);
  await page.getByRole('button', { name: 'Save setup' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('status')).toContainText('Setup complete');
  await expect(page.getByLabel('Owner code', { exact: true })).toHaveCount(0);
  await page.getByLabel('Launch code').fill('admin');
  await page.getByRole('button', { name: 'Start session' }).click();
  await expect(page.getByRole('heading', { name: 'Your electricity, understood.' })).toBeVisible();
  await expect(page.getByLabel('Office AI provider').locator('option')).toHaveText(['oci', 'openai']);
  await page.getByLabel('Office AI provider').selectOption('openai');
  await expect(page.getByText('Configured model: public-model-fixture.', { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Your electricity, understood.' })).toBeVisible();
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByLabel('Launch code')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Set up your demo' })).toHaveCount(0);
});

test('startup status failure is visible and can be retried before login', async ({ page }) => {
  let failed = true;
  await page.route('**/api/setup', route => failed ? route.abort() : route.fulfill({ json: { required: false } }));
  await page.goto(origin);
  await expect(page.getByRole('alert')).toContainText('Could not check demo setup');
  await expect(page.getByLabel('Launch code')).toHaveCount(0);
  failed = false;
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByLabel('Launch code')).toBeVisible();
});

test('failed setup remains editable without exposing submitted secrets', async ({ page }) => {
  await page.route('**/api/setup', route => route.request().method() === 'GET'
    ? route.fulfill({ json: { required: true } })
    : route.fulfill({ status: 503, json: { detail: 'Setup could not be verified. Wait a moment and try again.' } }));
  await page.goto(origin);
  await page.getByLabel('Owner code', { exact: true }).fill(setupCode);
  await page.getByLabel('Demo password', { exact: true }).fill('private-password-marker');
  await page.getByRole('button', { name: 'Save setup' }).click();
  await expect(page.getByRole('alert')).toContainText('Setup could not be verified');
  await expect(page.getByRole('button', { name: 'Save setup' })).toBeEnabled();
  await expect(page.getByRole('alert')).not.toContainText('private-password-marker');
  expect(new URL(page.url()).search).toBe('');
});

test('setup preserves a printable Unicode password within the server character limit', async ({ page }) => {
  const password = '🔋'.repeat(150);
  let submitted;
  await page.route('**/api/setup', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: { required: true } });
    submitted = route.request().postDataJSON();
    return route.fulfill({ json: { required: false } });
  });
  await page.goto(origin);
  await page.getByLabel('Owner code', { exact: true }).fill(setupCode);
  await page.getByLabel('Demo password', { exact: true }).fill(password);
  await expect(page.getByLabel('Demo password', { exact: true })).toHaveValue(password);
  await page.getByRole('button', { name: 'Save setup' }).click();
  await expect(page.getByRole('status')).toContainText('Setup complete');
  expect(submitted.password).toBe(password);
});
