import type { ReviewLabelCode } from './reviewLabels';

export const MAX_COMMENT_LENGTH = 1000;
export const CLIENT_VERSION = 'veritaxa-web/0.1.0';

export type ReviewBatch = {
  id: string;
  name: string;
  code: string;
  reviewedCount: number;
  totalCount: number;
  complete: boolean;
};

export type ReviewItem = {
  id: string;
  imageId: string;
  flickrKeyword: string | null;
  displayUrl: string | null;
  fallbackImageUrl: string;
  position: number;
  reviewedCount: number;
  totalCount: number;
};

export type ReviewSubmission = {
  itemId: string;
  label: ReviewLabelCode;
  comment: string | null;
  submissionId: string;
  clientVersion: string;
};

export type ReviewProgress = {
  reviewedCount: number;
  totalCount: number;
  complete: boolean;
};

export function normalizeComment(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;
  if (Array.from(trimmed).length > MAX_COMMENT_LENGTH) {
    throw new Error(`Comment must be ${String(MAX_COMMENT_LENGTH)} characters or fewer.`);
  }
  return trimmed;
}

export function createSubmissionId(existing: string | null): string {
  return existing ?? crypto.randomUUID();
}
