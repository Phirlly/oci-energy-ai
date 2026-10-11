import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Launch code').fill('admin');
  await page.getByRole('button', { name: 'Start session' }).click();
  await expect(page.getByRole('heading', { name: 'Your electricity, understood.' })).toBeVisible();
  await page.getByRole('button', { name: 'Review your bills', exact: true }).click();
});

test.afterEach(async ({ page, baseURL }) => {
  const response = await page.request.delete(`${baseURL}/api/session`, {
    headers: { Origin: new URL(baseURL).origin, 'x-energy-action': '1' }
  });
  expect(response.ok()).toBe(true);
});

test('missing dates preserve the ready bill average while daily and combined metrics stay unavailable', async ({ page }) => {
  await page.getByRole('button', { name: 'Try the example' }).click();
  await page.getByLabel('Start date').fill('');
  await page.getByRole('button', { name: 'Save corrections' }).click();
  await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByRole('heading', { name: 'Supplied-period insights' })).toBeVisible();
  await expect(page.getByTestId('daily-usage')).toHaveCount(0);
  await expect(page.getByText('Daily use: Unavailable', { exact: false })).toBeVisible();
  await expect(page.getByText('Average billed cost / kWh: USD 0.1578', { exact: true })).toBeVisible();
  await expect(page.getByText('The average includes billed charges; it is not a tariff rate.')).toBeVisible();
});

test('two uploaded and reviewed periods combine correctly and selection controls the result', async ({ page }) => {
  const periods = [
    { start: '2024-02-01', end: '2024-03-01', days: '29', usage: '580', cost: '87.00' },
    { start: '2024-03-01', end: '2024-04-01', days: '31', usage: '930', cost: '139.50' }
  ];
  for (const [index, period] of periods.entries()) {
    const text = `FICTIONAL DEMO / Sample Power / Account DEMO / Meter TEST
Electricity consumption ${period.usage} kWh / USD ${period.cost}
Service ${period.start} to ${period.end} / ${period.days} days`;
    const bytes = execFileSync('.venv/bin/python', ['-c',
      'import sys; from tests.fixtures.bills import pdf_bytes; sys.stdout.buffer.write(pdf_bytes(sys.argv[1]))', text],
      { cwd: process.cwd() + '/..', encoding: null });
    await page.getByLabel('Upload bill PDFs').setInputFiles({
      name: `fictional-${index}.pdf`, mimeType: 'application/pdf', buffer: bytes
    });
    await expect(page.getByLabel('Consumption', { exact: true })).toHaveValue('');
    await page.getByLabel('Service type').selectOption('electricity');
    await page.getByLabel('Usage meaning').selectOption('consumption');
    for (const [label, value] of Object.entries({ Supplier: 'Sample Power', 'Full account identity': 'DEMO',
      'Meter identity': 'TEST', 'Usage unit': 'kWh', Currency: 'USD', 'Start date': period.start,
      'End date': period.end, 'Billed days': period.days, Consumption: period.usage,
      'Current electricity charges': period.cost })) {
      await page.getByLabel(label, { exact: true }).fill(value);
    }
    await page.getByRole('button', { name: 'Save corrections' }).click();
    await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
    await expect(page.getByLabel(`Include bill ${index + 1} in insights`)).toBeChecked();
  }
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByTestId('daily-usage')).toHaveText('25.17 kWh/day');
  await expect(page.getByText('1510.00 kWh', { exact: true })).toBeVisible();
  await expect(page.getByText('USD 226.50', { exact: true })).toBeVisible();
  await expect(page.getByText('2 supplied periods · 60 billed days · 0 gap days.', { exact: false })).toBeVisible();
  await expect(page.getByRole('listitem').filter({ hasText: '2024-02-01 → 2024-03-01: 50.00%' })).toBeVisible();
  const first = page.locator('.bill-row').filter({ hasText: '2024-02-01' });
  const second = page.locator('.bill-row').filter({ hasText: '2024-03-01' });
  await first.getByRole('button').click();
  await page.getByLabel('Consumption', { exact: true }).fill('870');
  await page.getByRole('button', { name: 'Save corrections' }).click();
  await expect(first.getByRole('checkbox')).not.toBeChecked();
  await expect(first.getByRole('checkbox')).toBeDisabled();
  await expect(second.getByRole('checkbox')).toBeChecked();
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByTestId('daily-usage')).toHaveText('30.00 kWh/day');
  await expect(page.getByText('1 supplied period · 31 billed days · 0 gap days.', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Daily usage changes' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Approve reviewed facts' }).click();
  await expect(first.getByRole('checkbox')).toBeChecked();
  await expect(second.getByRole('checkbox')).toBeChecked();
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByText('1800.00 kWh', { exact: true })).toBeVisible();
  await expect(page.getByText('2 supplied periods · 60 billed days · 0 gap days.', { exact: false })).toBeVisible();
  await expect(page.getByRole('listitem').filter({ hasText: '2024-02-01 → 2024-03-01: 0.00%' })).toBeVisible();
  await first.getByRole('checkbox').uncheck();
  await expect(page.getByTestId('daily-usage')).toHaveCount(0);
  await page.getByRole('button', { name: 'Calculate insights' }).click();
  await expect(page.getByTestId('daily-usage')).toHaveText('30.00 kWh/day');
  await expect(page.getByRole('heading', { name: 'Daily usage changes' })).toHaveCount(0);
});
