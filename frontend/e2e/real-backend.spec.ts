import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';

/**
 * Full stack smoke test against a running backend on :8000 (proxied by the
 * Vite dev server). Skipped unless E2E_REAL_BACKEND=1.
 *
 *   E2E_REAL_BACKEND=1 npx playwright test --project=real-backend
 */
const FIXTURE =
  process.env.E2E_AUDIO_FIXTURE ??
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    '../../backend/tests/fixtures/soundscape_30s.flac',
  );

test.skip(
  process.env.E2E_REAL_BACKEND !== '1',
  'Set E2E_REAL_BACKEND=1 with the backend running on :8000.',
);

test('analyzes a real recording end to end', async ({ page, request }) => {
  test.setTimeout(240_000);
  expect(existsSync(FIXTURE), `audio fixture missing at ${FIXTURE}`).toBe(true);

  const health = await request.get('/api/v1/health');
  expect(health.ok()).toBe(true);

  await page.goto('/');
  await expect(page.getByRole('radio', { name: /Birds and more/ })).toBeChecked({
    timeout: 30_000,
  });
  await page.getByTestId('file-input').setInputFiles({
    name: 'soundscape_30s.flac',
    mimeType: 'audio/flac',
    buffer: readFileSync(FIXTURE),
  });
  await page.getByRole('button', { name: 'Generate spectrogram' }).click();
  await expect(page.getByTestId('decoded-duration')).toBeVisible({ timeout: 60_000 });

  await page.getByRole('button', { name: 'Run analysis' }).click();
  await expect(page.getByRole('list', { name: 'Analysis stages' })).toBeVisible();
  const done = page
    .getByRole('heading', { name: 'Species with detection events' })
    .or(page.getByTestId('no-detections'));
  await expect(done).toBeVisible({ timeout: 180_000 });

  const csvHref = await page.getByTestId('export-csv').getAttribute('href');
  expect(csvHref).toContain('threshold=0.60');
  const csv = await request.get(csvHref!);
  expect(csv.ok()).toBe(true);
  expect((await csv.text()).split('\n')[0]).toContain('analysis_id');

  await page.getByRole('slider', { name: 'Decision threshold' }).fill('0.45');
  await expect(page.getByTestId('applied-threshold')).toHaveText('Showing results at 45%', {
    timeout: 30_000,
  });
});
