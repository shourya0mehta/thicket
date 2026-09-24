import { expect, type Page } from '@playwright/test';
import { syntheticWav } from './png';

export const WAV_NAME = 'hollow-creek-dawn.wav';

/** Picks the synthetic recording through the hidden file input. */
export async function chooseRecording(page: Page, name = WAV_NAME) {
  await page.getByTestId('file-input').setInputFiles({
    name,
    mimeType: 'audio/wav',
    buffer: syntheticWav(60),
  });
  await expect(page.getByTestId('file-facts')).toContainText(name);
}

export async function fillMetadata(page: Page) {
  await page.getByLabel('Site name').fill('Hollow Creek Easement, north meadow');
  await page.getByLabel('Latitude').fill('42.4531');
  await page.getByLabel('Longitude').fill('-76.4735');
  await page.getByLabel('Recording date and time').fill('2026-05-14T05:42');
  await page.getByLabel('Time zone').fill('America/New_York');
}

export async function runToResults(page: Page) {
  await page.getByRole('button', { name: 'Run analysis' }).click();
  await expect(page.getByRole('heading', { name: 'Species with detection events' })).toBeVisible({
    timeout: 20_000,
  });
}

export async function setTheme(page: Page, theme: 'light' | 'dark') {
  await page.addInitScript((value) => {
    try {
      window.localStorage.setItem('thicket-theme', value);
    } catch {
      // ignore
    }
  }, theme);
}
