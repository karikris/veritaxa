import { describe, expect, it } from 'vitest';
import {
  advanceImageAttempt,
  createImageAttempt,
  createImagePolicy,
  currentImageSource,
  validateImageUrl,
} from './imageLoader';
import { suppliedPreviewEdge } from './imagePolicy';

const original = 'https://images.example.invalid/original.jpg';
const preview = 'https://images.example.invalid/preview.jpg';
// Fictional identifiers against a public hostname, not task URLs.
const flickr = (suffix: string, host = 'live') =>
  'https://' + host + '.' + 'staticflickr.com' + '/1/1_0000000000' + suffix + '.jpg';

describe('review image loading', () => {
  it.each([
    'http://images.example.invalid/image.jpg',
    'https://user:secret@images.example.invalid/image.jpg',
    'javascript:alert(1)',
    'not a URL',
  ])('rejects unsafe image URL %s', (url) => {
    expect(validateImageUrl(url)).toBeNull();
    expect(createImagePolicy(url, url)).toEqual({ previews: [], original: null });
  });

  it('uses the declared preview without automatically requesting an uncontrolled original', () => {
    const policy = createImagePolicy(preview, original);
    const attempt = createImageAttempt(policy);
    expect(currentImageSource(attempt)).toBe(preview);
    expect(advanceImageAttempt(attempt)).toBeNull();
    expect(currentImageSource(createImageAttempt(policy, 'original'))).toBe(original);
  });

  it.each([null, original])(
    'requires explicit inspection when the display field is %s',
    (display) => {
      const policy = createImagePolicy(display, original);
      expect(currentImageSource(createImageAttempt(policy))).toBeNull();
      expect(currentImageSource(createImageAttempt(policy, 'original'))).toBe(original);
    },
  );

  it.each([
    ['', 500],
    ['_b', 1024],
    ['_h', 1600],
    ['_c', 800],
    ['_s', 75],
  ] as const)(
    'recognizes supplied bounded Flickr suffix %s without rewriting its secret',
    (suffix, size) => {
      const source = flickr(suffix);
      expect(suppliedPreviewEdge(source)).toBe(size);
      expect(createImagePolicy(source, source).previews).toEqual([source]);
      expect(createImagePolicy(null, source).previews).toEqual([source]);
    },
  );

  it.each(['_k', '_3k', '_4k', '_f', '_5k', '_6k', '_o', '_unknown'])(
    'does not invent smaller URLs from the size-specific secret in %s',
    (suffix) => {
      const source = flickr(suffix);
      const policy = createImagePolicy(source, source);
      expect(policy.previews).toEqual([]);
      expect(createImageAttempt(policy, 'original').sources).toEqual([source]);
    },
  );

  it('only falls back automatically to another supplied bounded rendition', () => {
    const source = flickr('_b');
    const attempt = createImageAttempt(createImagePolicy(preview, source));
    expect(currentImageSource(attempt)).toBe(preview);
    const fallback = advanceImageAttempt(attempt);
    expect(fallback && currentImageSource(fallback)).toBe(source);
    expect(fallback && advanceImageAttempt(fallback)).toBeNull();
    expect(createImageAttempt(createImagePolicy(source, source)).sources).toEqual([source]);
  });

  it('accepts documented legacy farm hosts but does not mistake lookalikes for the provider', () => {
    expect(createImagePolicy(null, flickr('_b', 'farm1')).previews).toHaveLength(1);
    expect(createImagePolicy(null, flickr('_b', 'evil.live')).previews).toEqual([]);
    const lookalike = flickr('_b').replace('.com/', '.com.example.invalid/');
    expect(createImagePolicy(null, lookalike).previews).toEqual([]);
  });

  it('gives every request a separate ownership identity while retaining at most two preview sources', () => {
    const policy = createImagePolicy(preview, flickr('_b'));
    expect(createImageAttempt(policy).sources).not.toBe(createImageAttempt(policy).sources);
    expect(policy.previews).toHaveLength(2);
    expect(createImageAttempt(policy, 'original').sources).toHaveLength(1);
  });
});
