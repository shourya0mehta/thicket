import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { ORG, RECORDER_MOTH2, SITE_NORTH } from '../src/test/fixtures/platform';
import { setTheme } from './support/flows';
import { mockApi } from './support/mockApi';
import { mockPlatform } from './support/mockPlatform';
import { syntheticWav } from './support/png';

async function axeViolations(page: Page): Promise<string[]> {
  await page.waitForTimeout(400); // let fade-ins finish before contrast checks
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  return results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`,
  );
}

function sideNav(page: Page) {
  return page.getByRole('navigation', { name: 'Organization' });
}

test('sign in, create an organization, add a site, batch upload, dashboard, alert, report', async ({
  page,
}) => {
  await mockApi(page, { pollsBeforeComplete: 0 });
  const platform = await mockPlatform(page, {
    signedIn: false,
    organizations: [],
    pollsBeforeComplete: 1,
  });

  // Sign in with the development form.
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await page.getByLabel(/Email/).fill('jane@hollowcreek.example');
  await page.getByLabel(/^Name/).fill('Jane Farmer');
  await page.getByRole('button', { name: 'Sign in' }).click();

  // No organizations yet: create one.
  await expect(
    page.getByRole('heading', { level: 1, name: 'Create your farm or project' }),
  ).toBeVisible();
  await page.getByLabel(/^Name/).fill('Hilltop Farm');
  await page.getByRole('button', { name: 'Create organization' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
  await expect(page.getByTestId('org-name')).toHaveText('Hilltop Farm');

  // Add a site with coordinates.
  await sideNav(page).getByRole('link', { name: 'Sites' }).click();
  await page.getByRole('button', { name: 'Add site' }).first().click();
  const form = page.getByTestId('site-form');
  await form.getByLabel(/Site name/).fill('Bobolink meadow');
  await form.getByLabel('Latitude').fill('95');
  await form.getByLabel('Longitude').fill('-76.47');
  await form.getByRole('button', { name: 'Add site' }).click();
  await expect(form.getByText('Latitude must be a number between -90 and 90.')).toBeVisible();
  await form.getByLabel('Latitude').fill('42.45');
  await form.getByRole('button', { name: 'Add site' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Bobolink meadow' })).toBeVisible();
  await expect(page.getByTestId('site-map')).toBeVisible();

  // Batch upload two AudioMoth files and a CONFIG.TXT.
  await page.getByRole('link', { name: 'Upload here' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Upload recordings' })).toBeVisible();
  await page.getByTestId('batch-input').setInputFiles([
    { name: '20260514_053000.WAV', mimeType: 'audio/wav', buffer: syntheticWav(5) },
    { name: '20260514_060000.WAV', mimeType: 'audio/wav', buffer: syntheticWav(5) },
    { name: 'CONFIG.TXT', mimeType: 'text/plain', buffer: Buffer.from('Device ID: 24A1D5F3C9') },
  ]);
  await expect(page.getByTestId('timestamp-preview').first()).toHaveText('2026-05-14 05:30 UTC');
  await expect(page.getByLabel(/^Site/)).toHaveValue('site_new_1');
  await expect(page.getByRole('radio', { name: /Birds and more/ })).toBeChecked();
  await page.getByTestId('start-batch').click();
  await expect(page.getByTestId('batch-progress')).toContainText('2 of 2 files finished', {
    timeout: 15_000,
  });
  await expect(page.getByTestId('batch-progress')).toContainText('logs read: CONFIG.TXT');
  const upload = platform.log.find((r) => r.method === 'POST' && r.path.endsWith('/uploads'));
  expect(upload?.body).toMatchObject({
    files: ['file:20260514_053000.WAV', 'file:20260514_060000.WAV', 'file:CONFIG.TXT'],
    site_id: 'site_new_1',
    timezone: expect.any(String),
  });
  expect((upload?.body as { last_modified: string[] }).last_modified).toHaveLength(3);

  // Dashboard with charts.
  await sideNav(page).getByRole('link', { name: 'Dashboard' }).click();
  await expect(page.getByTestId('kpi-row')).toBeVisible();
  await expect(page.getByRole('img', { name: /^Species richness by day/ })).toBeVisible();

  // Acknowledge an alert.
  await sideNav(page).getByRole('link', { name: 'Alerts' }).click();
  const row = page.getByTestId('alert-row').filter({ hasText: 'Dawn species richness fell' });
  await row.getByRole('button', { name: 'Acknowledge' }).click();
  await expect(row.getByText('Acknowledged', { exact: true })).toBeVisible();
  const patch = platform.log.find((r) => r.method === 'PATCH' && r.path.startsWith('/alerts/'));
  expect(patch?.body).toMatchObject({ status: 'acknowledged' });

  // Report wizard to a download link.
  await sideNav(page).getByRole('link', { name: 'Reports' }).click();
  await page.getByRole('link', { name: 'New report' }).first().click();
  await page.getByTestId('template-evidence').click();
  await page.getByTestId('to-fields').click();
  await page.getByTestId('field-preparer_name').fill('Jane Farmer');
  await page.getByTestId('build-report').click();
  await expect(page.getByText('Some required details are missing')).toBeVisible();
  await page.getByRole('button', { name: 'Build with blanks' }).click();
  const pdf = page.getByTestId('download-pdf');
  await expect(pdf).toBeVisible({ timeout: 15_000 });
  await expect(pdf).toHaveAttribute('href', '/api/v1/reports/rp_new_1.pdf');
  await expect(page.getByTestId('download-json')).toHaveAttribute(
    'href',
    '/api/v1/reports/rp_new_1.json',
  );
});

test('opening a recording shows the existing analysis results view', async ({ page }) => {
  await mockApi(page, { pollsBeforeComplete: 0 });
  await mockPlatform(page, {});
  await page.goto(`/#/orgs/${ORG.id}/recordings`);
  await expect(page.getByTestId('recording-row').first()).toBeVisible();
  await page.getByTestId('recording-row').first().getByRole('link', { name: /Open/ }).click();
  await expect(page.getByRole('heading', { name: 'Species with detection events' })).toBeVisible({
    timeout: 15_000,
  });
});

