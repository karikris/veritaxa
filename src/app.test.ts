import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
  targetScientificName: 'Papilio exemplaris',
  displayUrl: 'https://images.example.invalid/review-002.jpg',
  fallbackImageUrl: 'https://images.example.invalid/review-002-original.jpg',
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

  it('renders one image and only three answer buttons without a Send or comment step', async () => {
    const repo = repository();
    const app = createApp(repo);
    await app.start();

    expect(document.querySelectorAll('img.review-image')).toHaveLength(1);
    expect(document.querySelector('img')?.alt).toBe('Image under review');
    expect(document.querySelectorAll('.answer-button')).toHaveLength(3);
    expect(document.querySelectorAll('input[name="review-label"]')).toHaveLength(0);
    expect(document.querySelector('textarea')).toBeNull();
    expect(document.querySelector('.send-button')).toBeNull();
    expect(document.querySelector('#classification-heading')?.textContent).toBe(
      'Is this Papilio exemplaris?',
    );
    expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2');
    expect(repo.saveReview).not.toHaveBeenCalled();
    app.dispose();
  });

  it('keeps image zoom available', async () => {
    const app = createApp(repository());
    await app.start();
    const image = document.querySelector<HTMLImageElement>('img.review-image');
    const zoomIn = document.querySelector<HTMLButtonElement>('[aria-label="Zoom in"]');
    zoomIn?.click();
    expect(image?.dataset.zoom).toBe('1.25');
    document.querySelector<HTMLButtonElement>('[aria-label^="Reset image zoom"]')?.click();
    expect(image?.dataset.zoom).toBe('1');
    app.dispose();
  });

  it.each([
    ['Yes', 'target_scientific_name'],
    ['No', 'target_not_present'],
    ['No butterfly', 'no_butterfly'],
  ] as const)(
    'saves %s immediately and advances only after confirmation',
    async (_answer, label) => {
      let resolveSave: (item: ReviewItem) => void = () => undefined;
      const pending = new Promise<ReviewItem>((resolve) => {
        resolveSave = resolve;
      });
      const repo = repository({ save: () => pending });
      const app = createApp(repo);
      await app.start();
      document.querySelector<HTMLButtonElement>(`[data-label="${label}"]`)?.click();

      expect(repo.saveReview).toHaveBeenCalledOnce();
      expect(repo.saveReview).toHaveBeenCalledWith(
        expect.objectContaining({
          itemId: firstItem.id,
          label,
          expectedVersion: 0,
          comment: null,
        }),
      );
      expect(document.querySelector('img')?.src).toContain('review-001-small.jpg');
      expect(
        [...document.querySelectorAll<HTMLButtonElement>('.answer-button')].every(
          (b) => b.disabled,
        ),
      ).toBe(true);
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'y', bubbles: true }));
      expect(repo.saveReview).toHaveBeenCalledOnce();

      resolveSave({ ...secondItem, reviewedCount: 1 });
      await vi.waitFor(() =>
        expect(document.querySelector('img')?.src).toContain('review-002.jpg'),
      );
      expect(repo.getCursor).toHaveBeenCalledOnce();
      expect(document.querySelector('.classification-panel')).toBe(document.activeElement);
      app.dispose();
    },
  );

  it('retains a failed answer and retries with the same submission ID', async () => {
    const repo = repository();
    repo.saveReview.mockRejectedValueOnce(new Error('Synthetic save failure'));
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLButtonElement>('[data-label="target_not_present"]')?.click();
    await vi.waitFor(() => expect(document.body.textContent).toContain('Synthetic save failure'));
    expect(document.querySelector('img')?.src).toContain('review-001-small.jpg');
    const retry = [...document.querySelectorAll<HTMLButtonElement>('button')].find(
      (b) => b.textContent === 'Retry save',
    );
    retry?.click();
    await vi.waitFor(() => expect(repo.saveReview).toHaveBeenCalledTimes(2));
    expect(repo.saveReview.mock.calls[1]?.[0]).toEqual(repo.saveReview.mock.calls[0]?.[0]);
    await vi.waitFor(() => expect(document.querySelector('img')?.src).toContain('review-002.jpg'));
    app.dispose();
  });

  it('never converts an older broad classification into a binary answer automatically', async () => {
    const app = createApp(
      repository({ cursor: { ...firstItem, currentLabel: 'moth', currentVersion: 3 } }),
    );
    await app.start();
    expect(document.querySelector('.classification-panel')?.textContent).not.toContain(
      'Your saved answer: No',
    );
    app.dispose();
  });

  it('allows a saved Yes answer to be corrected to No while retaining its comment', async () => {
    const repo = repository({
      cursor: {
        ...firstItem,
        currentLabel: 'target_scientific_name',
        currentComment: 'Original note',
        currentVersion: 3,
      },
    });
    const app = createApp(repo);
    await app.start();
    expect(document.body.textContent).toContain('Your saved answer: Yes');
    document.querySelector<HTMLButtonElement>('[data-label="target_not_present"]')?.click();
    expect(repo.saveReview).toHaveBeenCalledWith(
      expect.objectContaining({
        itemId: firstItem.id,
        expectedVersion: 3,
        label: 'target_not_present',
        comment: 'Original note',
      }),
    );
    await vi.waitFor(() => expect(app.state).toBe('reviewing'));
    app.dispose();
  });

  it('skips images with navigation without recording an answer', async () => {
    const repo = repository({
      getCursor: (_batchId, _position, direction) =>
        Promise.resolve(direction === 'next' ? secondItem : firstItem),
    });
    const app = createApp(repo);
    await app.start();
    document.querySelector<HTMLButtonElement>('[aria-label="Next image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
    );
    document.querySelector<HTMLButtonElement>('[aria-label="Previous image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2'),
    );
    expect(repo.saveReview).not.toHaveBeenCalled();
    app.dispose();
  });

  it('uses Y/N to save and ignores old shortcuts, repeated keys, and editable controls', async () => {
    const repo = repository();
    const app = createApp(repo);
    await app.start();
    const selector = document.querySelector<HTMLSelectElement>('select');
    selector?.dispatchEvent(new KeyboardEvent('keydown', { key: 'y', bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'y', repeat: true, bubbles: true }));
    expect(repo.saveReview).not.toHaveBeenCalled();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Y', bubbles: true }));
    expect(repo.saveReview).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'target_scientific_name' }),
    );
    await vi.waitFor(() => expect(document.querySelector('img')?.src).toContain('review-002.jpg'));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'n', bubbles: true }));
    expect(repo.saveReview).toHaveBeenLastCalledWith(
      expect.objectContaining({ label: 'target_not_present' }),
    );
    await vi.waitFor(() => expect(app.state).toBe('reviewing'));
    app.dispose();
  });

  it('disables all answers when the campaign has no target species', async () => {
    const repo = repository({ cursor: { ...firstItem, targetScientificName: null } });
    const app = createApp(repo);
    await app.start();
    expect(document.body.textContent).toContain('No target species configured');
    expect(
      [...document.querySelectorAll<HTMLButtonElement>('.answer-button')].every((b) => b.disabled),
    ).toBe(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'n', bubbles: true }));
    expect(repo.saveReview).not.toHaveBeenCalled();
    app.dispose();
  });

  it('does not record No for an unavailable image', async () => {
    const repo = repository();
    const app = createApp(repo);
    await app.start();
    const image = document.querySelector<HTMLImageElement>('img.review-image');
    image?.dispatchEvent(new Event('error'));
    image?.dispatchEvent(new Event('error'));
    expect(app.state).toBe('image_error');
    expect(
      [...document.querySelectorAll<HTMLButtonElement>('.answer-button')].every((b) => b.disabled),
    ).toBe(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'n', bubbles: true }));
    expect(repo.saveReview).not.toHaveBeenCalled();
    app.dispose();
  });
  it.each(['stale_version', 'submission_conflict'] as const)(
    'compares a %s conflict before reapplying the binary answer',
    async (kind) => {
      const repo = repository();
      repo.saveReview.mockRejectedValueOnce(new ReviewConflictError(kind));
      repo.getCursor.mockResolvedValueOnce(firstItem).mockResolvedValueOnce({
        ...firstItem,
        currentLabel: 'target_not_present',
        currentVersion: 2,
        currentComment: 'Saved elsewhere',
      });
      const app = createApp(repo);
      await app.start();
      document.querySelector<HTMLButtonElement>('[aria-label="Yes"]')?.click();
      await vi.waitFor(() => expect(app.state).toBe('save_error'));
      const original = repo.saveReview.mock.calls[0]?.[0];
      expect(document.querySelector<HTMLButtonElement>('[aria-label="No"]')?.disabled).toBe(true);
      document.querySelector<HTMLButtonElement>('.retry-save')?.click();
      await vi.waitFor(() => expect(document.querySelector('.conflict-comparison')).not.toBeNull());
      expect(repo.saveReview).toHaveBeenCalledOnce();
      document.querySelector<HTMLButtonElement>('.reapply')?.click();
      await vi.waitFor(() => expect(repo.saveReview).toHaveBeenCalledTimes(2));
      expect(repo.saveReview.mock.calls[1]?.[0]).toMatchObject({
        label: 'target_scientific_name',
        expectedVersion: 2,
        comment: 'Saved elsewhere',
      });
      expect(repo.saveReview.mock.calls[1]?.[0].submissionId).not.toBe(original?.submissionId);
      await vi.waitFor(() =>
        expect(document.querySelector('.image-position')?.textContent).toBe('2 / 2'),
      );
      app.dispose();
    },
  );

  it('keeps the mounted image and answer controls through an unknown save outcome', async () => {
    let rejectSave: (error: Error) => void = () => undefined;
    const pending = new Promise<ReviewItem>((_resolve, reject) => {
      rejectSave = reject;
    });
    const repo = repository({ save: () => pending });
    const app = createApp(repo);
    await app.start();
    const image = document.querySelector('img');
    const yes = document.querySelector<HTMLButtonElement>('[aria-label="Yes"]');
    yes?.click();
    expect(document.querySelector('img')).toBe(image);
    rejectSave(new Error('Unknown write outcome'));
    await vi.waitFor(() => expect(app.state).toBe('save_error'));
    expect(document.querySelector('img')).toBe(image);
    expect(document.querySelector('[aria-label="Yes"]')).toBe(yes);
    document.querySelector<HTMLButtonElement>('[aria-label="No"]')?.click();
    expect(repo.saveReview).toHaveBeenCalledOnce();
    app.dispose();
  });
  it('retains one header status text node through saving, success and navigation', async () => {
    let finish: (item: ReviewItem) => void = () => undefined;
    const pending = new Promise<ReviewItem>((resolve) => {
      finish = resolve;
    });
    const app = createApp(repository({ save: () => pending }));
    await app.start();
    const status = document.querySelector('.save-state');
    const text = status?.firstChild;
    expect(text).toBeInstanceOf(Text);
    expect(status?.textContent).toBe('');
    document.querySelector<HTMLButtonElement>('[aria-label="Yes"]')?.click();
    expect(status?.textContent).toBe('Saving…');
    expect(status?.firstChild).toBe(text);
    finish({ ...secondItem, reviewedCount: 1 });
    await vi.waitFor(() => expect(status?.textContent).toBe('Saved'));
    expect(status?.firstChild).toBe(text);
    document.querySelector<HTMLButtonElement>('[aria-label="Next image"]')?.click();
    await vi.waitFor(() =>
      expect(document.querySelector('.image-position')?.textContent).toBe('1 / 2'),
    );
    expect(status?.textContent).toBe('Saved');
    expect(status?.firstChild).toBe(text);
    app.dispose();
  });
  it('restores No butterfly and allows correction without changing the existing comment', async () => {
    const repo = repository({
      cursor: {
        ...firstItem,
        currentLabel: 'no_butterfly',
        currentVersion: 4,
        currentComment: 'Original note',
      },
    });
    const app = createApp(repo);
    await app.start();
    expect(document.body.textContent).toContain('Your saved answer: No butterfly.');
    document.querySelector<HTMLButtonElement>('[aria-label="Yes"]')?.click();
    expect(repo.saveReview).toHaveBeenCalledWith(
      expect.objectContaining({
        label: 'target_scientific_name',
        expectedVersion: 4,
        comment: 'Original note',
      }),
    );
    await vi.waitFor(() => expect(app.state).toBe('reviewing'));
    app.dispose();
  });

  it('uses zero to submit No butterfly while ignoring editable controls and held keys', async () => {
    const repo = repository();
    const app = createApp(repo);
    await app.start();
    document
      .querySelector('select')
      ?.dispatchEvent(new KeyboardEvent('keydown', { key: '0', bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '0', repeat: true, bubbles: true }));
    expect(repo.saveReview).not.toHaveBeenCalled();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '0', bubbles: true }));
    expect(repo.saveReview).toHaveBeenCalledWith(
      expect.objectContaining({ label: 'no_butterfly' }),
    );
    await vi.waitFor(() => expect(app.state).toBe('reviewing'));
    app.dispose();
  });
});
