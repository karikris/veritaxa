import { loadEnv, type Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

const CSP_ORIGIN_PLACEHOLDER = '__VERITAXA_SUPABASE_ORIGIN__';
const CSP_DEV_STYLE_PLACEHOLDER = '__VERITAXA_DEV_STYLE__';

function cspPlugin(origin: string, development: boolean): Plugin {
  return {
    name: 'veritaxa-csp',
    transformIndexHtml(html) {
      return html
        .replace(CSP_ORIGIN_PLACEHOLDER, origin)
        .replace(CSP_DEV_STYLE_PLACEHOLDER, development ? "'unsafe-inline'" : '');
    },
  };
}

function requireSupabaseOrigin(value: string | undefined): string {
  if (!value) {
    throw new Error('VITE_SUPABASE_URL is required for a production build.');
  }
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/') {
    throw new Error('VITE_SUPABASE_URL must be a credential-free HTTPS project origin.');
  }
  return url.origin;
}

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const origin =
    command === 'build'
      ? requireSupabaseOrigin(env.VITE_SUPABASE_URL)
      : 'https://localhost.invalid';

  if (command === 'build' && !env.VITE_SUPABASE_PUBLISHABLE_KEY) {
    throw new Error('VITE_SUPABASE_PUBLISHABLE_KEY is required for a production build.');
  }

  return {
    base: '/veritaxa/',
    plugins: [cspPlugin(origin, command !== 'build')],
    build: {
      target: 'es2022',
    },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.ts'],
    },
  };
});
