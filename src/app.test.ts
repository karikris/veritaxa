import { beforeEach, describe, expect, it, vi } from 'vitest';

import { VeriTaxaApp } from './app';
import type { ReviewBatch, ReviewItem } from './domain/reviewQueue';
import type { AuthEventHandler, ReviewRepository } from './data/reviewRepository';
import { ReviewConflictError, ReviewerAccessDisabledError } from './data/reviewRepository';

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
  });

  it('does not request batches or images before authentication', async () => {
    const repo = repository({ signedIn: false });
    const app = createApp(repo);

    await app.start();

    expect(document.querySelector('input[name="name"]')).not.toBeNull();
    expect(document.querySelector('input[type="email"]')).toBeNull();
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(document.querySelectorAll('[role="tab"]')).toHaveLength(0);
    expect(document.querySelector('nav')).toBeNull();
    expect(repo.listBatches).not.toHaveBeenCalled();
    expect(repo.getCursor).not.toHaveBeenCalled();
    app.dispose();
  });

  it('remembers the submitted name and starts the review immediately', async () => {
    const repo = repository({ signedIn: false });
    const app = createApp(repo);
    await app.start();

    const name = document.querySelector<HTMLInputElement>('input[name="name"]');
    if (!name) throw new Error('Name field is missing');
    name.value = '  Remembered reviewer  ';
    document
      .querySelector<HTMLFormElement>('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));

    await vi.waitFor(() => expect(repo.signIn).toHaveBeenCalledWith('Remembered reviewer'));
    expect(window.localStorage.getItem('veritaxa:reviewer-name')).toBe('Remembered reviewer');
    await vi.waitFor(() => expect(document.querySelector('img.review-image')).not.toBeNull());

    await repo.signOut();
    expect(document.querySelector<HTMLInputElement>('input[name="name"]')?.value).toBe(
      'Remembered reviewer',
    );
    app.dispose();
  });

  it('signs out an authenticated user whose reviewer profile is inactive', async () => {
    const repo = repository();
    repo.listBatches.mockRejectedValue(new ReviewerAccessDisabledError());
    const app = createApp(repo);

    await app.start();

    expect(repo.signOut).toHaveBeenCalledOnce();
    expect(document.body.textContent).toContain('This reviewer profile is inactive.');
    expect(document.querySelector('input[name="name"]')).not.toBeNull();
    expect(document.querySelector('input[type="email"]')).toBeNull();
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(repo.getCursor).not.toHaveBeenCalled();
    app.dispose();
  });

  it('renders one image, its target option, navigation, and all canonical labels', async () => {
    const repo = repository();
    const app = createApp(repo);

    await app.start();

    expect(document.querySelectorAll('img.review-image')).toHaveLength(1);
    expect(document.querySelector('img')?.alt).toBe('Image under review');
    const image = document.querySelector<HTMLImageElement>('img.review-image');
    const zoomOut = document.querySelector<HTMLButtonElement>('[aria-label="Zoom out"]');
    const resetZoom = document.querySelector<HTMLButtonElement>('[aria-label^="Reset image zoom"]');
    const zoomIn = document.querySelector<HTMLButtonElement>('[aria-label="Zoom in"]');
    expect(image?.dataset.zoom).toBe('1');
    expect(zoomOut?.disabled).toBe(true);
    expect(resetZoom?.textContent).toBe('100%');
    expect(resetZoom?.disabled).toBe(true);
    expect(zoomIn?.disabled).toBe(false);
    zoomIn?.click();
    expect(image?.dataset.zoom).toBe('1.25');
    expect(zoomOut?.disabled).toBe(false);
    expect(resetZoom?.textContent).toBe('125%');
    resetZoom?.click();
    expect(image?.dataset.zoom).toBe('1');
    expect(resetZoom?.textContent).toBe('100%');
    expect(document.querySelectorAll('input[name="review-label"]')).toHaveLength(16);
    expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2');
    expect(
      document.querySelector<HTMLButtonElement>('[aria-label="Previous image"]'),
    ).not.toBeNull();
    expect(document.querySelector<HTMLButtonElement>('[aria-label="Next image"]')).not.toBeNull();
    expect(document.body.textContent).toContain('Target scientific name');
    expect(document.body.textContent).toContain('Papilio exemplaris');
    expect(
      document.querySelector<HTMLInputElement>('input[value="target_scientific_name"]'),
    ).not.toBeNull();
    expect(document.body.textContent).not.toContain('Taxon example');
    app.dispose();
  });

  it.each(['resolve', 'reject'] as const)('ignores a save %s after sign-out', async (outcome) => {
    const save = deferred<ReviewItem>();
    const repo = repository({ save: () => save.promise });
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
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
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
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
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
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

  it('ignores errors from a detached image while preserving the active fallback', async () => {
    const repo = repository({
      getCursor: (_batchId, _anchor, direction) =>
        Promise.resolve(direction === 'next' ? secondItem : firstItem),
    });
    const app = createApp(repo);
    await app.start();
    const firstImage = document.querySelector<HTMLImageElement>('img');
    firstImage?.dispatchEvent(new Event('error'));
    expect(firstImage?.src).toBe(firstItem.fallbackImageUrl);
    document.querySelector<HTMLButtonElement>('[aria-label="Next image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    const currentImage = document.querySelector('img');
    firstImage?.dispatchEvent(new Event('error'));
    expect(app.state).toBe('reviewing');
    expect(document.querySelector('img')).toBe(currentImage);
    currentImage?.dispatchEvent(new Event('error'));
    expect(app.state).toBe('image_error');
    app.dispose();
  });

  it('keeps a pending save locked when its image fails', async () => {
    const save = deferred<ReviewItem>();
    const repo = repository({ save: () => save.promise });
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    const image = document.querySelector('img');
    image?.dispatchEvent(new Event('error'));
    image?.dispatchEvent(new Event('error'));
    expect(app.state).toBe('saving');
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    expect(repo.saveReview).toHaveBeenCalledOnce();
    save.resolve(secondItem);
    await vi.waitFor(() => expect(app.state).toBe('reviewing'));
    app.dispose();
  });

  it('omits the target choice when the campaign has no scientific name', async () => {
    const app = createApp(repository({ cursor: secondItem }));

    await app.start();

    expect(document.querySelectorAll('input[name="review-label"]')).toHaveLength(15);
    expect(document.body.textContent).not.toContain('Target scientific name');
    expect(
      document.querySelector<HTMLInputElement>('input[value="target_scientific_name"]'),
    ).toBeNull();
    app.dispose();
  });

  it('waits for save confirmation before advancing and preserves the draft on failure', async () => {
    let rejectSave: (error: Error) => void = () => undefined;
    const save = new Promise<ReviewItem>((_resolve, reject) => {
      rejectSave = reject;
    });
    const repo = repository({ save: () => save });
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

  it('renders the next item returned by the confirmed save without another cursor request', async () => {
    let resolveSave: (item: ReviewItem) => void = () => undefined;
    const save = new Promise<ReviewItem>((resolve) => {
      resolveSave = resolve;
    });
    const repo = repository({ save: () => save });
    const app = createApp(repo);
    await app.start();

    document.querySelector<HTMLInputElement>('input[value="moth"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    expect(document.querySelector('img')?.src).toContain('review-001-small.jpg');

    resolveSave({ ...secondItem, reviewedCount: 1 });
    await vi.waitFor(() => expect(document.querySelector('img')?.src).toContain('review-002.jpg'));
    expect(repo.getCursor).toHaveBeenCalledOnce();
    expect(repo.saveReview).toHaveBeenCalledWith(
      expect.objectContaining({
        expectedVersion: 0,
        itemId: firstItem.id,
        label: 'moth',
      }),
    );
    expect(document.querySelector('.classification-panel')).toBe(document.activeElement);
    app.dispose();
  });

  it('navigates reviewed and unreviewed items and restores unsaved drafts', async () => {
    const getCursor: ReviewRepository['getCursor'] = (_batchId, _anchorPosition, direction) =>
      Promise.resolve(direction === 'next' ? secondItem : firstItem);
    const repo = repository({ getCursor });
    const app = createApp(repo);
    await app.start();

    document.querySelector<HTMLInputElement>('input[value="adult_butterfly"]')?.click();
    const textarea = document.querySelector<HTMLTextAreaElement>('textarea');
    if (!textarea) throw new Error('Comment field is missing');
    textarea.value = 'Unsaved correction';
    textarea.dispatchEvent(new Event('input', { bubbles: true }));

    document.querySelector<HTMLButtonElement>('[aria-label="Next image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    expect(
      document.querySelector<HTMLInputElement>('input[name="review-label"]:checked'),
    ).toBeNull();

    document.querySelector<HTMLButtonElement>('[aria-label="Previous image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2'),
    );
    expect(
      document.querySelector<HTMLInputElement>('input[value="adult_butterfly"]')?.checked,
    ).toBe(true);
    expect(document.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe(
      'Unsaved correction',
    );
    expect(repo.saveReview).not.toHaveBeenCalled();
    app.dispose();
  });

  it('preserves the original version of an unsaved draft when another tab changes the answer', async () => {
    const repo = repository();
    repo.getCursor
      .mockResolvedValueOnce({ ...firstItem, currentLabel: 'moth', currentVersion: 1 })
      .mockResolvedValueOnce(secondItem)
      .mockResolvedValueOnce({ ...firstItem, currentLabel: 'bird', currentVersion: 2 });
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('[aria-label="Next image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    document.querySelector<HTMLButtonElement>('[aria-label="Previous image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2'),
    );
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    expect(repo.saveReview).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'plant', expectedVersion: 1 }),
    );
    app.dispose();
  });

  it('retries an immutable original request and retains newer edits after confirmation', async () => {
    const repo = repository();
    repo.saveReview.mockRejectedValueOnce(new Error('Response lost')).mockResolvedValue(secondItem);
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    const textarea = document.querySelector<HTMLTextAreaElement>('textarea');
    if (!textarea) throw new Error('Missing comment');
    textarea.value = 'Original note';
    textarea.dispatchEvent(new Event('input'));
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    await vi.waitFor(() => expect(app.state).toBe('save_error'));
    const original = repo.saveReview.mock.calls[0]?.[0];
    expect(Object.isFrozen(original)).toBe(true);
    document.querySelector<HTMLInputElement>('input[value="bird"]')?.click();
    const newerComment = document.querySelector<HTMLTextAreaElement>('textarea');
    if (!newerComment) throw new Error('Missing comment');
    newerComment.value = 'Newer note';
    newerComment.dispatchEvent(new Event('input'));
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    await vi.waitFor(() => expect(app.state).toBe('reviewing'));
    expect(repo.saveReview.mock.calls[1]?.[0]).toBe(original);
    expect(original).toMatchObject({
      label: 'plant',
      comment: 'Original note',
      expectedVersion: 0,
    });
    expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2');
    expect(document.querySelector<HTMLInputElement>('input[value="bird"]')?.checked).toBe(true);
    expect(document.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Newer note');
    expect(document.body.textContent).toContain('Your newer changes are still unsaved');
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    const newer = repo.saveReview.mock.calls[2]?.[0];
    expect(newer).toMatchObject({ label: 'bird', comment: 'Newer note', expectedVersion: 1 });
    expect(newer?.submissionId).not.toBe(original?.submissionId);
    app.dispose();
  });

  it('preserves an unknown submission across navigation and refreshed server versions', async () => {
    const repo = repository();
    repo.saveReview.mockRejectedValueOnce(new Error('Response lost'));
    repo.getCursor
      .mockResolvedValueOnce(firstItem)
      .mockResolvedValueOnce(secondItem)
      .mockResolvedValueOnce({ ...firstItem, currentLabel: 'plant', currentVersion: 1 });
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    await vi.waitFor(() => expect(app.state).toBe('save_error'));
    const original = repo.saveReview.mock.calls[0]?.[0];
    document.querySelector<HTMLButtonElement>('[aria-label="Next image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    document.querySelector<HTMLButtonElement>('[aria-label="Previous image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2'),
    );
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    expect(repo.saveReview.mock.calls[1]?.[0]).toBe(original);
    expect(original?.expectedVersion).toBe(0);
    app.dispose();
  });

  it.each(['stale_version', 'submission_conflict'] as const)(
    'requires an explicit comparison and reapply after %s',
    async (kind) => {
      const latest = {
        ...firstItem,
        currentLabel: 'bird' as const,
        currentComment: 'Saved elsewhere',
        currentVersion: 2,
      };
      const repo = repository();
      repo.saveReview.mockRejectedValueOnce(new ReviewConflictError(kind));
      repo.getCursor.mockResolvedValueOnce(firstItem).mockResolvedValueOnce(latest);
      const app = createApp(repo);
      await app.start();
      document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
      document.querySelector<HTMLButtonElement>('.send-button')?.click();
      await vi.waitFor(() => expect(app.state).toBe('save_error'));
      const original = repo.saveReview.mock.calls[0]?.[0];
      expect(repo.getCursor).toHaveBeenCalledOnce();
      expect(document.querySelector('.send-button')?.textContent).toBe('Compare saved answer');
      document.querySelector<HTMLButtonElement>('.send-button')?.click();
      await vi.waitFor(() => expect(document.querySelector('.conflict-comparison')).not.toBeNull());
      expect(repo.getCursor).toHaveBeenLastCalledWith(batch.id, 0, 'next', expect.any(AbortSignal));
      expect(document.querySelector('.conflict-comparison')?.textContent).toContain(
        'Saved elsewhere',
      );
      expect(document.querySelector<HTMLInputElement>('input[value="plant"]')?.checked).toBe(true);
      expect(repo.saveReview).toHaveBeenCalledOnce();
      const reapply = Array.from(document.querySelectorAll('button')).find(
        (node) => node.textContent === 'Reapply my changes',
      );
      reapply?.click();
      expect(app.state).toBe('reviewing');
      expect(repo.saveReview).toHaveBeenCalledOnce();
      document.querySelector<HTMLButtonElement>('.send-button')?.click();
      const newSubmission = repo.saveReview.mock.calls[1]?.[0];
      expect(newSubmission).toMatchObject({ label: 'plant', expectedVersion: 2 });
      expect(newSubmission?.submissionId).not.toBe(original?.submissionId);
      app.dispose();
    },
  );

  it('can accept the compared saved answer without writing to the database', async () => {
    const latest = {
      ...firstItem,
      currentLabel: 'bird' as const,
      currentComment: 'Keep this',
      currentVersion: 2,
    };
    const repo = repository();
    repo.saveReview.mockRejectedValueOnce(new ReviewConflictError('stale_version'));
    repo.getCursor.mockResolvedValueOnce(firstItem).mockResolvedValueOnce(latest);
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    await vi.waitFor(() => expect(app.state).toBe('save_error'));
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    await vi.waitFor(() => expect(document.querySelector('.conflict-comparison')).not.toBeNull());
    Array.from(document.querySelectorAll('button'))
      .find((node) => node.textContent === 'Use saved answer')
      ?.click();
    expect(document.querySelector<HTMLInputElement>('input[value="bird"]')?.checked).toBe(true);
    expect(document.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Keep this');
    expect(repo.saveReview).toHaveBeenCalledOnce();
    app.dispose();
  });

  it('does not compare another item when the original is unavailable', async () => {
    const repo = repository();
    repo.saveReview.mockRejectedValueOnce(new ReviewConflictError('stale_version'));
    repo.getCursor.mockResolvedValueOnce(firstItem).mockResolvedValueOnce(secondItem);
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    await vi.waitFor(() => expect(app.state).toBe('save_error'));
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    await vi.waitFor(() =>
      expect(document.body.textContent).toContain('Your draft has not changed'),
    );
    expect(document.querySelector('.conflict-comparison')).toBeNull();
    expect(document.querySelector<HTMLInputElement>('input[value="plant"]')?.checked).toBe(true);
    expect(repo.saveReview).toHaveBeenCalledOnce();
    app.dispose();
  });

  it('prefills an existing answer and allows it to be corrected', async () => {
    const reviewedItem: ReviewItem = {
      ...firstItem,
      currentLabel: 'moth',
      currentComment: 'Original answer',
      currentVersion: 3,
      reviewedCount: 1,
    };
    const repo = repository({
      cursor: reviewedItem,
      save: () =>
        Promise.resolve({
          ...secondItem,
          reviewedCount: 1,
        }),
    });
    const app = createApp(repo);
    await app.start();

    expect(document.querySelector<HTMLInputElement>('input[value="moth"]')?.checked).toBe(true);
    expect(document.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Original answer');
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();

    await vi.waitFor(() => expect(repo.saveReview).toHaveBeenCalledOnce());
    expect(repo.saveReview).toHaveBeenCalledWith(
      expect.objectContaining({
        expectedVersion: 3,
        itemId: firstItem.id,
        label: 'plant',
      }),
    );
    app.dispose();
  });

  it('keeps a completed batch navigable for corrections', async () => {
    const repo = repository({
      save: () =>
        Promise.resolve({
          ...firstItem,
          currentLabel: 'moth',
          currentVersion: 1,
          reviewedCount: 2,
          complete: true,
        }),
    });
    const app = createApp(repo);
    await app.start();

    document.querySelector<HTMLInputElement>('input[value="moth"]')?.click();
    document.querySelector<HTMLButtonElement>('.send-button')?.click();

    await vi.waitFor(() =>
      expect(document.body.textContent).toContain('All reviewed—answers can still be updated.'),
    );
    expect(document.querySelector('img.review-image')).not.toBeNull();
    expect(
      document.querySelector<HTMLButtonElement>('[aria-label="Previous image"]')?.disabled,
    ).toBe(false);
    expect(document.querySelector<HTMLInputElement>('input[value="moth"]')?.checked).toBe(true);
    app.dispose();
  });

  it('supports label shortcuts outside editable controls', async () => {
    const app = createApp(repository());
    await app.start();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', bubbles: true }));
    expect(
      document.querySelector<HTMLInputElement>('input[value="adult_butterfly"]')?.checked,
    ).toBe(true);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', bubbles: true }));
    expect(
      document.querySelector<HTMLInputElement>('input[value="target_scientific_name"]')?.checked,
    ).toBe(true);

    const textarea = document.querySelector<HTMLTextAreaElement>('textarea');
    textarea?.focus();
    textarea?.dispatchEvent(new KeyboardEvent('keydown', { key: 'm', bubbles: true }));
    expect(document.querySelector<HTMLInputElement>('input[value="moth"]')?.checked).toBe(false);
    app.dispose();
  });

  it('uses arrow navigation only outside editable fields', async () => {
    const repo = repository({
      getCursor: (_batchId, _anchorPosition, direction) =>
        Promise.resolve(direction === 'next' ? secondItem : firstItem),
    });
    const app = createApp(repo);
    await app.start();

    const textarea = document.querySelector<HTMLTextAreaElement>('textarea');
    textarea?.focus();
    textarea?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(repo.getCursor).toHaveBeenCalledOnce();

    document.body.focus();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    await vi.waitFor(() => expect(repo.getCursor).toHaveBeenCalledTimes(2));
    expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2');
    app.dispose();
  });
});
