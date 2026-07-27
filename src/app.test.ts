import { beforeEach, describe, expect, it, vi } from 'vitest';

import { VeriTaxaApp } from './app';
import type { ReviewBatch, ReviewItem, ReviewProgress } from './domain/reviewQueue';
import type { AuthEventHandler, ReviewRepository } from './data/reviewRepository';
import { ReviewerNotAuthorizedError } from './data/reviewRepository';
import { ImagePrefetch } from './image/imagePrefetch';

const batch: ReviewBatch = {
  id: '30000000-0000-0000-0000-000000000001',
  name: 'Batch SYNTH-001',
  code: 'SYNTH-001',
  reviewedCount: 0,
  totalCount: 2,
  complete: false,
};

const firstItem: ReviewItem = {
  id: '40000000-0000-0000-0000-000000000001',
  imageId: 'synthetic-image-001',
  displayUrl: 'https://images.example.invalid/review-001-small.jpg',
  fallbackImageUrl: 'https://images.example.invalid/review-001.jpg',
  position: 1,
  reviewedCount: 0,
  totalCount: 2,
};

const secondItem: ReviewItem = {
  id: '40000000-0000-0000-0000-000000000002',
  imageId: 'synthetic-image-002',
  displayUrl: null,
  fallbackImageUrl: 'https://images.example.invalid/review-002.jpg',
  position: 2,
  reviewedCount: 0,
  totalCount: 2,
};

type RepositoryOptions = {
  signedIn?: boolean;
  submit?: () => Promise<ReviewProgress>;
  queue?: ReviewItem[];
};

function repository(options: RepositoryOptions = {}): ReviewRepository & {
  listBatches: ReturnType<typeof vi.fn<ReviewRepository['listBatches']>>;
  getQueue: ReturnType<typeof vi.fn<ReviewRepository['getQueue']>>;
  signOut: ReturnType<typeof vi.fn<ReviewRepository['signOut']>>;
  submitReview: ReturnType<typeof vi.fn<ReviewRepository['submitReview']>>;
} {
  let authHandler: AuthEventHandler | null = null;
  const listBatches = vi.fn<ReviewRepository['listBatches']>().mockResolvedValue([batch]);
  const getQueue = vi
    .fn<ReviewRepository['getQueue']>()
    .mockResolvedValue(options.queue ?? [firstItem, secondItem]);
  const submitReview = vi
    .fn<ReviewRepository['submitReview']>()
    .mockImplementation(
      options.submit ??
        (() => Promise.resolve({ reviewedCount: 1, totalCount: 2, complete: false })),
    );
  const signOut = vi.fn<ReviewRepository['signOut']>().mockImplementation(() => {
    authHandler?.(null);
    return Promise.resolve();
  });
  return {
    getSession: () =>
      Promise.resolve(
        options.signedIn === false ? null : { email: 'allowed-reviewer@example.invalid' },
      ),
    onAuthStateChange: (handler) => {
      authHandler = handler;
      return () => {
        authHandler = null;
      };
    },
    sendMagicLink: () => Promise.resolve(),
    signOut,
    listBatches,
    getQueue,
    submitReview,
  };
}

function getRoot(): HTMLElement {
  const root = document.querySelector<HTMLElement>('#app');
  if (!root) throw new Error('Test root is missing');
  return root;
}

function createApp(repo: ReviewRepository): VeriTaxaApp {
  return new VeriTaxaApp(getRoot(), repo, {
    storage: window.localStorage,
    imagePrefetch: new ImagePrefetch(() => ({ src: '' })),
    locationHref: 'https://example.invalid/veritaxa/',
  });
}

describe('VeriTaxa application', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="app"></div>';
    window.localStorage.clear();
  });

  it('does not request batches or images before authentication', async () => {
    const repo = repository({ signedIn: false });
    const app = createApp(repo);

    await app.start();

    expect(document.querySelector('input[type="email"]')).not.toBeNull();
    expect(document.querySelectorAll('[role="tab"]')).toHaveLength(0);
    expect(document.querySelector('nav')).toBeNull();
    expect(repo.listBatches).not.toHaveBeenCalled();
    expect(repo.getQueue).not.toHaveBeenCalled();
    app.dispose();
  });

  it('signs out an authenticated user who is not allowlisted', async () => {
    const repo = repository();
    repo.listBatches.mockRejectedValue(new ReviewerNotAuthorizedError());
    const app = createApp(repo);

    await app.start();

    expect(repo.signOut).toHaveBeenCalledOnce();
    expect(document.body.textContent).toContain('This email is not approved for VeriTaxa.');
    expect(document.querySelector('input[type="email"]')).not.toBeNull();
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(repo.getQueue).not.toHaveBeenCalled();
    app.dispose();
  });

  it('renders one generic image and all canonical labels for an authorised session', async () => {
    const repo = repository();
    const app = createApp(repo);

    await app.start();

    expect(document.querySelectorAll('img.review-image')).toHaveLength(1);
    expect(document.querySelector('img')?.alt).toBe('Image under review');
    expect(document.querySelectorAll('input[name="review-label"]')).toHaveLength(15);
    expect(document.body.textContent).not.toContain('hidden');
    expect(document.body.textContent).not.toContain('Taxon example');
    app.dispose();
  });

  it('waits for save confirmation before advancing and preserves the draft on failure', async () => {
    let rejectSave: (error: Error) => void = () => undefined;
    const save = new Promise<ReviewProgress>((_resolve, reject) => {
      rejectSave = reject;
    });
    const repo = repository({ submit: () => save });
    const app = createApp(repo);
    await app.start();

    const firstRadio = document.querySelector<HTMLInputElement>('input[name="review-label"]');
    firstRadio?.click();
    const textarea = document.querySelector<HTMLTextAreaElement>('textarea');
    if (textarea) {
      textarea.value = 'Synthetic note';
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }
    document.querySelector<HTMLButtonElement>('.send-button')?.click();

    expect(document.querySelector('img')?.src).toContain('review-001-small.jpg');
    rejectSave(new Error('Synthetic save failure'));
    await vi.waitFor(() => expect(document.body.textContent).toContain('Synthetic save failure'));

    expect(document.querySelector('img')?.src).toContain('review-001-small.jpg');
    expect(
      document.querySelector<HTMLInputElement>('input[name="review-label"]:checked'),
    ).not.toBeNull();
    expect(document.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Synthetic note');
    expect(document.querySelector('.send-button')?.textContent).toBe('Retry save');
    app.dispose();
  });

  it('supports label shortcuts outside editable controls', async () => {
    const app = createApp(repository());
    await app.start();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', bubbles: true }));
    expect(
      document.querySelector<HTMLInputElement>('input[value="adult_butterfly"]')?.checked,
    ).toBe(true);

    const textarea = document.querySelector<HTMLTextAreaElement>('textarea');
    textarea?.focus();
    textarea?.dispatchEvent(new KeyboardEvent('keydown', { key: 'm', bubbles: true }));
    expect(document.querySelector<HTMLInputElement>('input[value="moth"]')?.checked).toBe(false);
    app.dispose();
  });
});
