import { defineConfig } from '@playwright/test';
import config from './playwright.config';

const deployedUrl = process.env.VERITAXA_E2E_URL;

export default defineConfig({
  ...config,
  testMatch: 'production-image-pan.spec.ts',
  testIgnore: [],
  use: { ...config.use, baseURL: deployedUrl ?? 'http://127.0.0.1:4174/veritaxa/' },
  webServer: deployedUrl
    ? undefined
    : {
        command:
          'VITE_SUPABASE_URL=https://example-project.supabase.co VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_synthetic npm run build && npm run preview -- --host 127.0.0.1 --port 4174',
        url: 'http://127.0.0.1:4174/veritaxa/',
        reuseExistingServer: false,
      },
});
