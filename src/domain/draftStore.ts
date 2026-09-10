import type { ReviewDraft } from './reviewDraft';

export const MAX_DIRTY_DRAFTS = 256;
export const MAX_DRAFT_BYTES = 1024 * 1024;
// Two 1,000-code-point comments (current edit + immutable retry), even with JSON
// escaping, plus UUIDs/version/labels fit in 16 KiB. Reserve the active editor so
// later typing or an ambiguous save cannot overrun the total budget.
export const ACTIVE_DRAFT_RESERVE = 16 * 1024;
const encoder = new TextEncoder();

export function draftBytes(itemId: string, draft: ReviewDraft): number {
  return encoder.encode(JSON.stringify([itemId, draft])).byteLength;
}

/** Only parked drafts live here; the editor owns its active draft separately. */
export class DraftStore {
  readonly #entries = new Map<string, { draft: ReviewDraft; bytes: number }>();
  #bytes = 0;

  get size(): number {
    return this.#entries.size;
  }
  get bytes(): number {
    return this.#bytes;
  }

  keep(itemId: string, draft: ReviewDraft): boolean {
    const bytes = draftBytes(itemId, draft);
    const previous = this.#entries.get(itemId);
    const count = this.size + (previous ? 0 : 1);
    const total = this.#bytes - (previous?.bytes ?? 0) + bytes;
    if (
      bytes > ACTIVE_DRAFT_RESERVE ||
      count >= MAX_DIRTY_DRAFTS ||
      total > MAX_DRAFT_BYTES - ACTIVE_DRAFT_RESERVE
    )
      return false;
    // Navigation may fail, leaving this editor active. Subsequent edits must not
    // mutate a parked entry behind its byte accounting. Pending requests are frozen.
    this.#entries.set(itemId, { draft: { ...draft }, bytes });
    this.#bytes = total;
    return true;
  }

  take(itemId: string): ReviewDraft | undefined {
    const entry = this.#entries.get(itemId);
    this.delete(itemId);
    return entry?.draft;
  }

  delete(itemId: string): void {
    const entry = this.#entries.get(itemId);
    if (!entry) return;
    this.#bytes -= entry.bytes;
    this.#entries.delete(itemId);
  }

  clear(): void {
    this.#entries.clear();
    this.#bytes = 0;
  }
}
