import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { ANALYSIS_ID } from '../src/test/fixtures/analysis';
import { chooseRecording, fillMetadata, runToResults, setTheme } from './support/flows';
import { mockApi } from './support/mockApi';

function metric(page: Page, testId: string) {
  return page.getByTestId(testId).getByRole('definition');
}

test('upload, preview, analyze, change threshold, play an event and export', async ({ page }) => {
  const api = await mockApi(page, { pollsBeforeComplete: 3 });
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Turn field recordings into transparent biodiversity evidence.',
  );

  await chooseRecording(page);
  await page.getByRole('button', { name: 'Generate spectrogram' }).click();
  await expect(page.getByTestId('decoded-duration')).toHaveText('1 min 00 s');
  await expect(
    page.getByRole('img', { name: /Spectrogram of hollow-creek-dawn.wav/ }),
  ).toBeVisible();
  expect(api.previewCalls).toBe(1);

  await fillMetadata(page);
  await page.getByRole('button', { name: 'Run analysis' }).click();

  // Explicit stage list while the analysis runs.
  const stages = page.getByRole('list', { name: 'Analysis stages' });
  await expect(stages).toBeVisible();
  await expect(stages.getByRole('listitem')).toHaveCount(8);
  await expect(stages).toContainText('Running BirdNET');
  await expect(page.getByRole('heading', { name: 'Species with detection events' })).toBeVisible({
    timeout: 20_000,
  });

  await expect(metric(page, 'metric-richness')).toHaveText('6');
  await expect(page.getByTestId('species-row')).toHaveCount(6);
  await expect(page.getByTestId('export-csv')).toHaveAttribute(
    'href',
    `/api/v1/analyses/${ANALYSIS_ID}/export.csv?threshold=0.60`,
  );

  // Threshold change refetches from the server and every view follows.
  const refetch = page.waitForRequest((r) =>
    r.url().includes(`/analyses/${ANALYSIS_ID}?threshold=0.45`),
  );
  await page.getByRole('slider', { name: 'Decision threshold' }).fill('0.45');
  await refetch;
  await expect(page.getByTestId('applied-threshold')).toHaveText('Showing results at 45%');
  await expect(metric(page, 'metric-richness')).toHaveText('7');
  await expect(page.getByTestId('species-row')).toHaveCount(7);
  await expect(page.getByTestId('species-chart-row')).toHaveCount(7);

  // Clicking an event seeks the audio to its start and highlights it.
  const row = page.getByTestId('event-row').filter({ hasText: 'Song Sparrow' }).first();
  await row.getByRole('button', { name: /Play Song Sparrow from 0:06/ }).click();
  await expect(row).toHaveAttribute('aria-current', 'true');
  const time = await page
    .getByTestId('audio-element')
    .evaluate((el) => (el as HTMLAudioElement).currentTime);
  expect(time).toBeGreaterThanOrEqual(6);
  expect(time).toBeLessThan(7.5);

  // Export uses the applied threshold.
  const csv = page.getByTestId('export-csv');
  await expect(csv).toHaveAttribute(
    'href',
    `/api/v1/analyses/${ANALYSIS_ID}/export.csv?threshold=0.45`,
  );
  await expect(csv).toHaveAttribute('download', `thicket_${ANALYSIS_ID}_t0.45.csv`);
  await expect(page.getByTestId('export-json')).toHaveAttribute(
    'href',
    `/api/v1/analyses/${ANALYSIS_ID}/export.json?threshold=0.45`,
  );
});

test('no detections above the threshold is a calm, valid result', async ({ page }) => {
  await mockApi(page, { pollsBeforeComplete: 1, analysis: { confidenceScale: 0.5 } });
  await page.goto('/');
  await chooseRecording(page);
  await page.getByRole('button', { name: 'Run analysis' }).click();

  const empty = page.getByTestId('no-detections');
  await expect(empty).toContainText('No detection events above 60%', { timeout: 20_000 });
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(metric(page, 'metric-richness')).toHaveText('0');

  await empty.getByRole('button', { name: 'Show results at 45%' }).click();
  await expect(page.getByTestId('applied-threshold')).toHaveText('Showing results at 45%');
  await expect(page.getByTestId('species-row').first()).toBeVisible();
});

