const MAX_URL_LENGTH = 2048;

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

export function createImageAttempt(
  displayUrl: string | null,
  fallbackImageUrl: string,
): ImageAttempt {
  const display = validateImageUrl(displayUrl);
  const fallback = validateImageUrl(fallbackImageUrl);
  const sources = [display, fallback].filter(
    (source, index, all): source is string => source !== null && all.indexOf(source) === index,
  );
  return { sources, index: 0 };
}

export function currentImageSource(attempt: ImageAttempt): string | null {
  return attempt.sources[attempt.index] ?? null;
}

export function advanceImageAttempt(attempt: ImageAttempt): ImageAttempt | null {
  const nextIndex = attempt.index + 1;
  if (nextIndex >= attempt.sources.length) return null;
  return { ...attempt, index: nextIndex };
}
