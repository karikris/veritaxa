import './styles.css';
import { renderApp } from './app';
import { readPublicConfig } from './config';

const root = document.querySelector<HTMLElement>('#app');

if (!root) {
  throw new Error('Application root is missing');
}

renderApp(root, readPublicConfig());
