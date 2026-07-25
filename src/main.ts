import './styles.css';
import { VeriTaxaApp } from './app';
import { readPublicConfig } from './config';
import { SupabaseReviewRepository } from './data/supabaseReviewRepository';

const root = document.querySelector<HTMLElement>('#app');

if (!root) {
  throw new Error('Application root is missing');
}

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
} else {
  const app = new VeriTaxaApp(root, new SupabaseReviewRepository(config.value), {
    storage: window.localStorage,
  });
  void app.start();
}
