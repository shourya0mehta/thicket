import { expect, test } from '@playwright/test';
import { buildAnalysis } from '../src/test/fixtures/analysis';
import { spectrogramPng } from './support/mockApi';
import { syntheticWav } from './support/png';

// Runs against the dev server started with VITE_DEMO_MODE=true. Demo files are
// served through route mocks, so nothing needs to exist under public/demo.
test('demo mode loads precomputed analyses without uploads', async ({ page }) => {
  const requested: string[] = [];
  await page.route(
    (url) => url.pathname.startsWith('/demo/'),
    async (route) => {
      const url = new URL(route.request().url());
      requested.push(url.pathname);
      if (url.pathname.endsWith('/demo/index.json')) {
        return route.fulfill({
          json: {
            analyses: [
              {
                id: 'hollow-creek',
                title: 'Dawn chorus, Hollow Creek',
                description: 'Sixty seconds of spring dawn chorus with frogs.',
                attribution: 'Recorded by A. Field (xeno-canto XC000000)',
                license: 'CC BY 4.0',
              },
            ],
          },
        });
      }
      const match = /threshold-(\d\.\d\d)\.json$/.exec(url.pathname);
      if (match)
        return route.fulfill({
          json: buildAnalysis({ id: 'demo_hc', threshold: Number(match[1]) }),
        });
      if (url.pathname.endsWith('spectrogram.png'))
        return route.fulfill({ body: spectrogramPng(), contentType: 'image/png' });
      if (url.pathname.endsWith('audio.mp3'))
        return route.fulfill({ body: syntheticWav(60), contentType: 'audio/wav' });
      return route.fulfill({ status: 404 });
    },
  );
  // No API calls may happen in demo mode.
  await page.route('**/api/v1/**', (route) => route.fulfill({ status: 500, body: 'unexpected' }));

  await page.goto('/');
  await expect(page.getByTestId('demo-banner')).toHaveText(
    'Demo: precomputed analyses of openly licensed recordings. Run Thicket locally to analyze your own audio.',
  );
  await expect(page.getByRole('button', { name: 'Choose file' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'History' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Species with detection events' })).toBeVisible();
  await expect(page.getByTestId('demo-attribution')).toContainText('CC BY 4.0');
  expect(requested).toContain('/demo/hollow-creek/threshold-0.60.json');

  await page.getByRole('slider', { name: 'Decision threshold' }).fill('0.45');
  await expect(page.getByTestId('applied-threshold')).toHaveText('Showing results at 45%');
  expect(requested).toContain('/demo/hollow-creek/threshold-0.45.json');

  // Review is off; exports are generated in the browser.
  await expect(page.getByRole('button', { name: 'Accept' }).first()).toBeDisabled();
  const csv = page.getByTestId('export-csv');
  await expect(csv).toHaveAttribute('href', /^blob:/);
  await expect(csv).toHaveAttribute('download', 'thicket_demo_hc_t0.45.csv');
  await expect(page.getByRole('button', { name: 'Delete from server' })).toHaveCount(0);
});