for (const theme of ['light', 'dark'] as const) {
  test(`platform pages have no axe violations (${theme})`, async ({ page }) => {
    await setTheme(page, theme);
    await mockApi(page, { pollsBeforeComplete: 0 });
    await mockPlatform(page, {});

    await page.goto(`/#/orgs/${ORG.id}`);
    await expect(page.getByTestId('kpi-row')).toBeVisible();
    await expect(page.getByTestId('heatmap-chart')).toBeVisible();
    expect(await axeViolations(page), 'dashboard').toEqual([]);

    await page.goto(`/#/orgs/${ORG.id}/alerts`);
    await expect(page.getByTestId('alerts-ecology')).toBeVisible();
    await page.getByTestId('alert-row').first().getByRole('button', { expanded: false }).click();
    expect(await axeViolations(page), 'alerts').toEqual([]);

    await page.goto(`/#/orgs/${ORG.id}/recorders/${RECORDER_MOTH2}`);
    await expect(page.getByTestId('health-checks')).toBeVisible();
    await expect(page.getByTestId('level-chart')).toBeVisible();
    expect(await axeViolations(page), 'recorder').toEqual([]);

    await page.goto(`/#/orgs/${ORG.id}/sites/${SITE_NORTH}`);
    await expect(page.getByTestId('phenology-chart')).toBeVisible();
    expect(await axeViolations(page), 'site').toEqual([]);
  });
}

test('platform pages have no horizontal page scroll on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await mockApi(page, { pollsBeforeComplete: 0 });
  await mockPlatform(page, {});
  for (const path of [
    '',
    '/alerts',
    `/recorders/${RECORDER_MOTH2}`,
    `/sites/${SITE_NORTH}`,
    '/sites',
    '/recordings',
    '/upload',
    '/reports',
    '/reports/new',
    '/settings',
  ]) {
    await page.goto(`/#/orgs/${ORG.id}${path}`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path || 'dashboard'}`).toBeLessThanOrEqual(0);
  }
  // The bottom tab bar replaces the side navigation.
  await expect(page.getByRole('navigation', { name: 'Organization' })).toBeVisible();
  await page.getByRole('button', { name: 'More' }).click();
  await expect(page.getByRole('menuitem', { name: 'Settings' })).toBeVisible();
});

test('google mode links to the server sign-in URL', async ({ page }) => {
  await mockApi(page, {});
  await mockPlatform(page, {
    auth: {
      mode: 'google',
      sign_in_url: '/api/v1/auth/google/start',
      allowed_domains: [],
    },
    signedIn: false,
  });
  await page.goto(`/#/orgs/${ORG.id}/alerts`);
  const link = page.getByTestId('google-sign-in');
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute(
    'href',
    `/api/v1/auth/google/start?next=${encodeURIComponent(`#/orgs/${ORG.id}/alerts`)}`,
  );
});
