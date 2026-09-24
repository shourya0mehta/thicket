import { test, expect } from '@playwright/test';
import { mockApi } from './support/mockApi';
import { chooseRecording, fillMetadata, runToResults, setTheme } from './support/flows';

/**
 * Captures reference screenshots of the results view into ./screenshots.
 * Opt-in: `npm run screenshots` (sets SCREENSHOTS=1).
 */
test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to capture screenshots.');

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
} as const;

for (const theme of ['light', 'dark'] as const) {
  for (const [device, viewport] of Object.entries(VIEWPORTS)) {
    test(`results ${device} ${theme}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await setTheme(page, theme);
      await mockApi(page, { pollsBeforeComplete: 1 });
      await page.goto('/');
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      if (device === 'desktop') {
        await page.screenshot({ path: `screenshots/empty-${device}-${theme}.png`, fullPage: true });
      }
      await chooseRecording(page);
      await fillMetadata(page);
      await runToResults(page);
      await page.waitForTimeout(600);
      await page.screenshot({ path: `screenshots/results-${device}-${theme}.png`, fullPage: true });

      await page.getByRole('tab', { name: 'Timeline' }).click();
      await page.getByTestId('timeline-bar').first().click();
      await page.waitForTimeout(300);
      await page.screenshot({
        path: `screenshots/timeline-${device}-${theme}.png`,
        fullPage: true,
      });
    });
  }
}

test('states: preview, processing, methods, history', async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.desktop);
  await setTheme(page, 'light');
  await mockApi(page, { pollsBeforeComplete: 30 });
  await page.goto('/');
  await chooseRecording(page);
  await fillMetadata(page);
  await page.getByRole('button', { name: 'Generate spectrogram' }).click();
  await expect(page.getByTestId('decoded-duration')).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: 'screenshots/preview-desktop-light.png', fullPage: true });

  await page.getByRole('button', { name: 'Run analysis' }).click();
  await expect(page.getByRole('list', { name: 'Analysis stages' })).toBeVisible();
  await page.waitForTimeout(2600);
  await page.screenshot({ path: 'screenshots/processing-desktop-light.png', fullPage: false });

  await page.goto('/#/methods');
  await expect(page.getByRole('heading', { name: 'Methods', level: 1 })).toBeVisible();
  await page.screenshot({ path: 'screenshots/methods-desktop-light.png', fullPage: true });

  await page.evaluate(() =>
    window.localStorage.setItem(
      'thicket-history',
      JSON.stringify([
        {
          id: 'an_7f3c2a91d4',
          filename: 'hollow-creek-dawn.wav',
          site: 'Hollow Creek Easement, north meadow',
          created_at: '2026-09-24T13:12:08Z',
          richness: 6,
          top_species: ['Northern Cardinal', 'American Robin', 'Song Sparrow'],
        },
        {
          id: 'an_2',
          filename: 'pond-edge-dusk.flac',
          site: 'Mill Pond, south edge',
          created_at: '2026-09-23T23:40:00Z',
          richness: 4,
          top_species: ['Spring Peeper', 'Gray Treefrog'],
        },
      ]),
    ),
  );
  await page.goto('/#/history');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'History', level: 1 })).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'screenshots/history-desktop-light.png', fullPage: true });
});
