import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SupabaseReviewRepository } from './supabaseReviewRepository';
import { normalizeComment } from '../domain/reviewQueue';

const { rpc } = vi.hoisted(() => ({ rpc: vi.fn() }));
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({ rpc }) }));

const item = {
  item_id: '40000000-0000-0000-0000-000000000001',
  image_id: 'synthetic-image',
  target_scientific_name: null,
  display_url: null,
  fallback_image_url: 'https://images.example.invalid/synthetic.jpg',
  position: 1,
  current_label: 'plant',
  current_comment: null as string | null,
  current_version: 1,
  reviewed_count: 1,
  total_count: 1,
  complete: true,
};

function repository() {
  return new SupabaseReviewRepository({
    supabaseUrl: 'https://example-project.supabase.co',
    supabasePublishableKey: 'sb_publishable_synthetic_test',
  });
}

describe('review RPC response boundary', () => {
  beforeEach(() => rpc.mockReset());

  it.each([600, 1000])('reads back a valid %i-code-point comment', async (length) => {
    const comment = normalizeComment('🦋'.repeat(length));
    rpc.mockReturnValue({
      abortSignal: vi.fn().mockResolvedValue({ data: [{ ...item, current_comment: comment }] }),
    });
    const result = await repository().getCursor(
      'synthetic-batch',
      null,
      'resume',
      new AbortController().signal,
    );
    expect(result?.currentComment).toBe(comment);
  });

  it.each(['🦋'.repeat(1001), 17, {}])(
    'rejects an invalid comment at the boundary',
    async (comment) => {
      rpc.mockReturnValue({
        abortSignal: vi.fn().mockResolvedValue({ data: [{ ...item, current_comment: comment }] }),
      });
      await expect(
        repository().getCursor('synthetic-batch', null, 'resume', new AbortController().signal),
      ).rejects.toThrow('current review comment response was not valid');
    },
  );
});
