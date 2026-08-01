import type {
  ReviewBatch,
  ReviewCursorDirection,
  ReviewItem,
  ReviewSubmission,
} from '../domain/reviewQueue';

export type ReviewerSession = {
  userId: string;
  identifiedBy: string | null;
};

export type AuthEventHandler = (session: ReviewerSession | null) => void;

export class ReviewerAccessDisabledError extends Error {
  constructor() {
    super('This reviewer profile is inactive.');
    this.name = 'ReviewerAccessDisabledError';
  }
}

export type ReviewRepository = {
  getSession: () => Promise<ReviewerSession | null>;
  onAuthStateChange: (handler: AuthEventHandler) => () => void;
  signIn: (identifiedBy: string) => Promise<void>;
  signOut: () => Promise<void>;
  listBatches: (signal: AbortSignal) => Promise<ReviewBatch[]>;
  getCursor: (
    batchId: string,
    anchorPosition: number | null,
    direction: ReviewCursorDirection,
    signal: AbortSignal,
  ) => Promise<ReviewItem | null>;
  saveReview: (submission: ReviewSubmission) => Promise<ReviewItem>;
};
