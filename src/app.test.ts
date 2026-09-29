import { beforeEach, describe, expect, it, vi } from 'vitest';

import { VeriTaxaApp } from './app';
import type { ReviewBatch, ReviewItem } from './domain/reviewQueue';
import type { AuthEventHandler, ReviewRepository } from './data/reviewRepository';
import { ReviewConflictError, ReviewerAccessDisabledError } from './data/reviewRepository';
import * as text from './domain/text';

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

  it('preserves the mounted review nodes, focus, selection and zoom through edits and save status', async () => {
    const save = deferred<ReviewItem>();
    const app = createApp(repository({ save: () => save.promise }));
    await app.start();
    const selectors = [
      '.app-shell',
      '.site-header',
      '#batch-select',
      '.review-main',
      '.image-stage',
      'img.review-image',
      '.image-zoom-controls',
      '.classification-panel',
      'input[value="plant"]',
      '#review-comment',
      '.send-button',
    ];
    const nodes = selectors.map((selector) => document.querySelector(selector));
    const image = document.querySelector<HTMLImageElement>('img');
    const radio = document.querySelector<HTMLInputElement>('input[value="plant"]');
    const comment = document.querySelector<HTMLTextAreaElement>('#review-comment');
    if (!image || !radio || !comment) throw new Error('Review controls are missing');
    const setSource = vi.spyOn(image, 'src', 'set');
    const replaceRoot = vi.spyOn(getRoot(), 'replaceChildren');
    document.querySelector<HTMLButtonElement>('[aria-label="Zoom in"]')?.click();
    radio.focus();
    radio.click();
    expect(document.activeElement).toBe(radio);
    comment.focus();
    comment.value = 'Synthetic 🦋 comment';
    comment.setSelectionRange(3, 7);
    comment.dispatchEvent(new Event('input', { bubbles: true }));
    expect(document.activeElement).toBe(comment);
    expect([comment.selectionStart, comment.selectionEnd]).toEqual([3, 7]);
    expect(image.dataset.zoom).toBe('1.25');
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    expect(app.state).toBe('saving');
    selectors.forEach((selector, index) =>
      expect(document.querySelector(selector)).toBe(nodes[index]),
    );
    save.reject(new Error('Synthetic failure'));
    await vi.waitFor(() => expect(app.state).toBe('save_error'));
    selectors.forEach((selector, index) =>
      expect(document.querySelector(selector)).toBe(nodes[index]),
    );
    expect(setSource).not.toHaveBeenCalled();
    expect(replaceRoot).not.toHaveBeenCalled();
    app.dispose();
  });

  it('keeps classification and navigation controls across items but releases replaced image sources', async () => {
    const repo = repository({
      getCursor: (_batch, _anchor, direction) =>
        Promise.resolve(direction === 'next' ? secondItem : firstItem),
    });
    const app = createApp(repo);
    await app.start();
    const original = document.querySelector('img');
    const target = document.querySelector('input[value="target_scientific_name"]');
    const plant = document.querySelector('input[value="plant"]');
    const next = document.querySelector<HTMLButtonElement>('[aria-label="Next image"]');
    next?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    expect(document.querySelector('img')).not.toBe(original);
    expect(original?.getAttribute('src')).toBeNull();
    expect(original?.onerror).toBeNull();
    expect(document.querySelector('input[value="target_scientific_name"]')).toBeNull();
    expect(document.querySelector('input[value="plant"]')).toBe(plant);
    expect(document.querySelector('[aria-label="Next image"]')).toBe(next);
    document.querySelector<HTMLButtonElement>('[aria-label="Previous image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2'),
    );
    expect(document.querySelector('input[value="target_scientific_name"]')).toBe(target);
    const image = document.querySelector('img');
    await repo.signOut();
    expect(image?.getAttribute('src')).toBeNull();
    expect(document.querySelector('img')).toBeNull();
    app.dispose();
  });

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

  it.each(['retry', 'change batch'] as const)(
    'releases an initial cursor failure for %s without accepting duplicate retries',
    async (recovery) => {
      const repo = repository();
      const otherBatch = { ...batch, id: '30000000-0000-0000-0000-000000000002' };
      const pending = deferred<ReviewItem>();
      repo.listBatches.mockResolvedValue([batch, otherBatch]);
      repo.getCursor
        .mockRejectedValueOnce(new Error('Synthetic initial cursor failure'))
        .mockReturnValueOnce(pending.promise);
      const app = createApp(repo);
      await app.start();
      const selector = document.querySelector<HTMLSelectElement>('#batch-select');
      const retry = document.querySelector<HTMLButtonElement>('.retry-image');
      if (!selector || !retry) throw new Error('Missing recovery controls');
      expect(app.state).toBe('navigation_error');
      expect(selector.disabled).toBe(false);
      expect(retry.disabled).toBe(false);
      expect(document.querySelector('img')).toBeNull();

      if (recovery === 'retry') retry.click();
      else {
        selector.value = otherBatch.id;
        selector.dispatchEvent(new Event('change', { bubbles: true }));
      }
      expect(app.state).toBe('loading_image');
      expect(selector.disabled).toBe(true);
      expect(retry.disabled).toBe(true);
      expect(repo.getCursor).toHaveBeenCalledTimes(2);
      expect(repo.getCursor.mock.lastCall?.slice(0, 3)).toEqual([
        recovery === 'retry' ? batch.id : otherBatch.id,
        null,
        'resume',
      ]);
      retry.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      expect(repo.getCursor).toHaveBeenCalledTimes(2);
      expect(repo.getCursor.mock.lastCall?.[3].aborted).toBe(false);

      pending.resolve(firstItem);
      await vi.waitFor(() => expect(app.state).toBe('reviewing'));
      expect(selector.disabled).toBe(false);
      expect(document.querySelectorAll('.classification-panel')).toHaveLength(1);
      app.dispose();
    },
  );

  it.each(['discard', 'save', 'retry'] as const)(
    'requires explicit %s resolution at the draft limit without evicting other work',
    async (resolution) => {
      const itemAt = (position: number): ReviewItem => ({
        ...firstItem,
        id: `40000000-0000-0000-0000-${String(position).padStart(12, '0')}`,
        position,
        totalCount: 1000,
      });
      const repo = repository({
        getCursor: (_batchId, anchor, direction) =>
          Promise.resolve(
            itemAt(direction === 'resume' ? 1 : (anchor ?? 0) + (direction === 'next' ? 1 : -1)),
          ),
        save: () => Promise.resolve(itemAt(257)),
      });
      const alternate = { ...batch, id: '30000000-0000-0000-0000-000000000002' };
      repo.listBatches.mockResolvedValue([batch, alternate]);
      if (resolution === 'retry')
        repo.saveReview.mockRejectedValueOnce(new Error('Synthetic unknown save outcome'));
      const app = createApp(repo);
      await app.start();
      const radio = document.querySelector<HTMLInputElement>('input[value="plant"]');
      const comment = document.querySelector<HTMLTextAreaElement>('#review-comment');
      const next = document.querySelector<HTMLButtonElement>('[aria-label="Next image"]');
      if (!radio || !comment || !next) throw new Error('Review controls are missing');
      for (let position = 1; position <= 256; position += 1) {
        radio.click();
        comment.value = `Unsaved ${String(position)}`;
        comment.dispatchEvent(new Event('input', { bubbles: true }));
        next.click();
        await new Promise<void>((resolve) => queueMicrotask(resolve));
      }
      expect(repo.getCursor).toHaveBeenCalledTimes(256);
      expect(document.querySelector('.image-position')?.textContent).toBe('256 / 1000');
      expect(comment.value).toBe('Unsaved 256');
      expect(document.querySelector<HTMLElement>('.draft-limit')?.hidden).toBe(false);
      const select = document.querySelector<HTMLSelectElement>('#batch-select');
      if (!select) throw new Error('Batch selector is missing');
      select.value = alternate.id;
      select.dispatchEvent(new Event('change'));
      expect(select.value).toBe(batch.id);
      expect(repo.getCursor).toHaveBeenCalledTimes(256);
      const discard = document.querySelector<HTMLButtonElement>('.discard-draft');
      if (resolution === 'discard') {
        discard?.click();
        expect(comment.value).toBe('');
        expect(repo.saveReview).not.toHaveBeenCalled();
        next.click();
      } else {
        document.querySelector<HTMLButtonElement>('.send-button')?.click();
        if (resolution === 'retry') {
          await vi.waitFor(() => expect(app.state).toBe('save_error'));
          expect(discard?.disabled).toBe(true);
          expect(document.querySelector('.draft-limit')?.textContent).toContain(
            'may already have committed',
          );
          discard?.dispatchEvent(new Event('click'));
          expect(comment.value).toBe('Unsaved 256');
          document.querySelector<HTMLButtonElement>('.send-button')?.click();
        }
      }
      await vi.waitFor(() =>
        expect(document.querySelector('.image-position')?.textContent).toBe('257 / 1000'),
      );
      expect(document.querySelector<HTMLElement>('.draft-limit')?.hidden).toBe(true);
      repo.getCursor.mockResolvedValueOnce(itemAt(1));
      document.querySelector<HTMLButtonElement>('[aria-label="Previous image"]')?.click();
      await vi.waitFor(() => expect(comment.value).toBe('Unsaved 1'));
      expect(radio.checked).toBe(true);
      app.dispose();
    },
    15000,
  );

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

  it('releases an oversized preview, permits explicit source inspection and ignores its detached load callback', async () => {
    const app = createApp(repository());
    await app.start();
    const image = document.querySelector('img');
    if (!image) throw new Error('Preview is missing');
    Object.defineProperty(image, 'naturalWidth', { value: 3200 });
    Object.defineProperty(image, 'naturalHeight', { value: 2400 });
    const staleLoad = image.onload;
    image.dispatchEvent(new Event('load'));
    expect(document.querySelector('img')).toBeNull();
    expect(image.getAttribute('src')).toBeNull();
    expect(image.onload).toBeNull();
    expect(document.body.textContent).toContain('Preview exceeded 1,600 pixels');
    document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
    document.querySelector<HTMLButtonElement>('.image-source-button')?.click();
    const source = document.querySelector('img');
    expect(source?.src).toBe(firstItem.fallbackImageUrl);
    staleLoad?.call(image, new Event('load'));
    expect(document.querySelector('img')).toBe(source);
    if (!source) throw new Error('Source image is missing');
    Object.defineProperty(source, 'naturalWidth', { value: 3200 });
    source.dispatchEvent(new Event('load'));
    expect(document.querySelector('img')).toBe(source);
    document.querySelector<HTMLButtonElement>('.image-source-button')?.click();
    expect(source.getAttribute('src')).toBeNull();
    expect(source.onload).toBeNull();
    expect(document.querySelector('img')?.src).toBe(firstItem.displayUrl);
    expect(document.querySelector<HTMLInputElement>('input[value="plant"]')?.checked).toBe(true);
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
    document
      .querySelector<HTMLButtonElement>('.image-source-button')
      ?.dispatchEvent(new Event('click'));
    expect(document.querySelector('img')).toBeNull();
    expect(app.state).toBe('saving');
    document.querySelector<HTMLButtonElement>('.send-button')?.click();
    expect(repo.saveReview).toHaveBeenCalledOnce();
    save.resolve(secondItem);
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    expect(app.state).toBe('image_error');
    expect(document.querySelector<HTMLButtonElement>('.image-source-button')?.disabled).toBe(false);
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
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    expect(document.querySelector('img')).toBeNull();
    document.querySelector<HTMLButtonElement>('.image-source-button')?.click();
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

  it.each(['saving', 'loading_image'] as const)(
    'keeps keyboard and control capabilities aligned while %s',
    async (operation) => {
      const pending = deferred<ReviewItem>();
      const repo = repository({ save: () => pending.promise });
      const app = createApp(repo);
      await app.start();
      const label = document.querySelector<HTMLInputElement>('input[value="moth"]');
      const comment = document.querySelector<HTMLTextAreaElement>('#review-comment');
      const next = document.querySelector<HTMLButtonElement>('[aria-label="Next image"]');
      const send = document.querySelector<HTMLButtonElement>('.send-button');
      const selector = document.querySelector<HTMLSelectElement>('#batch-select');
      const source = document.querySelector<HTMLButtonElement>('.image-source-button');
      if (!label || !comment || !next || !send || !selector || !source)
        throw new Error('Missing review controls');
      label.click();
      comment.value = 'Original draft';
      comment.dispatchEvent(new Event('input', { bubbles: true }));
      if (operation === 'saving') send.click();
      else {
        repo.getCursor.mockReturnValueOnce(pending.promise);
        next.click();
      }
      expect(app.state).toBe(operation);
      const cursorCalls = repo.getCursor.mock.calls.length;
      const saveCalls = repo.saveReview.mock.calls.length;
      const image = document.querySelector('img');
      for (const control of [label, comment, next, send, selector, source])
        expect(control.disabled).toBe(true);

      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', bubbles: true }));
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      comment.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }),
      );
      // Queued/programmatic events do not gain authority from a mutable DOM flag.
      selector.disabled = false;
      selector.dispatchEvent(new Event('change', { bubbles: true }));
      comment.disabled = false;
      comment.value = 'Ignored while busy';
      comment.dispatchEvent(new Event('input', { bubbles: true }));
      next.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      source.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      expect(repo.getCursor).toHaveBeenCalledTimes(cursorCalls);
      expect(repo.saveReview).toHaveBeenCalledTimes(saveCalls);
      expect(document.querySelector('img')).toBe(image);

      pending.resolve({ ...firstItem, currentLabel: 'moth', currentComment: 'Original draft' });
      await vi.waitFor(() => expect(app.state).toBe('reviewing'));
      expect(label.checked).toBe(true);
      expect(comment.value).toBe('Original draft');
      for (const control of [label, comment, next, send, selector, source])
        expect(control.disabled).toBe(false);
      app.dispose();
    },
  );

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

  it('counts Unicode once per edit and only recounts a changed restored draft', async () => {
    const repo = repository({
      getCursor: (_batch, _anchor, direction) =>
        Promise.resolve(direction === 'next' ? secondItem : firstItem),
    });
    const app = createApp(repo);
    await app.start();
    const count = vi.spyOn(text, 'countCodePoints');
    const limit = vi.spyOn(text, 'limitCodePoints');
    try {
      const comment = document.querySelector<HTMLTextAreaElement>('#review-comment');
      if (!comment) throw new Error('Missing comment');
      comment.value = '🦋'.repeat(1005);
      comment.dispatchEvent(new Event('input', { bubbles: true }));
      expect(comment.value).toBe('🦋'.repeat(1000));
      expect(document.querySelector('.comment-count')?.textContent).toBe('0 remaining');
      expect(limit).toHaveBeenCalledOnce();
      expect(count).not.toHaveBeenCalled();
      document.querySelector<HTMLInputElement>('input[value="moth"]')?.click();
      document.querySelector<HTMLButtonElement>('.image-source-button')?.click();
      expect(count).not.toHaveBeenCalled();
      document.querySelector<HTMLButtonElement>('[aria-label="Next image"]')?.click();
      await vi.waitFor(() => expect(comment.value).toBe(''));
      expect(count).toHaveBeenCalledOnce();
      document.querySelector<HTMLButtonElement>('[aria-label="Previous image"]')?.click();
      await vi.waitFor(() => expect(comment.value).toBe('🦋'.repeat(1000)));
      expect(count).toHaveBeenCalledTimes(2);
      expect(document.querySelector('.comment-count')?.textContent).toBe('0 remaining');
    } finally {
      count.mockRestore();
      limit.mockRestore();
      app.dispose();
    }
  });
});
