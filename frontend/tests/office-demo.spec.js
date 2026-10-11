import { test, expect } from '@playwright/test';

test.use({ baseURL: 'http://127.0.0.1:8767' });
test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Launch code').fill('admin');
  await page.getByRole('button', { name: 'Start session' }).click();
  await expect(page.getByRole('heading', { name: 'A month in the office.' })).toBeVisible();
});
test.afterEach(async ({ page, baseURL }) => {
  await page.request.delete(`${baseURL}/api/session`, {
    headers: { Origin: baseURL, 'x-energy-action': '1' }
  });
});

test('prepared month reconciles, downloads a bill and recalculates battery choices', async ({ page }) => {
  await expect(page.getByTestId('office-total')).toHaveText('$6,710.80');
  await expect(page.getByText('ComStock', { exact: false }).first()).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download illustrative bill' }).click();
  expect((await download).suggestedFilename()).toBe('illustrative-office-bill.pdf');
  await page.getByRole('button', { name: 'Calculate scenario' }).click();
  await expect(page.getByTestId('office-difference')).toHaveText('$366.69');
  await page.getByLabel('Power (kW)', { exact: true }).fill('0');
  await expect(page.getByTestId('office-difference')).toHaveCount(0);
  await page.getByRole('button', { name: 'Calculate scenario' }).click();
  await expect(page.getByTestId('office-difference')).toHaveText('$0.00');
  await expect(page.getByText('Target not reached', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Reset scenario' }).click();
  await expect(page.getByLabel('Power (kW)', { exact: true })).toHaveValue('25');
});

test('consent gates real tool runs and technical events agree with saved history', async ({ page }) => {
  let missedPoll = false;
  await page.route('**/api/office/runs/*', async route => {
    if (route.request().method() === 'GET' && !missedPoll) {
      missedPoll = true;
      await route.abort('failed');
    } else await route.continue();
  });
  const run = page.getByRole('button', { name: 'Run analysts' });
  await expect(run).toBeDisabled();
  await page.getByLabel('Send the public office sample', { exact: false }).check();
  await run.click();
  await expect(page.getByTestId('office-run-status')).toHaveText('complete');
  expect(missedPoll).toBe(true);
  await expect(page.getByRole('heading', { name: 'Energy Analyst', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Technical view' }).click();
  await expect(page.getByText('2 tool calls · 4 model requests', { exact: false })).toBeVisible();
  await expect(page.getByText('tool_finished · inspect_office', { exact: false })).toBeVisible();
  await expect(page.getByText('tool_finished · simulate_selected_battery', { exact: false })).toBeVisible();
  await page.reload();
  await page.locator('.office-history button').filter({ hasText: 'complete' }).first().click();
  await expect(page.getByTestId('office-run-status')).toHaveText('complete');
  await page.getByLabel('Power (kW)', { exact: true }).fill('20');
  await expect(page.getByTestId('office-run-status')).toHaveCount(0);
});

test('cancel and provider failure are recoverable and mobile keyboard navigation preserves bills', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel('Send the public office sample', { exact: false }).check();
  await page.getByRole('button', { name: 'Run analysts' }).click();
  await page.getByRole('button', { name: 'Cancel analysis' }).click();
  await expect(page.getByTestId('office-run-status')).toHaveText('cancelled');
  await page.getByLabel('Office AI provider').selectOption('anthropic');
  await expect(page.getByLabel('Send the public office sample', { exact: false })).not.toBeChecked();
  await page.getByLabel('Send the public office sample', { exact: false }).check();
  await page.getByRole('button', { name: 'Run analysts' }).click();
  await expect(page.getByTestId('office-run-status')).toHaveText('failed');
  await expect(page.getByText('Provider quota or rate limit reached; retry later.')).toBeVisible();
  await page.getByRole('button', { name: 'Review your bills', exact: true }).click();
  await page.getByRole('button', { name: 'Try the example' }).click();
  await page.getByLabel('Consumption', { exact: true }).fill('700');
  await expect(page.getByRole('button', { name: 'Office demo', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Save corrections' }).click();
  await expect(page.getByRole('button', { name: 'Office demo', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Office demo', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'A month in the office.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Review your bills', exact: true }).click();
  await expect(page.getByLabel('Consumption', { exact: true })).toHaveValue('700');
});

test('historical provider remains visible without replacing the available provider for a new run', async ({ page }) => {
  await page.route('**/api/office/runs', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({ json: [{ id: 'historical-provider', created: 1700000000,
      provider: 'oci', model: 'previous-model', status: 'interrupted', question: 'evaluate_battery',
      controls: { power_kw: 25, capacity_kwh: 100, efficiency: .9, target_kw: 80 },
      events: [], result: null, error: 'Application restarted before the run completed.' }] });
  });
  await page.getByRole('button', { name: 'Refresh history' }).click();
  await page.locator('.office-history button').filter({ hasText: 'interrupted' }).click();
  await expect(page.getByText('oci · previous-model', { exact: false })).toBeVisible();
  await expect(page.getByLabel('Send the public office sample', { exact: false })).toHaveAccessibleName(/to openai/);
});
