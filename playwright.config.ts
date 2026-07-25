import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command:
      'VITE_SUPABASE_URL=https://example-project.supabase.co VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_synthetic npm run dev -- --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173/veritaxa/',
    reuseExistingServer: !process.env.CI,
  },
});
