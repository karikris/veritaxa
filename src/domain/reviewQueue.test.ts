import { describe, expect, it } from 'vitest';

import { MAX_COMMENT_LENGTH, normalizeComment } from './reviewQueue';

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
});
