import { describe, expect, it } from 'vitest';
import { countCodePoints, limitCodePoints } from './text';

describe('Unicode code-point limits', () => {
  it('counts and truncates without splitting surrogate pairs', () => {
    expect(countCodePoints('a🦋e\u0301')).toBe(4);
    expect(limitCodePoints('a🦋e\u0301', 2)).toEqual({ value: 'a🦋', length: 2 });
    expect(limitCodePoints('🦋'.repeat(1001), 1000)).toEqual({
      value: '🦋'.repeat(1000),
      length: 1000,
    });
    expect(limitCodePoints('', 1000)).toEqual({ value: '', length: 0 });
  });
});
