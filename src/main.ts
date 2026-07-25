import './styles.css';
import { VeriTaxaApp } from './app';
import { readPublicConfig } from './config';
import { SupabaseReviewRepository } from './data/supabaseReviewRepository';
import type { ReviewRepository } from './data/reviewRepository';

function applicationRoot(): HTMLElement {
  const root = document.querySelector<HTMLElement>('#app');
  if (!root) throw new Error('Application root is missing');
  return root;
}

const root = applicationRoot();

async function start(): Promise<void> {
  const config = readPublicConfig();

  if (!config.ok) {
    const header = document.createElement('header');
    header.className = 'site-header';
    const brand = document.createElement('span');
    brand.className = 'wordmark';
    brand.textContent = 'VeriTaxa';
    header.append(brand);
    const main = document.createElement('main');
    main.className = 'status-shell';
    const status = document.createElement('p');
    status.className = 'status-text status-text--error';
    status.setAttribute('role', 'alert');
    status.textContent = config.message;
    main.append(status);
    root.append(header, main);
    return;
  }

  let repository: ReviewRepository = new SupabaseReviewRepository(config.value);
  if (
    import.meta.env.DEV &&
    new URLSearchParams(window.location.search).get('repository') === 'synthetic'
  ) {
    const { SyntheticReviewRepository } = await import('./data/mockReviewRepository');
    repository = new SyntheticReviewRepository();
  }

  const app = new VeriTaxaApp(root, repository, {
    storage: window.localStorage,
  });
  await app.start();
}

void start();
