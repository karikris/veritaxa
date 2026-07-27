import type {
  ReviewBatch,
  ReviewItem,
  ReviewProgress,
  ReviewSubmission,
} from '../domain/reviewQueue';

export type ReviewerSession = {
  email: string;
};

export type AuthEventHandler = (session: ReviewerSession | null) => void;

export class ReviewerNotAuthorizedError extends Error {
  constructor() {
    super('This email is not approved for VeriTaxa.');
    this.name = 'ReviewerNotAuthorizedError';
  }
}

export type ReviewRepository = {
  getSession: () => Promise<ReviewerSession | null>;
  onAuthStateChange: (handler: AuthEventHandler) => () => void;
  sendMagicLink: (email: string, redirectTo: string) => Promise<void>;
  signOut: () => Promise<void>;
  listBatches: (signal: AbortSignal) => Promise<ReviewBatch[]>;
  getQueue: (batchId: string, limit: number, signal: AbortSignal) => Promise<ReviewItem[]>;
  submitReview: (submission: ReviewSubmission) => Promise<ReviewProgress>;
};
