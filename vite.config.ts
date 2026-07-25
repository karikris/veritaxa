import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/veritaxa/',
  build: {
    target: 'es2022',
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
});
