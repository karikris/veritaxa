import { createClient, type SupabaseClient } from '@supabase/supabase-js';

import type { PublicConfig } from '../config';
import { isReviewLabelCode } from '../domain/reviewLabels';
import type {
  ReviewBatch,
  ReviewItem,
  ReviewProgress,
  ReviewSubmission,
} from '../domain/reviewQueue';
import type { Database } from './database.types';
import {
  ReviewerNotAuthorizedError,
  type AuthEventHandler,
  type ReviewerSession,
  type ReviewRepository,
} from './reviewRepository';

const MAX_BATCH_NAME_LENGTH = 120;
const MAX_BATCH_CODE_LENGTH = 80;
const MAX_IMAGE_ID_LENGTH = 500;

export class SupabaseReviewRepository implements ReviewRepository {
  readonly #client: SupabaseClient<Database>;

  constructor(config: PublicConfig) {
    this.#client = createClient<Database>(config.supabaseUrl, config.supabasePublishableKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
  }

  async getSession(): Promise<ReviewerSession | null> {
    const { data, error } = await this.#client.auth.getSession();
    if (error) throw new Error('Could not restore the sign-in session.');
    return sessionFromEmail(data.session?.user.email);
  }

  onAuthStateChange(handler: AuthEventHandler): () => void {
    const {
      data: { subscription },
    } = this.#client.auth.onAuthStateChange((_event, session) => {
      handler(sessionFromEmail(session?.user.email));
    });
    return () => subscription.unsubscribe();
  }

  async sendMagicLink(email: string, redirectTo: string): Promise<void> {
    const { error } = await this.#client.auth.signInWithOtp({
      email,
      options: {
        shouldCreateUser: false,
        emailRedirectTo: redirectTo,
      },
    });
    if (error)
      throw new Error('The sign-in link could not be sent. Check the address and try again.');
  }

  async signOut(): Promise<void> {
    const { error } = await this.#client.auth.signOut();
    if (error) throw new Error('Could not sign out. Try again.');
  }

  async listBatches(signal: AbortSignal): Promise<ReviewBatch[]> {
    const { data, error } = await this.#client.rpc('list_review_batches').abortSignal(signal);
    if (signal.aborted) throw new DOMException('Request cancelled', 'AbortError');
    if (error?.code === '42501') throw new ReviewerNotAuthorizedError();
    if (error) throw new Error('Could not load review batches.');
    if (!Array.isArray(data)) throw new Error('The batch response was not valid.');
    return data.map(parseBatch);
  }

  async getQueue(batchId: string, limit: number, signal: AbortSignal): Promise<ReviewItem[]> {
    const { data, error } = await this.#client
      .rpc('get_review_queue', { p_batch_id: batchId, p_limit: limit })
      .abortSignal(signal);
    if (signal.aborted) throw new DOMException('Request cancelled', 'AbortError');
    if (error) throw new Error('Could not load the review queue.');
    if (!Array.isArray(data)) throw new Error('The review queue response was not valid.');
    return data.map(parseItem);
  }

  async submitReview(submission: ReviewSubmission): Promise<ReviewProgress> {
    const { data, error } = await this.#client.rpc('submit_image_review', {
      p_client_version: submission.clientVersion,
      p_comment: submission.comment,
      p_item_id: submission.itemId,
      p_label: submission.label,
      p_submission_id: submission.submissionId,
    });
    if (error) throw new Error('The classification could not be saved.');
    const first = Array.isArray(data) ? data[0] : undefined;
    return parseProgress(first);
  }
}

function sessionFromEmail(email: string | undefined): ReviewerSession | null {
  return email ? { email } : null;
}

function parseBatch(value: unknown): ReviewBatch {
  const row = asRecord(value, 'batch');
  return {
    id: requiredString(row.batch_id, 36, 'batch ID'),
    name: requiredString(row.reviewer_name, MAX_BATCH_NAME_LENGTH, 'batch name'),
    code: requiredString(row.batch_code, MAX_BATCH_CODE_LENGTH, 'batch code'),
    reviewedCount: requiredCount(row.reviewed_count, 'reviewed count'),
    totalCount: requiredCount(row.total_count, 'total count'),
    complete: requiredBoolean(row.complete, 'completion state'),
  };
}

function parseItem(value: unknown): ReviewItem {
  const row = asRecord(value, 'review item');
  const displayUrl = row.display_url;
  return {
    id: requiredString(row.item_id, 36, 'item ID'),
    imageId: requiredString(row.image_id, MAX_IMAGE_ID_LENGTH, 'image ID'),
    displayUrl: displayUrl === null ? null : requiredString(displayUrl, 2048, 'display image URL'),
    fallbackImageUrl: requiredString(row.fallback_image_url, 2048, 'fallback image URL'),
    position: requiredCount(row.position, 'item position'),
    reviewedCount: requiredCount(row.reviewed_count, 'reviewed count'),
    totalCount: requiredCount(row.total_count, 'total count'),
  };
}

function parseProgress(value: unknown): ReviewProgress {
  const row = asRecord(value, 'save response');
  return {
    reviewedCount: requiredCount(row.reviewed_count, 'reviewed count'),
    totalCount: requiredCount(row.total_count, 'total count'),
    complete: requiredBoolean(row.complete, 'completion state'),
  };
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`The ${label} response was not valid.`);
  }
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, maxLength: number, label: string): string {
  if (typeof value !== 'string' || value.length === 0 || value.length > maxLength) {
    throw new Error(`The ${label} response was not valid.`);
  }
  return value;
}

function requiredCount(value: unknown, label: string): number {
  const numberValue = typeof value === 'string' ? Number(value) : value;
  if (typeof numberValue !== 'number' || !Number.isSafeInteger(numberValue) || numberValue < 0) {
    throw new Error(`The ${label} response was not valid.`);
  }
  return numberValue;
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') throw new Error(`The ${label} response was not valid.`);
  return value;
}

export function assertCanonicalSubmission(value: unknown): asserts value is ReviewSubmission {
  const row = asRecord(value, 'submission');
  if (!isReviewLabelCode(row.label)) throw new Error('The review label was not valid.');
}
