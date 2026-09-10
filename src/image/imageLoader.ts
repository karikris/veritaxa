import { MAX_PREVIEW_EDGE, suppliedPreviewEdge } from './imagePolicy';

const MAX_URL_LENGTH = 2048;

export type ImagePolicy = {
  previews: readonly string[];
  original: string | null;
};

export type ImageMode = 'preview' | 'original';

export type ImageAttempt = {
  sources: readonly string[];
  index: number;
};

export function validateImageUrl(value: unknown): string | null {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_URL_LENGTH) return null;

  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

export function createImagePolicy(
  displayUrl: string | null,
  fallbackImageUrl: string,
): ImagePolicy {
  const display = validateImageUrl(displayUrl);
  const original = validateImageUrl(fallbackImageUrl);
  const previews: string[] = [];
  if (display) {
    const edge = suppliedPreviewEdge(display);
    // A distinct display_url is an upstream preview declaration, not a hard
    // dimension guarantee. A duplicated unknown source URL is not a preview.
    if ((edge !== null && edge <= MAX_PREVIEW_EDGE) || (edge === null && display !== original)) {
      previews.push(display);
    }
  }
  if (original && !previews.includes(original)) {
    const edge = suppliedPreviewEdge(original);
    if (edge !== null && edge <= MAX_PREVIEW_EDGE) previews.push(original);
  }
  return { previews, original };
}

export function createImageAttempt(policy: ImagePolicy, mode: ImageMode = 'preview'): ImageAttempt {
  return {
    sources:
      mode === 'original' ? (policy.original ? [policy.original] : []) : [...policy.previews],
    index: 0,
  };
}

export function currentImageSource(attempt: ImageAttempt): string | null {
  return attempt.sources[attempt.index] ?? null;
}

export function advanceImageAttempt(attempt: ImageAttempt): ImageAttempt | null {
  const nextIndex = attempt.index + 1;
  if (nextIndex >= attempt.sources.length) return null;
  return { ...attempt, index: nextIndex };
}
