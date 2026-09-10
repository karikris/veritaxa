import { describe, expect, it } from 'vitest';

import { countCodePoints, limitCodePoints } from './text';

describe('code-point counting and bounded truncation', () => {
  it('counts and truncates without splitting surrogate pairs', () => {
    expect(countCodePoints('a🦋e\u0301')).toBe(4);
    expect(limitCodePoints('a🦋e\u0301', 2)).toEqual({ value: 'a🦋', length: 2 });
    expect(limitCodePoints('🦋'.repeat(1001), 1000)).toEqual({
      value: '🦋'.repeat(1000),
      length: 1000,
    });
    expect(limitCodePoints('', 1000)).toEqual({ value: '', length: 0 });
  });

  it.each(['', 'abc', '🦋a🦋', 'e\u0301', 'a\ud800b'])('preserves code points in %j', (value) => {
    const points = Array.from(value);
    expect(countCodePoints(value)).toBe(points.length);
    for (const limit of [0, 1, 2, 9]) {
      expect(limitCodePoints(value, limit)).toEqual({
        value: points.slice(0, limit).join(''),
        length: Math.min(points.length, limit),
      });
    }
  });
});
