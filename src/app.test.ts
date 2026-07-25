import { beforeEach, describe, expect, it } from 'vitest';

import { renderApp } from './app';
import type { ConfigResult } from './config';

const validConfig: ConfigResult = {
  ok: true,
  value: {
    supabaseUrl: 'https://example-project.supabase.co',
    supabasePublishableKey: 'sb_publishable_synthetic',
  },
};

function getRoot(): HTMLElement {
  const root = document.querySelector<HTMLElement>('#app');
  if (!root) throw new Error('Test root is missing');
  return root;
}

describe('application shell', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="app"></div>';
  });

  it('shows only the compact login experience before authentication', () => {
    renderApp(getRoot(), validConfig);

    expect(document.querySelector('header')?.textContent).toBe('VeriTaxa');
    expect(document.querySelector('input[type="email"]')).not.toBeNull();
    expect(document.querySelector('button')?.textContent).toBe('Send sign-in link');
    expect(document.querySelectorAll('[role="tab"]')).toHaveLength(0);
    expect(document.querySelectorAll('nav')).toHaveLength(0);
  });

  it('fails closed when public configuration is absent', () => {
    renderApp(getRoot(), { ok: false, message: 'Configuration is missing.' });

    expect(document.body.textContent).toContain('Configuration required');
    expect(document.body.textContent).toContain('Configuration is missing.');
    expect(document.querySelector('input')).toBeNull();
  });
});
