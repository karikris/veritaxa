import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { VeriTaxaApp } from './app';
import type { ReviewBatch, ReviewItem } from './domain/reviewQueue';
import type { AuthEventHandler, ReviewRepository } from './data/reviewRepository';

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
  targetScientificName: 'Papilio exemplaris',
  displayUrl: 'https://images.example.invalid/review-001-small.jpg',
  fallbackImageUrl: 'https://images.example.invalid/review-001.jpg',
  position: 1,
  currentLabel: null,
  currentComment: null,
  currentVersion: 0,
  reviewedCount: 0,
  totalCount: 2,
  complete: false,
};

const secondItem: ReviewItem = {
  id: '40000000-0000-0000-0000-000000000002',
  imageId: 'synthetic-image-002',
  targetScientificName: null,
  displayUrl: null,
  fallbackImageUrl: 'https://images.example.invalid/review-002.jpg',
  position: 2,
  currentLabel: null,
  currentComment: null,
  currentVersion: 0,
  reviewedCount: 0,
  totalCount: 2,
  complete: false,
};

type RepositoryOptions = {
  signedIn?: boolean;
  save?: () => Promise<ReviewItem>;
  cursor?: ReviewItem | null;
  getCursor?: ReviewRepository['getCursor'];
};

function repository(options: RepositoryOptions = {}): ReviewRepository & {
  emitAuth: AuthEventHandler;
  listBatches: ReturnType<typeof vi.fn<ReviewRepository['listBatches']>>;
  getCursor: ReturnType<typeof vi.fn<ReviewRepository['getCursor']>>;
  signIn: ReturnType<typeof vi.fn<ReviewRepository['signIn']>>;
  signOut: ReturnType<typeof vi.fn<ReviewRepository['signOut']>>;
  saveReview: ReturnType<typeof vi.fn<ReviewRepository['saveReview']>>;
} {
  let authHandler: AuthEventHandler | null = null;
  const listBatches = vi.fn<ReviewRepository['listBatches']>().mockResolvedValue([batch]);
  const getCursor = vi
    .fn<ReviewRepository['getCursor']>()
    .mockImplementation(options.getCursor ?? (() => Promise.resolve(options.cursor ?? firstItem)));
  const saveReview = vi.fn<ReviewRepository['saveReview']>().mockImplementation(
    options.save ??
      (() =>
        Promise.resolve({
          ...secondItem,
          reviewedCount: 1,
        })),
  );
  const signIn = vi.fn<ReviewRepository['signIn']>().mockImplementation((identifiedBy: string) => {
    authHandler?.({
      userId: '10000000-0000-0000-0000-000000000001',
      identifiedBy,
    });
    return Promise.resolve();
  });
  const signOut = vi.fn<ReviewRepository['signOut']>().mockImplementation(() => {
    authHandler?.(null);
    return Promise.resolve();
  });
  return {
    emitAuth: (session) => authHandler?.(session),
    getSession: () =>
      Promise.resolve(
        options.signedIn === false
          ? null
          : {
              userId: '10000000-0000-0000-0000-000000000001',
              identifiedBy: 'Synthetic reviewer',
            },
      ),
    onAuthStateChange: (handler) => {
      authHandler = handler;
      return () => {
        authHandler = null;
      };
    },
    signIn,
    signOut,
    listBatches,
    getCursor,
    saveReview,
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
  });
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  let reject: (error: Error) => void = () => undefined;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

