import { defineConfig, devices } from '@playwright/test';

/**
 * E2E tests run against Vite dev servers with the API mocked through
 * page.route, so no backend is needed. Three servers cover the build flags:
 *   5173 default, 5174 experimental models enabled, 5175 demo mode.
 * real-backend.spec.ts runs only with E2E_REAL_BACKEND=1 (backend on :8000).
 * screenshots.spec.ts runs only with SCREENSHOTS=1 (npm run screenshots).
 */
const PORT = 5173;
const PORT_EXPERIMENTAL = 5174;
const PORT_DEMO = 5175;
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

function server(port: number, env: Record<string, string>) {
  return {
    command: `npx vite --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      VITE_API_BASE_URL: '',
      VITE_ENABLE_EXPERIMENTAL_MODELS: 'false',
      VITE_DEMO_MODE: 'false',
      VITE_BASE_PATH: '/',
      ...env,
    },
  };
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: process.env.CI ? 1 : 2,
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: [
        /experimental\.spec\.ts/,
        /demo\.spec\.ts/,
        /screenshots\.spec\.ts/,
        /real-backend\.spec\.ts/,
      ],
    },
    {
      name: 'experimental',
      testMatch: /experimental\.spec\.ts/,
      use: { baseURL: `http://localhost:${PORT_EXPERIMENTAL}` },
    },
    {
      name: 'demo',
      testMatch: /demo\.spec\.ts/,
      use: { baseURL: `http://localhost:${PORT_DEMO}` },
    },
    {
      name: 'real-backend',
      testMatch: /real-backend\.spec\.ts/,
    },
    {
      name: 'screenshots',
      testMatch: /screenshots\.spec\.ts/,
    },
  ],
  webServer: [
    server(PORT, {}),
    server(PORT_EXPERIMENTAL, { VITE_ENABLE_EXPERIMENTAL_MODELS: 'true' }),
    server(PORT_DEMO, { VITE_DEMO_MODE: 'true' }),
  ],
});
