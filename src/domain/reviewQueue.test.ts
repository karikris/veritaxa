import { describe, expect, it, vi } from 'vitest';

import { createSubmissionId, MAX_COMMENT_LENGTH, normalizeComment } from './reviewQueue';

describe('review submission rules', () => {
  it('normalises blank comments to null and trims meaningful comments', () => {
    expect(normalizeComment(' \n ')).toBeNull();
    expect(normalizeComment('  useful note \n')).toBe('useful note');
  });

  it('accepts 1000 Unicode code points and rejects 1001', () => {
    expect(normalizeComment('🦋'.repeat(MAX_COMMENT_LENGTH))).toHaveLength(MAX_COMMENT_LENGTH * 2);
    expect(() => normalizeComment('🦋'.repeat(MAX_COMMENT_LENGTH + 1))).toThrow(
      '1000 characters or fewer',
    );
  });

  it('reuses an existing submission ID for an idempotent retry', () => {
    const randomUuid = vi.spyOn(crypto, 'randomUUID');
    expect(createSubmissionId('50000000-0000-0000-0000-000000000001')).toBe(
      '50000000-0000-0000-0000-000000000001',
    );
    expect(randomUuid).not.toHaveBeenCalled();
  });
});