describe('VeriTaxa application', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="app"></div>';
    window.localStorage.clear();
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe = vi.fn();
        disconnect = vi.fn();
      },
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  it('shows an initial cursor error and retries without mounting duplicate review controls', async () => {
    const repo = repository();
    repo.getCursor.mockRejectedValueOnce(new Error('Synthetic queue error'));
    const app = createApp(repo);
    await app.start();
    const error = document.querySelector<HTMLElement>('.queue-error');
    expect(error?.hidden).toBe(false);
    expect(error?.textContent).toBe('Synthetic queue error');
    const retry = document.querySelector<HTMLButtonElement>('.retry-image');
    expect(retry?.hidden).toBe(false);
    expect(retry?.disabled).toBe(false);
    retry?.click();
    await vi.waitFor(() => expect(app.state).toBe('reviewing'));
    expect(document.querySelectorAll('.classification-panel')).toHaveLength(1);
    expect(error?.hidden).toBe(true);
    expect(error?.textContent).toBe('');
    app.dispose();
  });

  it.each(['resolve', 'reject'] as const)('ignores a save %s after sign-out', async (outcome) => {
    const save = deferred<ReviewItem>();
    const repo = repository({ save: () => save.promise });
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLButtonElement>('[data-label="target_not_present"]')?.click();

    expect(app.state).toBe('saving');
    await repo.signOut();
    expect(app.state).toBe('signed_out');
    if (outcome === 'resolve') save.resolve(secondItem);
    else save.reject(new Error('Old account save failed'));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    expect(app.state).toBe('signed_out');
    expect(document.body.textContent).not.toContain('Old account save failed');
    expect(document.querySelector('img')).toBeNull();
    app.dispose();
  });

  it('clears drafts and rejects stale saves on direct account replacement', async () => {
    const save = deferred<ReviewItem>();
    const repo = repository({ save: () => save.promise });
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLButtonElement>('[data-label="target_not_present"]')?.click();

    repo.emitAuth({ userId: 'synthetic-other-reviewer', identifiedBy: 'Other reviewer' });
    await vi.waitFor(() => expect(app.state).toBe('reviewing'));
    save.resolve(secondItem);
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2');
    expect(document.querySelector('input:checked')).toBeNull();
    expect(document.querySelector('.save-state')?.textContent).toBe('');
    app.dispose();
  });

  it.each(['resolve', 'reject'] as const)('ignores a save %s after disposal', async (outcome) => {
    const save = deferred<ReviewItem>();
    const repo = repository({ save: () => save.promise });
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLButtonElement>('[data-label="target_not_present"]')?.click();

    app.dispose();
    getRoot().textContent = 'Replacement application';
    if (outcome === 'resolve') save.resolve(secondItem);
    else save.reject(new Error('Disposed save failed'));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    expect(getRoot().textContent).toBe('Replacement application');
  });

  it.each(['resolve', 'reject'] as const)(
    'does not let an initial session %s overwrite a newer auth event',
    async (outcome) => {
      const session = deferred<Awaited<ReturnType<ReviewRepository['getSession']>>>();
      const repo = repository();
      repo.getSession = () => session.promise;
      const app = createApp(repo);
      const starting = app.start();
      repo.emitAuth({ userId: 'synthetic-current-reviewer', identifiedBy: 'Current reviewer' });
      await vi.waitFor(() => expect(app.state).toBe('reviewing'));
      if (outcome === 'resolve') session.resolve(null);
      else session.reject(new Error('Stale restoration error'));
      await starting;
      expect(app.state).toBe('reviewing');
      expect(repo.listBatches).toHaveBeenCalledOnce();
      app.dispose();
    },
  );

  it('does not restart or attach keyboard handlers after disposal during initial restore', async () => {
    const session = deferred<Awaited<ReturnType<ReviewRepository['getSession']>>>();
    const repo = repository();
    repo.getSession = () => session.promise;
    const app = createApp(repo);
    const starting = app.start();
    app.dispose();
    getRoot().textContent = 'Replacement application';
    session.resolve({ userId: 'synthetic-old-reviewer', identifiedBy: null });
    await starting;
    await app.start();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'p', bubbles: true }));
    expect(getRoot().textContent).toBe('Replacement application');
    expect(repo.listBatches).not.toHaveBeenCalled();
  });

  it('ignores detached image errors while source inspection remains explicitly owned', async () => {
    const repo = repository({
      getCursor: (_batchId, _anchor, direction) =>
        Promise.resolve(direction === 'next' ? secondItem : firstItem),
    });
    const app = createApp(repo);
    await app.start();
    const firstImage = document.querySelector<HTMLImageElement>('img');
    firstImage?.dispatchEvent(new Event('error'));
    expect(document.querySelector('img')).toBeNull();
    document.querySelector<HTMLButtonElement>('.image-source-button')?.click();
    const firstOriginal = document.querySelector<HTMLImageElement>('img');
    expect(firstOriginal?.src).toBe(firstItem.fallbackImageUrl);
    document.querySelector<HTMLButtonElement>('[aria-label="Next image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    const currentImage = document.querySelector('img');
    expect(currentImage).toBeNull();
    document.querySelector<HTMLButtonElement>('.image-source-button')?.click();
    const inspectedImage = document.querySelector('img');
    firstImage?.dispatchEvent(new Event('error'));
    firstOriginal?.dispatchEvent(new Event('error'));
    expect(app.state).toBe('reviewing');
    expect(document.querySelector('img')).toBe(inspectedImage);
    inspectedImage?.dispatchEvent(new Event('error'));
    expect(app.state).toBe('image_error');
    app.dispose();
  });

  it('falls back on the same node only when the source is a supplied bounded rendition', async () => {
    const bounded = 'https://live.' + 'staticflickr.com' + '/1/1_0000000000_b.jpg';
    const app = createApp(repository({ cursor: { ...firstItem, fallbackImageUrl: bounded } }));
    await app.start();
    const image = document.querySelector('img');
    image?.dispatchEvent(new Event('error'));
    expect(document.querySelector('img')).toBe(image);
    expect(image?.src).toBe(bounded);
    image?.dispatchEvent(new Event('error'));
    expect(document.querySelector('img')).toBeNull();
    app.dispose();
  });

  it('keeps a pending save locked when its image fails', async () => {
    const save = deferred<ReviewItem>();
    const repo = repository({ save: () => save.promise });
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLButtonElement>('[data-label="target_not_present"]')?.click();

    const image = document.querySelector('img');
    image?.dispatchEvent(new Event('error'));
    image?.dispatchEvent(new Event('error'));
    expect(app.state).toBe('saving');
    document
      .querySelector<HTMLButtonElement>('.image-source-button')
      ?.dispatchEvent(new Event('click'));
    expect(document.querySelector('img')).toBeNull();
    expect(app.state).toBe('saving');

    expect(repo.saveReview).toHaveBeenCalledOnce();
    save.resolve(secondItem);
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    expect(app.state).toBe('image_error');
    expect(document.querySelector<HTMLButtonElement>('.image-source-button')?.disabled).toBe(false);
    app.dispose();
  });
});