test('a backend 500 shows a friendly error and retry succeeds', async ({ page }) => {
  const api = await mockApi(page, {
    pollsBeforeComplete: 1,
    createFailures: [
      { status: 500, body: { error_code: 'internal_error', message: 'Worker crashed' } },
    ],
  });
  await page.goto('/');
  await chooseRecording(page);
  await page.getByRole('button', { name: 'Run analysis' }).click();

  const alert = page.getByRole('alert');
  await expect(alert).toContainText('Something went wrong on the server');
  await expect(alert).toContainText('Worker crashed');
  await alert.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByRole('heading', { name: 'Species with detection events' })).toBeVisible({
    timeout: 20_000,
  });
  expect(api.createCalls).toBe(2);
});

test('backend unreachable is explained, not a blank screen', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => route.fulfill({ status: 502, body: 'Bad Gateway' }));
  await page.goto('/');
  await expect(page.getByText('The Thicket server is unavailable')).toBeVisible();
  await chooseRecording(page);
  await expect(page.getByRole('button', { name: 'Run analysis' })).toBeDisabled();
});

test('experimental models are hidden without the flag', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await expect(page.getByRole('radio', { name: /Birds and more/ })).toBeChecked();
  await expect(page.getByRole('radio', { name: /Perch/ })).toHaveCount(0);
  await expect(page.getByText('Experimental')).toHaveCount(0);
});

test('map tab only with coordinates; never a fallback point', async ({ page }) => {
  await mockApi(page, {
    pollsBeforeComplete: 1,
    analysis: { recording: { latitude: null, longitude: null } },
  });
  await page.goto('/');
  await chooseRecording(page);
  await runToResults(page);
  await expect(page.getByRole('tab', { name: 'Map' })).toHaveCount(0);
  await expect(page.getByTestId('location-status')).toHaveText('Location not provided');
});

test('timeline lanes seek audio and show the view filter', async ({ page }) => {
  await mockApi(page, { pollsBeforeComplete: 1 });
  await page.goto('/');
  await chooseRecording(page);
  await runToResults(page);
  await page.getByRole('tab', { name: 'Timeline' }).click();
  await expect(page.getByText('Minimum confidence (view filter)')).toBeVisible();
  const bar = page.getByRole('button', { name: /Northern Cardinal, 0:12 to 0:15/ });
  await bar.click();
  await expect(bar).toHaveAttribute('aria-current', 'true');
  const time = await page
    .getByTestId('audio-element')
    .evaluate((el) => (el as HTMLAudioElement).currentTime);
  expect(time).toBeGreaterThanOrEqual(12);

  const before = await page.getByTestId('timeline-bar').count();
  await page.getByLabel('Minimum confidence (view filter)').fill('0.8');
  await expect.poll(() => page.getByTestId('timeline-bar').count()).toBeLessThan(before);
  // The view filter does not change the decision threshold.
  await expect(page.getByTestId('applied-threshold')).toHaveText('Showing results at 60%');
});

async function axeViolations(page: Page): Promise<string[]> {
  await page.waitForTimeout(400); // let fade-ins finish before contrast checks
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  return results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`,
  );
}

for (const theme of ['light', 'dark'] as const) {
  test(`results views have no axe violations (${theme})`, async ({ page }) => {
    await setTheme(page, theme);
    await mockApi(page, { pollsBeforeComplete: 1 });
    await page.goto('/');
    expect(await axeViolations(page), 'empty state').toEqual([]);
    await chooseRecording(page);
    await runToResults(page);
    expect(await axeViolations(page), 'results tab').toEqual([]);
    await page.getByRole('tab', { name: 'Timeline' }).click();
    expect(await axeViolations(page), 'timeline tab').toEqual([]);
    await page.getByRole('tab', { name: 'Methods' }).click();
    expect(await axeViolations(page), 'methods tab').toEqual([]);
  });
}

test('mobile width has no horizontal page scroll', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await mockApi(page, { pollsBeforeComplete: 1 });
  await page.goto('/');
  await chooseRecording(page);
  await runToResults(page);
  for (const tab of ['Results', 'Timeline', 'Methods']) {
    await page.getByRole('tab', { name: tab }).click();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${tab}`).toBeLessThanOrEqual(0);
  }
});

test('keyboard users can reach and operate the main controls', async ({ page }) => {
  await mockApi(page, { pollsBeforeComplete: 1 });
  await page.goto('/');
  await page.getByRole('heading', { level: 1 }).waitFor();
  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => document.activeElement?.textContent ?? '');
  expect(focused).toBe('Skip to main content');
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Choose file' }).focus();
  await page.keyboard.press('Enter');
  await (
    await chooser
  ).setFiles({ name: 'dawn.wav', mimeType: 'audio/wav', buffer: Buffer.from('RIFF0000WAVE') });
  await expect(page.getByTestId('file-facts')).toContainText('dawn.wav');
});
