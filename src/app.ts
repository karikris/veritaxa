import type { ConfigResult } from './config';

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function buildHeader(): HTMLElement {
  const header = element('header', 'site-header');
  const brand = element('span', 'wordmark');
  brand.textContent = 'VeriTaxa';
  header.append(brand);
  return header;
}

function buildStatus(message: string, kind: 'quiet' | 'error' = 'quiet'): HTMLElement {
  const status = element('p', `status-text status-text--${kind}`);
  status.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  status.textContent = message;
  return status;
}

function buildLogin(): HTMLElement {
  const main = element('main', 'login-shell');
  const panel = element('section', 'login-panel');
  panel.setAttribute('aria-labelledby', 'login-heading');

  const eyebrow = element('p', 'eyebrow');
  eyebrow.textContent = 'Private review workspace';

  const heading = element('h1');
  heading.id = 'login-heading';
  heading.textContent = 'Sign in to continue';

  const intro = element('p', 'login-copy');
  intro.textContent = 'We’ll email an access link to approved reviewers.';

  const form = element('form', 'login-form');
  const label = element('label');
  label.htmlFor = 'reviewer-email';
  label.textContent = 'Email address';

  const field = element('input');
  field.id = 'reviewer-email';
  field.name = 'email';
  field.type = 'email';
  field.autocomplete = 'email';
  field.required = true;
  field.placeholder = 'you@example.org';

  const button = element('button', 'primary-button');
  button.type = 'submit';
  button.textContent = 'Send sign-in link';
  button.disabled = true;
  button.title = 'Authentication is connected in the classifier phase';

  form.append(label, field, button);
  panel.append(
    eyebrow,
    heading,
    intro,
    form,
    buildStatus('Access is limited to approved reviewers.'),
  );
  main.append(panel);
  return main;
}

export function renderApp(root: HTMLElement, config: ConfigResult): void {
  root.replaceChildren();
  const page = element('div', 'app-shell');
  page.append(buildHeader());

  if (!config.ok) {
    const main = element('main', 'login-shell');
    const panel = element('section', 'login-panel');
    const heading = element('h1');
    heading.textContent = 'Configuration required';
    panel.append(heading, buildStatus(config.message, 'error'));
    main.append(panel);
    page.append(main);
  } else {
    page.append(buildLogin());
  }

  root.append(page);
}
