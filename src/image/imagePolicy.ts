export const MAX_PREVIEW_EDGE = 1600;
const FLICKR_DOMAIN = 'staticflickr.com';
const FLICKR_EDGES: Readonly<Record<string, number>> = {
  s: 75,
  q: 150,
  t: 100,
  m: 240,
  n: 320,
  w: 400,
  '': 500,
  z: 640,
  c: 800,
  b: 1024,
  h: 1600,
  k: 2048,
  '3k': 3072,
  '4k': 4096,
  f: 4096,
  '5k': 5120,
  '6k': 6144,
};

/** Recognize supplied Flickr renditions; never fabricate a size-specific secret. */
export function suppliedPreviewEdge(source: string): number | null {
  const url = new URL(source);
  if (url.port || !url.hostname.endsWith(`.${FLICKR_DOMAIN}`)) return null;
  const host = url.hostname.slice(0, -FLICKR_DOMAIN.length - 1);
  if (host !== 'live' && !/^farm\d+$/.test(host)) return null;
  const match = /^\/\d+\/\d+_[a-f\d]+(?:_([a-z\d]+))?\.jpg$/i.exec(url.pathname);
  if (!match) return Infinity;
  return FLICKR_EDGES[match[1] ?? ''] ?? Infinity;
}
