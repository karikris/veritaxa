import { describe, expect, it } from 'vitest';

import {
  advanceImageAttempt,
  createImageAttempt,
  currentImageSource,
  validateImageUrl,
} from './imageLoader';

describe('review image loading', () => {
  it.each([
    'http://images.example.invalid/image.jpg',
    'https://user:secret@images.example.invalid/image.jpg',
    'javascript:alert(1)',
    'not a URL',
  ])('rejects unsafe image URL %s', (url) => {
    expect(validateImageUrl(url)).toBeNull();
  });

  it('uses the display URL first and falls back once to the source URL', () => {
    const attempt = createImageAttempt(
      'https://images.example.invalid/small.jpg',
      'https://images.example.invalid/original.jpg',
    );
    expect(currentImageSource(attempt)).toContain('/small.jpg');
    const fallback = advanceImageAttempt(attempt);
    expect(fallback && currentImageSource(fallback)).toContain('/original.jpg');
    expect(fallback && advanceImageAttempt(fallback)).toBeNull();
  });

  it('does not request the same URL twice when display and fallback match', () => {
    const attempt = createImageAttempt(
      'https://images.example.invalid/image.jpg',
      'https://images.example.invalid/image.jpg',
    );
    expect(attempt.sources).toHaveLength(1);
  });
});
