import type { ReviewLabelCode } from './reviewLabels';
import {
  CLIENT_VERSION,
  normalizeComment,
  type ReviewItem,
  type ReviewSubmission,
} from './reviewQueue';

export type ReviewDraft = {
  label: ReviewLabelCode | null;
  comment: string;
  baseVersion: number;
  pendingSubmission: ReviewSubmission | null;
  conflicted: boolean;
};

export function createReviewDraft(item: ReviewItem | null = null): ReviewDraft {
  return {
    label: item?.currentLabel ?? null,
    comment: item?.currentComment ?? '',
    baseVersion: item?.currentVersion ?? 0,
    pendingSubmission: null,
    conflicted: false,
  };
}

/** An unknown write outcome must be retried byte-for-byte, independently of later edits. */
export function submissionForDraft(itemId: string, draft: ReviewDraft): ReviewSubmission {
  if (draft.pendingSubmission) return draft.pendingSubmission;
  if (draft.conflicted) throw new Error('Compare the saved answer before sending again.');
  if (!draft.label) throw new Error('Select a classification before sending.');
  return Object.freeze({
    itemId,
    label: draft.label,
    comment: normalizeComment(draft.comment),
    submissionId: crypto.randomUUID(),
    clientVersion: CLIENT_VERSION,
    expectedVersion: draft.baseVersion,
  });
}
