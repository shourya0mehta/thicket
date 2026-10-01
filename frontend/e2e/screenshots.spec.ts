import { test, expect, type Page } from '@playwright/test';
import { ORG, RECORDER_MOTH2, SITE_NORTH } from '../src/test/fixtures/platform';
import { mockApi } from './support/mockApi';
import { mockPlatform } from './support/mockPlatform';
import { chooseRecording, fillMetadata, runToResults, setTheme } from './support/flows';

/**
 * Captures reference screenshots of the results view and the platform pages
 * (dashboard, site, recorder health, alerts, report wizard) into ./screenshots.
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

const PLATFORM_PAGES: Array<{
  name: string;
  path: string;
  ready: string;
  prepare?: (page: Page) => Promise<void>;
}> = [
  { name: 'dashboard', path: '', ready: 'heatmap-chart' },
  { name: 'site', path: `/sites/${SITE_NORTH}`, ready: 'phenology-chart' },
  { name: 'recorder', path: `/recorders/${RECORDER_MOTH2}`, ready: 'level-chart' },
  {
    name: 'alerts',
    path: '/alerts',
    ready: 'alerts-ecology',
    prepare: async (page) => {
      await page.getByTestId('alert-row').first().getByRole('button', { expanded: false }).click();
    },
  },
  {
    name: 'report-wizard',
    path: '/reports/new',
    ready: 'template-cards',
  },
  {
    name: 'report-fields',
    path: '/reports/new',
    ready: 'template-cards',
    prepare: async (page) => {
      await page.getByTestId('template-nrcs').click();
      await page.getByTestId('to-fields').click();
      await page.getByTestId('group-nrcs').waitFor();
    },
  },
];

for (const theme of ['light', 'dark'] as const) {
  for (const [device, viewport] of Object.entries(VIEWPORTS)) {
    test(`platform ${device} ${theme}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await setTheme(page, theme);
      await mockApi(page, { pollsBeforeComplete: 0 });
      await mockPlatform(page, {});
      for (const p of PLATFORM_PAGES) {
        await page.goto(`/#/orgs/${ORG.id}${p.path}`);
        await page.getByTestId(p.ready).waitFor();
        if (p.prepare) await p.prepare(page);
        await page.waitForTimeout(700);
        await page.screenshot({
          path: `screenshots/${p.name}-${device}-${theme}.png`,
          fullPage: true,
        });
      }
    });
  }
}
