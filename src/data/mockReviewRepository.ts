import type { ReviewBatch, ReviewItem, ReviewSubmission } from '../domain/reviewQueue';
import type { AuthEventHandler, ReviewRepository } from './reviewRepository';

const FIRST_BATCH_ID = '30000000-0000-0000-0000-000000000001';
const SECOND_BATCH_ID = '30000000-0000-0000-0000-000000000002';

const itemsByBatch: Readonly<Record<string, readonly ReviewItem[]>> = {
  [FIRST_BATCH_ID]: [
    {
      id: '40000000-0000-0000-0000-000000000001',
      imageId: 'synthetic-image-001',
      displayUrl: 'https://images.example.invalid/display-fail.jpg',
      fallbackImageUrl: 'https://images.example.invalid/review-001.svg',
      position: 1,
      reviewedCount: 0,
      totalCount: 2,
    },
    {
      id: '40000000-0000-0000-0000-000000000002',
      imageId: 'synthetic-image-002',
      displayUrl: 'https://images.example.invalid/review-002.svg',
      fallbackImageUrl: 'https://images.example.invalid/review-002-original.svg',
      position: 2,
      reviewedCount: 0,
      totalCount: 2,
    },
  ],
  [SECOND_BATCH_ID]: [
    {
      id: '40000000-0000-0000-0000-000000000003',
      imageId: 'synthetic-image-003',
      displayUrl: null,
      fallbackImageUrl: 'https://images.example.invalid/review-003.svg',
      position: 1,
      reviewedCount: 0,
      totalCount: 1,
    },
  ],
};

export class SyntheticReviewRepository implements ReviewRepository {
  #signedIn = true;
  #authHandler: AuthEventHandler | null = null;
  readonly #reviews = new Map<string, ReviewSubmission>();
  readonly #submissionItems = new Map<string, string>();
  readonly #failedOnce = new Set<string>();

  getSession() {
    return Promise.resolve(
      this.#signedIn
        ? { email: 'synthetic-reviewer@example.invalid', identifiedBy: 'Synthetic reviewer' }
        : null,
    );
  }

  onAuthStateChange(handler: AuthEventHandler) {
    this.#authHandler = handler;
    return () => {
      this.#authHandler = null;
    };
  }

  sendMagicLink() {
    return Promise.resolve();
  }

  signOut() {
    this.#signedIn = false;
    this.#authHandler?.(null);
    return Promise.resolve();
  }

  listBatches(signal: AbortSignal) {
    throwIfAborted(signal);
    return Promise.resolve(this.#batchList());
  }

  getQueue(batchId: string, limit: number, signal: AbortSignal) {
    throwIfAborted(signal);
    const items = itemsByBatch[batchId] ?? [];
    const reviewedCount = items.filter((item) => this.#reviews.has(item.id)).length;
    return Promise.resolve(
      items
        .filter((item) => !this.#reviews.has(item.id))
        .slice(0, Math.min(Math.max(limit, 1), 2))
        .map((item) => ({ ...item, reviewedCount, totalCount: items.length })),
    );
  }

  submitReview(submission: ReviewSubmission) {
    if (
      submission.comment === 'force-save-failure' &&
      !this.#failedOnce.has(submission.submissionId)
    ) {
      this.#failedOnce.add(submission.submissionId);
      return Promise.reject(new Error('Synthetic save failure'));
    }

    const existingItem = this.#submissionItems.get(submission.submissionId);
    if (existingItem && existingItem !== submission.itemId) {
      return Promise.reject(new Error('Synthetic submission conflict'));
    }
    const existing = this.#reviews.get(submission.itemId);
    if (existing && existing.submissionId !== submission.submissionId) {
      return Promise.reject(new Error('Synthetic duplicate review'));
    }
    this.#submissionItems.set(submission.submissionId, submission.itemId);
    this.#reviews.set(submission.itemId, submission);
    const batchEntry = Object.entries(itemsByBatch).find(([, items]) =>
      items.some((item) => item.id === submission.itemId),
    );
    const batchItems = batchEntry?.[1] ?? [];
    const reviewedCount = batchItems.filter((item) => this.#reviews.has(item.id)).length;
    return Promise.resolve({
      reviewedCount,
      totalCount: batchItems.length,
      complete: batchItems.length > 0 && reviewedCount === batchItems.length,
    });
  }

  #batchList(): ReviewBatch[] {
    return [
      this.#batch(FIRST_BATCH_ID, 'SYNTH-001', 'Batch SYNTH-001'),
      this.#batch(SECOND_BATCH_ID, 'SYNTH-002', 'Batch SYNTH-002'),
    ];
  }

  #batch(id: string, code: string, name: string): ReviewBatch {
    const items = itemsByBatch[id] ?? [];
    const reviewedCount = items.filter((item) => this.#reviews.has(item.id)).length;
    return {
      id,
      code,
      name,
      reviewedCount,
      totalCount: items.length,
      complete: items.length > 0 && reviewedCount === items.length,
    };
  }
}

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) throw new DOMException('Request cancelled', 'AbortError');
}
