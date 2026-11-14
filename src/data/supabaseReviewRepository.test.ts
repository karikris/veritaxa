import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SupabaseReviewRepository } from './supabaseReviewRepository';
import { normalizeComment } from '../domain/reviewQueue';
import { ReviewConflictError } from './reviewRepository';

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
  team_reviewed_count: 1,
  reviewed_by_anyone: true,
};

function repository() {
  return new SupabaseReviewRepository({
    supabaseUrl: 'https://example-project.supabase.co',
    supabasePublishableKey: 'sb_publishable_synthetic_test',
  });
}

describe('review RPC response boundary', () => {
  beforeEach(() => rpc.mockReset());

  it('reads only the requested model name and finite raw cosine', async () => {
    rpc.mockReturnValue({ abortSignal: vi.fn().mockResolvedValue({ data: [{
      ...item, model_scientific_name: 'Papilio testensis', model_cosine: 0.6789,
      pipeline_metadata: { secret_source: 'synthetic private metadata' },
    }] }) });
    const result = await repository().getCursor('synthetic-batch', null, 'resume', new AbortController().signal);
    expect(result?.modelScientificName).toBe('Papilio testensis');
    expect(result?.modelCosine).toBe(0.6789);
    expect(result).not.toHaveProperty('pipeline_metadata');
  });

  it.each([NaN, Infinity, -Infinity, 1.1, -1.1, '0.6'])(
    'rejects an invalid model cosine (%s)', async (cosine) => {
      rpc.mockReturnValue({ abortSignal: vi.fn().mockResolvedValue({ data: [{
        ...item, model_scientific_name: 'Papilio testensis', model_cosine: cosine,
      }] }) });
      await expect(repository().getCursor('synthetic-batch', null, 'resume', new AbortController().signal))
        .rejects.toThrow('model cosine response was not valid');
    },
  );

  it('accepts count-only shared progress without retaining private metadata', async () => {
    rpc.mockReturnValue({ abortSignal: vi.fn().mockResolvedValue({ data: [{
      batch_id: '30000000-0000-0000-0000-000000000001',
      reviewer_name: 'Synthetic dataset', batch_code: 'SYNTH-001',
      reviewed_count: 0, total_count: 2, complete: false, team_reviewed_count: 1,
      review_round: 2, pipeline_metadata: { private: 'synthetic detail' },
    }] }) });
    const [batch] = await repository().listBatches(new AbortController().signal);
    expect(batch?.teamReviewedCount).toBe(1);
    expect(batch?.reviewRound).toBe(2);
    expect(batch).not.toHaveProperty('pipeline_metadata');
  });

  it('reads the shared image status without exposing another reviewer’s answer', async () => {
    rpc.mockReturnValue({ abortSignal: vi.fn().mockResolvedValue({ data: [{
      ...item, current_label: null, current_version: 0, reviewed_count: 0,
      another_review: { label: 'plant', name: 'Synthetic other reviewer' },
    }] }) });
    const result = await repository().getCursor('synthetic-batch', null, 'resume', new AbortController().signal);
    expect(result?.reviewedByAnyone).toBe(true);
    expect(result?.currentLabel).toBeNull();
    expect(result).not.toHaveProperty('another_review');
  });

  it.each([
    ['40001', 'stale_version'],
    ['23505', 'submission_conflict'],
  ] as const)('maps %s to a typed conflict without exposing server details', async (code, kind) => {
    rpc.mockResolvedValue({ error: { code, message: 'Synthetic private server detail' } });
    const result = repository().saveReview({
      itemId: item.item_id,
      label: 'plant',
      comment: null,
      submissionId: '50000000-0000-0000-0000-000000000001',
      clientVersion: 'synthetic-client',
      expectedVersion: 1,
    });
    await expect(result).rejects.toBeInstanceOf(ReviewConflictError);
    await expect(result).rejects.toHaveProperty('kind', kind);
    await expect(result).rejects.not.toHaveProperty('message', 'Synthetic private server detail');
  });

  it('keeps unknown failures generic and validates the returned cursor after saving', async () => {
    const submission = {
      itemId: item.item_id,
      label: 'plant' as const,
      comment: '🦋'.repeat(1000),
      submissionId: '50000000-0000-0000-0000-000000000001',
      clientVersion: 'synthetic-client',
      expectedVersion: 1,
    };
    rpc.mockResolvedValueOnce({ error: { code: 'XX000', message: 'Synthetic private detail' } });
    await expect(repository().saveReview(submission)).rejects.toThrow(
      'The classification could not be saved.',
    );
    rpc.mockResolvedValueOnce({
      data: [
        {
          ...item,
          current_comment: submission.comment,
          hidden_metadata: 'synthetic private detail',
        },
      ],
    });
    const result = await repository().saveReview(submission);
    expect(result.currentComment).toBe(submission.comment);
    expect(result).not.toHaveProperty('hidden_metadata');
    expect(rpc).toHaveBeenLastCalledWith('save_image_review_v4', {
      p_item_id: submission.itemId,
      p_label: submission.label,
      p_comment: submission.comment,
      p_submission_id: submission.submissionId,
      p_client_version: submission.clientVersion,
      p_expected_version: submission.expectedVersion,
    });
  });

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
