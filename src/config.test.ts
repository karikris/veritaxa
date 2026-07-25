import { describe, expect, it } from 'vitest';

import { readPublicConfig } from './config';

describe('public configuration', () => {
  it('accepts an HTTPS project URL and publishable key', () => {
    const result = readPublicConfig({
      VITE_SUPABASE_URL: 'https://example-project.supabase.co',
      VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_synthetic',
    });

    expect(result.ok).toBe(true);
  });

  it.each([
    'http://example-project.supabase.co',
    'https://user:password@example-project.supabase.co',
    'not-a-url',
  ])('rejects unsafe project URL %s', (url) => {
    const result = readPublicConfig({
      VITE_SUPABASE_URL: url,
      VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_synthetic',
    });

    expect(result.ok).toBe(false);
  });
});
