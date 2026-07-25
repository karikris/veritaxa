import { describe, expect, it } from 'vitest';

import { ImagePrefetch, shouldPrefetch } from './imagePrefetch';

describe('next-image prefetch', () => {
  it('is disabled in data-saver mode', () => {
    expect(shouldPrefetch({ saveData: true })).toBe(false);
    expect(shouldPrefetch({ saveData: false })).toBe(true);
  });

  it('keeps at most one detached image and invalidates stale work', () => {
    const images: { src: string }[] = [];
    const prefetch = new ImagePrefetch(() => {
      const image = { src: '' };
      images.push(image);
      return image;
    });

    prefetch.start('https://images.example.invalid/first.jpg', undefined);
    prefetch.start('https://images.example.invalid/second.jpg', undefined);

    expect(images).toHaveLength(2);
    expect(images[0]?.src).toBe('');
    expect(images[1]?.src).toContain('/second.jpg');
    prefetch.invalidate();
    expect(images[1]?.src).toBe('');
  });
});
