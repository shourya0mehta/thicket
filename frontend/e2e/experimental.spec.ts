import { expect, test } from '@playwright/test';
import { mockApi } from './support/mockApi';

// Runs against the dev server started with VITE_ENABLE_EXPERIMENTAL_MODELS=true.
test('experimental models appear with a badge, explanation and disabled state', async ({
  page,
}) => {
  await mockApi(page);
  await page.goto('/');

  const group = page.getByRole('radiogroup', { name: 'Model' });
  await expect(group.getByRole('radio')).toHaveCount(4); // BirdNET, frogs/insects, Perch, Combined
  await expect(page.getByRole('radio', { name: /Birds and more/ })).toBeChecked();

  const disabled = page.getByRole('radio', { name: /Frogs and insects/ });
  await expect(disabled).toBeDisabled();
  await expect(page.getByTestId('model-status-frogs_insects')).toHaveText(
    'Disabled until it passes the validation benchmark.',
  );
  await expect(group.getByText('Experimental', { exact: true })).toHaveCount(3);

  const info = page.getByRole('button', { name: 'About experimental model Perch 2.0' });
  await info.hover();
  await expect(page.getByRole('tooltip').filter({ hasText: 'validation benchmark' })).toBeVisible();

  await page.getByRole('radio', { name: /Combined/ }).check();
  await expect(page.getByRole('radio', { name: /Combined/ })).toBeChecked();
});

test('combined runs send every ready model key', async ({ page }) => {
  await mockApi(page, { pollsBeforeComplete: 1 });
  await page.goto('/');
  await page.getByTestId('file-input').setInputFiles({
    name: 'dawn.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('RIFF0000WAVE'),
  });
  await page.getByRole('radio', { name: /Combined/ }).check();
  const post = page.waitForRequest(
    (r) => r.method() === 'POST' && r.url().endsWith('/api/v1/analyses'),
  );
  await page.getByRole('button', { name: 'Run analysis' }).click();
  const body = (await post).postData() ?? '';
  expect(body).toContain('["birdnet","perch"]');
});
