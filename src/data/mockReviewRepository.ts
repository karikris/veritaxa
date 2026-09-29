import type {
  ReviewBatch,
  ReviewCursorDirection,
  ReviewItem,
  ReviewSubmission,
} from '../domain/reviewQueue';
import type { AuthEventHandler, ReviewRepository } from './reviewRepository';
import { ReviewConflictError } from './reviewRepository';

const FIRST_BATCH_ID = '30000000-0000-0000-0000-000000000001';
const SECOND_BATCH_ID = '30000000-0000-0000-0000-000000000002';

const itemsByBatch: Readonly<Record<string, readonly ReviewItem[]>> = {
  [FIRST_BATCH_ID]: [
    {
      id: '40000000-0000-0000-0000-000000000001',
      imageId: 'synthetic-image-001',
      targetScientificName: 'Papilio exemplaris',
      displayUrl: 'https://images.example.invalid/review-001.svg',
      fallbackImageUrl: 'https://images.example.invalid/review-001-original.svg',
      position: 1,
      currentLabel: null,
      currentComment: null,
      currentVersion: 0,
      reviewedCount: 0,
      totalCount: 2,
      complete: false,
    },
    {
      id: '40000000-0000-0000-0000-000000000002',
      imageId: 'synthetic-image-002',
      targetScientificName: null,
      displayUrl: 'https://images.example.invalid/review-002.svg',
      fallbackImageUrl: 'https://images.example.invalid/review-002-original.svg',
      position: 2,
      currentLabel: null,
      currentComment: null,
      currentVersion: 0,
      reviewedCount: 0,
      totalCount: 2,
      complete: false,
    },
  ],
  [SECOND_BATCH_ID]: [
    {
      id: '40000000-0000-0000-0000-000000000003',
      imageId: 'synthetic-image-003',
      targetScientificName: 'Danaus exemplaris',
      displayUrl: null,
      fallbackImageUrl: 'https://images.example.invalid/review-003.svg',
      position: 1,
      currentLabel: null,
      currentComment: null,
      currentVersion: 0,
      reviewedCount: 0,
      totalCount: 1,
      complete: false,
    },
  ],
};

export class SyntheticReviewRepository implements ReviewRepository {
  #signedIn = true;
  #authHandler: AuthEventHandler | null = null;
  readonly #reviews = new Map<string, ReviewSubmission & { version: number }>();
  readonly #failedOnce = new Set<string>();

  getSession() {
    return Promise.resolve(
      this.#signedIn
        ? {
            userId: '10000000-0000-0000-0000-000000000001',
            identifiedBy: 'Synthetic reviewer',
          }
        : null,
    );
  }

  onAuthStateChange(handler: AuthEventHandler) {
    this.#authHandler = handler;
    return () => {
      this.#authHandler = null;
    };
  }

  signIn(identifiedBy: string) {
    this.#signedIn = true;
    this.#authHandler?.({
      userId: '10000000-0000-0000-0000-000000000001',
      identifiedBy,
    });
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

  getCursor(
    batchId: string,
    anchorPosition: number | null,
    direction: ReviewCursorDirection,
    signal: AbortSignal,
  ) {
    throwIfAborted(signal);
    const items = itemsByBatch[batchId] ?? [];
    const selected = this.#selectCursorItem(items, anchorPosition, direction);
    return Promise.resolve(selected ? this.#withReview(selected, items) : null);
  }

  saveReview(submission: ReviewSubmission) {
    if (
      submission.comment === 'force-save-failure' &&
      !this.#failedOnce.has(submission.submissionId)
    ) {
      this.#failedOnce.add(submission.submissionId);
      return Promise.reject(new Error('Synthetic save failure'));
    }

    const existing = this.#reviews.get(submission.itemId);
    if (existing?.submissionId === submission.submissionId) {
      if (
        existing.label !== submission.label ||
        existing.comment !== submission.comment ||
        existing.clientVersion !== submission.clientVersion ||
        existing.version !== submission.expectedVersion + 1
      ) {
        return Promise.reject(new ReviewConflictError('submission_conflict'));
      }
    } else if ((existing?.version ?? 0) !== submission.expectedVersion) {
      return Promise.reject(new ReviewConflictError('stale_version'));
    } else {
      this.#reviews.set(submission.itemId, {
        ...submission,
        version: submission.expectedVersion + 1,
      });
    }

    const batchEntry = Object.entries(itemsByBatch).find(([, items]) =>
      items.some((item) => item.id === submission.itemId),
    );
    const batchItems = batchEntry?.[1] ?? [];
    const savedItem = batchItems.find((item) => item.id === submission.itemId);
    const next = savedItem
      ? this.#selectCursorItem(batchItems, savedItem.position, 'next')
      : undefined;
    if (!next) return Promise.reject(new Error('Synthetic review item is missing'));
    return Promise.resolve(this.#withReview(next, batchItems));
  }

  #selectCursorItem(
    items: readonly ReviewItem[],
    anchorPosition: number | null,
    direction: ReviewCursorDirection,
  ): ReviewItem | undefined {
    if (direction === 'resume') {
      return items.find((item) => !this.#reviews.has(item.id)) ?? items[0];
    }
    if (anchorPosition === null) return undefined;
    if (direction === 'next') {
      return items.find((item) => item.position > anchorPosition) ?? items[0];
    }
    return [...items].reverse().find((item) => item.position < anchorPosition) ?? items.at(-1);
  }

  #withReview(item: ReviewItem, batchItems: readonly ReviewItem[]): ReviewItem {
    const review = this.#reviews.get(item.id);
    const reviewedCount = batchItems.filter((candidate) => this.#reviews.has(candidate.id)).length;
    return {
      ...item,
      currentLabel: review?.label ?? null,
      currentComment: review?.comment ?? null,
      currentVersion: review?.version ?? 0,
      reviewedCount,
      totalCount: batchItems.length,
      complete: batchItems.length > 0 && reviewedCount === batchItems.length,
    };
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
