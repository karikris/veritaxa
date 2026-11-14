import type { ReviewLabelCode } from './reviewLabels';
import { countCodePoints } from './text';

export const MAX_COMMENT_LENGTH = 1000;
export const CLIENT_VERSION = 'veritaxa-web/0.8.0';

export type ReviewBatch = {
  id: string;
  name: string;
  code: string;
  reviewedCount: number;
  totalCount: number;
  complete: boolean;
  teamReviewedCount?: number;
  reviewRound?: number;
};

export type ReviewItem = {
  id: string;
  imageId: string;
  targetScientificName: string | null;
  modelScientificName?: string | null;
  modelCosine?: number | null;
  displayUrl: string | null;
  fallbackImageUrl: string;
  position: number;
  currentLabel: ReviewLabelCode | null;
  currentComment: string | null;
  currentVersion: number;
  reviewedByAnyone?: boolean;
  teamReviewedCount?: number;
  reviewedCount: number;
  totalCount: number;
  complete: boolean;
};

export type ReviewCursorDirection = 'resume' | 'next' | 'previous';

export type ReviewSubmission = Readonly<{
  itemId: string;
  label: ReviewLabelCode;
  comment: string | null;
  submissionId: string;
  clientVersion: string;
  expectedVersion: number;
}>;

export function normalizeComment(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;
  if (countCodePoints(trimmed) > MAX_COMMENT_LENGTH) {
    throw new Error(`Comment must be ${String(MAX_COMMENT_LENGTH)} characters or fewer.`);
  }
  return trimmed;
}
