import { describe, expect, it } from 'vitest';
import {
  ACTIVE_DRAFT_RESERVE,
  DraftStore,
  MAX_DIRTY_DRAFTS,
  MAX_DRAFT_BYTES,
  draftBytes,
} from './draftStore';
import { createReviewDraft, submissionForDraft } from './reviewDraft';
import { MAX_COMMENT_LENGTH } from './reviewQueue';

describe('bounded parked drafts', () => {
  it('reserves one active slot and never evicts when the count limit is reached', () => {
    const store = new DraftStore();
    const draft = { ...createReviewDraft(), label: 'plant' as const, comment: 'Synthetic draft' };
    for (let index = 0; index < MAX_DIRTY_DRAFTS - 1; index += 1) {
      expect(store.keep(String(index), draft)).toBe(true);
    }
    const bytes = store.bytes;
    expect(store.keep('overflow', draft)).toBe(false);
    expect(store.size).toBe(255);
    expect(store.bytes).toBe(bytes);
    expect(store.take('0')).toEqual(draft);
    expect(store.keep('overflow', draft)).toBe(true);
  });

  it('caps serialized bytes independently of count, including escaped Unicode and retries', () => {
    const store = new DraftStore();
    const draft = {
      ...createReviewDraft(),
      label: 'artifact_or_illustration' as const,
      comment: '\u0001'.repeat(MAX_COMMENT_LENGTH),
      baseVersion: Number.MAX_SAFE_INTEGER,
    };
    const id = '40000000-0000-0000-0000-000000000001';
    const pending = submissionForDraft(id, draft);
    const large = { ...draft, pendingSubmission: pending };
    expect(draftBytes(id, large)).toBeLessThan(ACTIVE_DRAFT_RESERVE);
    let kept = 0;
    while (store.keep(String(kept), large)) kept += 1;
    expect(kept).toBeGreaterThan(1);
    expect(kept).toBeLessThan(MAX_DIRTY_DRAFTS - 1);
    expect(store.bytes + ACTIVE_DRAFT_RESERVE).toBeLessThanOrEqual(MAX_DRAFT_BYTES);
    expect(store.take('0')).toEqual(large);
    expect(store.take('1')?.pendingSubmission).toBe(pending);
    expect(store.keep('emoji', { ...draft, comment: '🦋'.repeat(MAX_COMMENT_LENGTH) })).toBe(true);
  });

  it('snapshots mutable edits, accounts replacements and releases on take/delete/clear', () => {
    const store = new DraftStore();
    const draft = createReviewDraft();
    draft.comment = 'first';
    store.keep('one', draft);
    const initial = store.bytes;
    draft.comment = 'second, longer';
    expect(store.bytes).toBe(initial);
    expect(store.take('one')?.comment).toBe('first');
    expect(store.bytes).toBe(0);
    store.keep('one', draft);
    store.keep('one', createReviewDraft());
    expect(store.bytes).toBe(draftBytes('one', createReviewDraft()));
    expect(store.size).toBe(1);
    store.delete('missing');
    store.delete('one');
    expect(store.bytes).toBe(0);
    store.keep('one', draft);
    store.clear();
    expect(store.size).toBe(0);
    expect(store.bytes).toBe(0);
  });

  it('refuses an out-of-contract oversized entry without changing an existing draft', () => {
    const store = new DraftStore();
    const draft = createReviewDraft();
    store.keep('one', draft);
    expect(store.keep('one', { ...draft, comment: 'x'.repeat(ACTIVE_DRAFT_RESERVE) })).toBe(false);
    expect(store.take('one')).toEqual(draft);
  });
});
