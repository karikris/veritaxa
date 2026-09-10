import type { ReviewLabelGroup } from './domain/reviewLabels';
import { createReviewDraft, submissionForDraft, type ReviewDraft } from './domain/reviewDraft';
import { countCodePoints, limitCodePoints } from './domain/text';
import { LABEL_BY_SHORTCUT, REVIEW_LABEL_GROUPS, REVIEW_LABELS } from './domain/reviewLabels';
import {
  MAX_COMMENT_LENGTH,
  normalizeComment,
  type ReviewBatch,
  type ReviewItem,
  type ReviewSubmission,
} from './domain/reviewQueue';
import {
  advanceImageAttempt,
  createImageAttempt,
  currentImageSource,
  type ImageAttempt,
} from './image/imageLoader';
import {
  ReviewConflictError,
  ReviewerAccessDisabledError,
  type ReviewerSession,
  type ReviewRepository,
} from './data/reviewRepository';

export type AppStateName =
  | 'config_error'
  | 'auth_loading'
  | 'signed_out'
  | 'loading_batches'
  | 'no_batches'
  | 'loading_image'
  | 'reviewing'
  | 'saving'
  | 'save_error'
  | 'navigation_error'
  | 'image_error'
  | 'empty_batch';

type AppOptions = {
  storage?: Storage;
};

const LAST_BATCH_KEY = 'veritaxa:last-batch-id';
const REVIEWER_NAME_KEY = 'veritaxa:reviewer-name';
const MIN_IMAGE_ZOOM = 1;
const MAX_IMAGE_ZOOM = 4;
const IMAGE_ZOOM_STEP = 0.25;

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function button(text: string, className: string): HTMLButtonElement {
  const node = element('button', className);
  node.type = 'button';
  node.textContent = text;
  return node;
}

export class VeriTaxaApp {
  readonly #root: HTMLElement;
  readonly #repository: ReviewRepository;
  readonly #storage: Storage | undefined;

  #state: AppStateName = 'auth_loading';
  #session: ReviewerSession | null = null;
  #batches: ReviewBatch[] = [];
  #batchId: string | null = null;
  #currentItem: ReviewItem | null = null;
  readonly #drafts = new Map<string, ReviewDraft>();
  #draft = createReviewDraft();
  #comparisonItem: ReviewItem | null = null;
  #imageAttempt: ImageAttempt | null = null;
  #imageZoom = MIN_IMAGE_ZOOM;
  #errorMessage = '';
  #authMessage = '';
  #requestId = 0;
  #requestController: AbortController | null = null;
  #unsubscribeAuth: (() => void) | null = null;
  #lastSaveSucceeded = false;
  #sessionEpoch = 0;
  #authRevision = 0;
  #started = false;
  #disposed = false;

  constructor(root: HTMLElement, repository: ReviewRepository, options: AppOptions = {}) {
    this.#root = root;
    this.#repository = repository;
    this.#storage = options.storage;
  }

  get state(): AppStateName {
    return this.#state;
  }

  async start(): Promise<void> {
    if (this.#started || this.#disposed) return;
    this.#started = true;
    const authRevision = this.#authRevision;
    this.#state = 'auth_loading';
    this.#render();
    document.addEventListener('keydown', this.#handleKeydown);
    this.#unsubscribeAuth = this.#repository.onAuthStateChange((session) => {
      this.#authRevision += 1;
      void this.#handleSession(session);
    });

    try {
      const session = await this.#repository.getSession();
      if (!this.#isCurrentAuthRevision(authRevision)) return;
      await this.#handleSession(session);
    } catch {
      if (!this.#isCurrentAuthRevision(authRevision)) return;
      this.#resetSession(null);
      this.#state = 'signed_out';
      this.#errorMessage = 'The sign-in session could not be restored.';
      this.#render();
    }
  }

  dispose(): void {
    this.#disposed = true;
    this.#resetSession(null);
    this.#unsubscribeAuth?.();
    this.#unsubscribeAuth = null;
    document.removeEventListener('keydown', this.#handleKeydown);
  }

  async #handleSession(session: ReviewerSession | null): Promise<void> {
    if (this.#disposed) return;
    if (this.#session?.userId === session?.userId && this.#state !== 'auth_loading') return;
    this.#resetSession(session);
    if (!session) {
      this.#state = 'signed_out';
      this.#render();
      return;
    }

    if (session.identifiedBy) this.#storage?.setItem(REVIEWER_NAME_KEY, session.identifiedBy);
    await this.#loadBatches();
  }

  #resetSession(session: ReviewerSession | null): void {
    this.#sessionEpoch += 1;
    this.#cancelRequests();
    this.#session = session;
    this.#batches = [];
    this.#batchId = null;
    this.#currentItem = null;
    this.#imageAttempt = null;
    this.#drafts.clear();
    this.#clearDraft();
    this.#lastSaveSucceeded = false;
    this.#errorMessage = '';
    this.#authMessage = '';
  }

  #ownsSession(epoch: number): boolean {
    return !this.#disposed && this.#sessionEpoch === epoch;
  }

  #isCurrentAuthRevision(revision: number): boolean {
    return !this.#disposed && this.#authRevision === revision;
  }

  async #loadBatches(): Promise<void> {
    const { id, signal } = this.#beginRequest();
    this.#state = 'loading_batches';
    this.#errorMessage = '';
    this.#render();

    try {
      const batches = await this.#repository.listBatches(signal);
      if (!this.#isCurrentRequest(id)) return;
      this.#batches = batches;
      if (batches.length === 0) {
        this.#state = 'no_batches';
        this.#render();
        return;
      }

      const storedId = this.#storage?.getItem(LAST_BATCH_KEY);
      const selected =
        batches.find((batch) => batch.id === storedId) ??
        batches.find((batch) => !batch.complete) ??
        batches[0];
      if (!selected) {
        this.#state = 'no_batches';
        this.#render();
        return;
      }
      await this.#selectBatch(selected.id);
    } catch (error) {
      if (!this.#isCurrentRequest(id) || isAbortError(error)) return;
      if (error instanceof ReviewerAccessDisabledError) {
        this.#resetSession(null);
        const epoch = this.#sessionEpoch;
        this.#state = 'signed_out';
        this.#errorMessage = error.message;
        this.#render();
        try {
          await this.#repository.signOut();
        } catch {
          if (!this.#ownsSession(epoch)) return;
          this.#errorMessage = `${error.message} The local session could not be cleared.`;
          this.#render();
        }
        return;
      }
      this.#state = 'no_batches';
      this.#errorMessage = messageFrom(error, 'Could not load review batches.');
      this.#render();
    }
  }

  async #selectBatch(batchId: string): Promise<void> {
    this.#rememberCurrentDraft();
    this.#batchId = batchId;
    this.#storage?.setItem(LAST_BATCH_KEY, batchId);
    this.#currentItem = null;
    this.#clearDraft();
    await this.#loadCursor(batchId, null, 'resume');
  }

  async #loadCursor(
    batchId: string,
    anchorPosition: number | null,
    direction: 'resume' | 'next' | 'previous',
  ): Promise<void> {
    const { id, signal } = this.#beginRequest();
    this.#state = 'loading_image';
    this.#errorMessage = '';
    this.#render();

    try {
      const item = await this.#repository.getCursor(batchId, anchorPosition, direction, signal);
      if (!this.#isCurrentRequest(id) || this.#batchId !== batchId) return;
      this.#currentItem = item;
      if (!item) {
        this.#state = 'empty_batch';
        this.#imageAttempt = null;
      } else {
        this.#updateBatchProgress(item);
        this.#restoreDraft(item);
        this.#prepareCurrentImage();
      }
      this.#render();
    } catch (error) {
      if (!this.#isCurrentRequest(id) || isAbortError(error)) return;
      this.#state = this.#currentItem ? 'navigation_error' : 'loading_image';
      this.#errorMessage = messageFrom(error, 'Could not load the requested image.');
      this.#render();
    }
  }

  #prepareCurrentImage(): void {
    this.#imageZoom = MIN_IMAGE_ZOOM;
    const current = this.#currentItem;
    if (!current) {
      this.#state = 'empty_batch';
      this.#imageAttempt = null;
      return;
    }
    this.#imageAttempt = createImageAttempt(current.displayUrl, current.fallbackImageUrl);
    this.#state = currentImageSource(this.#imageAttempt) ? 'reviewing' : 'image_error';
  }

  #beginRequest(): { id: number; signal: AbortSignal } {
    this.#cancelRequests();
    const controller = new AbortController();
    this.#requestController = controller;
    this.#requestId += 1;
    return { id: this.#requestId, signal: controller.signal };
  }

  #cancelRequests(): void {
    this.#requestController?.abort();
    this.#requestController = null;
    this.#requestId += 1;
  }

  #isCurrentRequest(id: number): boolean {
    return !this.#disposed && id === this.#requestId;
  }

  #clearDraft(): void {
    this.#draft = createReviewDraft();
    this.#comparisonItem = null;
  }

  #restoreDraft(item: ReviewItem): void {
    this.#draft = this.#drafts.get(item.id) ?? createReviewDraft(item);
    this.#drafts.delete(item.id);
    this.#comparisonItem = null;
  }

  #rememberCurrentDraft(): void {
    const item = this.#currentItem;
    if (!item) return;
    const persistedComment = item.currentComment ?? '';
    if (
      this.#draft.label === item.currentLabel &&
      this.#draft.comment === persistedComment &&
      this.#draft.pendingSubmission === null &&
      !this.#draft.conflicted
    ) {
      this.#drafts.delete(item.id);
      return;
    }
    this.#drafts.set(item.id, this.#draft);
  }

  async #navigate(direction: 'next' | 'previous'): Promise<void> {
    const current = this.#currentItem;
    const batchId = this.#batchId;
    if (!current || !batchId || this.#state === 'saving' || this.#state === 'loading_image') return;
    this.#rememberCurrentDraft();
    await this.#loadCursor(batchId, current.position, direction);
    this.#focusClassification();
  }

  async #submit(): Promise<void> {
    const current = this.#currentItem;
    if (
      !current ||
      !this.#batchId ||
      !this.#draft.label ||
      !this.#session ||
      this.#state === 'saving' ||
      this.#state === 'loading_image'
    ) {
      return;
    }
    if (this.#comparisonItem) return;
    if (this.#draft.conflicted) {
      await this.#compareSavedReview();
      return;
    }
    let submission: ReviewSubmission;
    try {
      submission = submissionForDraft(current.id, this.#draft);
    } catch (error) {
      this.#errorMessage = messageFrom(error, 'The comment is not valid.');
      this.#state = 'save_error';
      this.#render();
      return;
    }

    this.#draft.pendingSubmission = submission;
    const epoch = this.#sessionEpoch;
    const batchId = this.#batchId;
    this.#state = 'saving';
    this.#errorMessage = '';
    this.#render();

    try {
      const nextItem = await this.#repository.saveReview(submission);
      if (!this.#ownsSession(epoch) || this.#batchId !== batchId || this.#currentItem !== current)
        return;
      this.#updateBatchProgressValues(
        batchId,
        nextItem.reviewedCount,
        nextItem.totalCount,
        nextItem.complete,
      );
      this.#draft.pendingSubmission = null;
      this.#drafts.delete(current.id);
      if (
        this.#draft.label === submission.label &&
        normalizeComment(this.#draft.comment) === submission.comment
      ) {
        this.#lastSaveSucceeded = true;
        this.#currentItem = nextItem;
        this.#restoreDraft(nextItem);
        this.#prepareCurrentImage();
      } else {
        // The original write is confirmed, but edits made after its failure are still unsaved.
        this.#currentItem = {
          ...current,
          currentLabel: submission.label,
          currentComment: submission.comment,
          currentVersion: submission.expectedVersion + 1,
          reviewedCount: nextItem.reviewedCount,
          totalCount: nextItem.totalCount,
          complete: nextItem.complete,
        };
        this.#draft.baseVersion = submission.expectedVersion + 1;
        this.#lastSaveSucceeded = false;
        this.#state = 'reviewing';
        this.#errorMessage = 'Original save confirmed. Your newer changes are still unsaved.';
      }
      this.#render();
      this.#focusClassification();
    } catch (error) {
      if (!this.#ownsSession(epoch) || this.#batchId !== batchId || this.#currentItem !== current)
        return;
      if (error instanceof ReviewConflictError) {
        this.#draft.pendingSubmission = null;
        this.#draft.conflicted = true;
      }
      this.#rememberCurrentDraft();
      this.#state = 'save_error';
      this.#errorMessage = messageFrom(error, 'The classification could not be saved.');
      this.#render();
    }
  }

  #updateBatchProgress(item: ReviewItem | undefined): void {
    if (!item || !this.#batchId) return;
    this.#updateBatchProgressValues(
      this.#batchId,
      item.reviewedCount,
      item.totalCount,
      item.reviewedCount === item.totalCount && item.totalCount > 0,
    );
  }

  async #compareSavedReview(): Promise<void> {
    const current = this.#currentItem;
    const batchId = this.#batchId;
    if (!current || !batchId) return;
    const { id, signal } = this.#beginRequest();
    this.#state = 'loading_image';
    this.#errorMessage = '';
    this.#render();
    try {
      // Seek the same item through the existing owner-scoped RPC, not the resume cursor.
      const latest = await this.#repository.getCursor(
        batchId,
        current.position - 1,
        'next',
        signal,
      );
      if (!this.#isCurrentRequest(id) || this.#currentItem !== current) return;
      if (latest?.id !== current.id) {
        throw new Error('The saved answer is unavailable. Your draft has not changed.');
      }
      this.#comparisonItem = latest;
      this.#state = 'save_error';
      this.#errorMessage = 'Compare your draft with the saved answer, then choose which to keep.';
      this.#render();
    } catch (error) {
      if (!this.#isCurrentRequest(id) || this.#currentItem !== current) return;
      this.#state = 'save_error';
      this.#errorMessage = messageFrom(
        error,
        'Could not load the saved answer. Your draft has not changed.',
      );
      this.#render();
    }
  }

  #resolveConflict(latest: ReviewItem, useSaved: boolean): void {
    if (
      this.#comparisonItem !== latest ||
      this.#state === 'loading_image' ||
      this.#state === 'saving'
    )
      return;
    this.#currentItem = latest;
    this.#draft = useSaved
      ? createReviewDraft(latest)
      : {
          ...this.#draft,
          baseVersion: latest.currentVersion,
          pendingSubmission: null,
          conflicted: false,
        };
    this.#drafts.delete(latest.id);
    this.#comparisonItem = null;
    this.#lastSaveSucceeded = false;
    this.#updateBatchProgress(latest);
    this.#state = 'reviewing';
    this.#errorMessage = useSaved
      ? ''
      : 'Your changes are ready to send against the compared version.';
    this.#render();
    this.#focusClassification();
  }

  #buildConflictComparison(latest: ReviewItem): HTMLElement {
    const section = element('section', 'conflict-comparison');
    section.setAttribute('aria-label', 'Saved answer comparison');
    const heading = element('h3');
    heading.textContent = `Your saved answer (version ${String(latest.currentVersion)})`;
    const label = element('p');
    label.textContent =
      latest.currentLabel === 'target_scientific_name'
        ? latest.targetScientificName
        : (REVIEW_LABELS.find((candidate) => candidate.code === latest.currentLabel)
            ?.displayLabel ?? 'No classification');
    const comment = element('p');
    comment.textContent = latest.currentComment ?? 'No comment';
    const useSaved = button('Use saved answer', 'secondary-button');
    useSaved.addEventListener('click', () => this.#resolveConflict(latest, true));
    const reapply = button('Reapply my changes', 'secondary-button');
    reapply.addEventListener('click', () => this.#resolveConflict(latest, false));
    section.append(heading, label, comment, useSaved, reapply);
    return section;
  }

  #updateBatchProgressValues(
    batchId: string,
    reviewedCount: number,
    totalCount: number,
    complete: boolean,
  ): void {
    this.#batches = this.#batches.map((batch) =>
      batch.id === batchId ? { ...batch, reviewedCount, totalCount, complete } : batch,
    );
  }

  #focusClassification(): void {
    const epoch = this.#sessionEpoch;
    const item = this.#currentItem;
    queueMicrotask(() => {
      if (!this.#ownsSession(epoch) || this.#currentItem !== item) return;
      this.#root.querySelector<HTMLElement>('.classification-panel')?.focus();
    });
  }

  readonly #handleKeydown = (event: KeyboardEvent): void => {
    if (this.#disposed) return;
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      if (!this.#isEditableEmailOrSelector(event.target)) {
        event.preventDefault();
        void this.#submit();
      } else if (event.target instanceof HTMLTextAreaElement) {
        event.preventDefault();
        void this.#submit();
      }
      return;
    }

    if (event.ctrlKey || event.metaKey || event.altKey || this.#isEditable(event.target)) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      if (!this.#currentItem || this.#state === 'saving' || this.#state === 'loading_image') {
        return;
      }
      event.preventDefault();
      void this.#navigate(event.key === 'ArrowLeft' ? 'previous' : 'next');
      return;
    }

    const label = LABEL_BY_SHORTCUT.get(event.key.toLowerCase());
    if (
      !label ||
      !this.#currentItem ||
      this.#state === 'saving' ||
      this.#state === 'loading_image'
    ) {
      return;
    }
    if (label === 'target_scientific_name' && !this.#currentItem.targetScientificName) return;
    event.preventDefault();
    this.#draft.label = label;
    this.#render();
  };

  #isEditable(target: EventTarget | null): boolean {
    return (
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      target instanceof HTMLInputElement ||
      (target instanceof HTMLElement && target.isContentEditable)
    );
  }

  #isEditableEmailOrSelector(target: EventTarget | null): boolean {
    return (
      target instanceof HTMLInputElement ||
      target instanceof HTMLSelectElement ||
      (target instanceof HTMLElement && target.isContentEditable)
    );
  }

  #render(): void {
    if (this.#disposed) return;
    this.#root.replaceChildren();
    const shell = element('div', 'app-shell');
    shell.append(this.#buildHeader());

    if (this.#state === 'auth_loading') {
      shell.append(this.#buildCentredStatus('Checking sign-in…'));
    } else if (this.#state === 'signed_out') {
      shell.append(this.#buildLogin());
    } else {
      shell.append(this.#buildAuthenticatedMain());
    }

    this.#root.append(shell);
  }

  #buildHeader(): HTMLElement {
    const header = element('header', `site-header ${this.#session ? 'site-header--active' : ''}`);
    const brand = element('span', 'wordmark');
    brand.textContent = 'VeriTaxa';
    header.append(brand);

    if (!this.#session) return header;

    const controls = element('div', 'header-controls');
    if (this.#batches.length > 0) {
      const selectLabel = element('label', 'visually-hidden');
      selectLabel.htmlFor = 'batch-select';
      selectLabel.textContent = 'Review batch';
      const select = element('select', 'batch-select');
      select.id = 'batch-select';
      select.disabled =
        this.#state === 'saving' ||
        this.#state === 'loading_batches' ||
        this.#state === 'loading_image';
      for (const batch of this.#batches) {
        const option = element('option');
        option.value = batch.id;
        option.selected = batch.id === this.#batchId;
        option.textContent = `${batch.code} · ${batch.name}`;
        select.append(option);
      }
      select.addEventListener('change', () => {
        void this.#selectBatch(select.value);
      });
      controls.append(selectLabel, select);
    }

    const progress = element('span', 'header-progress');
    const activeBatch = this.#batches.find((batch) => batch.id === this.#batchId);
    progress.textContent = activeBatch
      ? `${String(activeBatch.reviewedCount)} / ${String(activeBatch.totalCount)}`
      : '— / —';

    const saveState = element('span', 'save-state');
    saveState.setAttribute('role', 'status');
    saveState.textContent =
      this.#state === 'saving'
        ? 'Saving…'
        : this.#state === 'save_error'
          ? 'Save failed'
          : this.#lastSaveSucceeded
            ? 'Saved'
            : '';

    const signOut = button('Sign out', 'text-button');
    signOut.addEventListener('click', () => {
      const epoch = this.#sessionEpoch;
      void this.#repository.signOut().catch(() => {
        if (!this.#ownsSession(epoch)) return;
        this.#errorMessage = 'Could not sign out. Try again.';
        this.#render();
      });
    });

    controls.append(progress, saveState, signOut);
    header.append(controls);
    return header;
  }

  #buildLogin(): HTMLElement {
    const main = element('main', 'login-shell');
    const panel = element('section', 'login-panel');
    panel.setAttribute('aria-labelledby', 'login-heading');
    const eyebrow = element('p', 'eyebrow');
    eyebrow.textContent = 'Review workspace';
    const heading = element('h1');
    heading.id = 'login-heading';
    heading.textContent = 'Join the review';
    const intro = element('p', 'login-copy');
    intro.textContent = 'Enter your name to start reviewing.';

    const form = element('form', 'login-form');
    const nameLabel = element('label');
    nameLabel.htmlFor = 'reviewer-name';
    nameLabel.textContent = 'Name';
    const nameField = element('input');
    nameField.id = 'reviewer-name';
    nameField.name = 'name';
    nameField.type = 'text';
    nameField.autocomplete = 'name';
    nameField.required = true;
    nameField.maxLength = 100;
    nameField.placeholder = 'Your name';
    nameField.value = this.#storage?.getItem(REVIEWER_NAME_KEY) ?? '';
    nameField.addEventListener('input', () => nameField.setCustomValidity(''));

    const submit = element('button', 'primary-button');
    submit.type = 'submit';
    submit.textContent = 'Start reviewing';
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      nameField.setCustomValidity(nameField.value.trim() ? '' : 'Enter your name.');
      if (!nameField.reportValidity()) return;
      const identifiedBy = nameField.value.trim();
      this.#storage?.setItem(REVIEWER_NAME_KEY, identifiedBy);
      submit.disabled = true;
      this.#authMessage = 'Starting review…';
      this.#errorMessage = '';
      this.#render();
      const epoch = this.#sessionEpoch;
      void this.#repository
        .signIn(identifiedBy)
        .then(() => {
          if (!this.#ownsSession(epoch)) return;
          this.#authMessage = '';
        })
        .catch((error: unknown) => {
          if (!this.#ownsSession(epoch)) return;
          this.#authMessage = '';
          this.#errorMessage = messageFrom(error, 'The review session could not be started.');
          this.#render();
        });
    });
    form.append(nameLabel, nameField, submit);
    panel.append(
      eyebrow,
      heading,
      intro,
      form,
      this.#buildLiveStatus(
        this.#errorMessage ||
          this.#authMessage ||
          'Your name, session, and review progress will be remembered on this device.',
        Boolean(this.#errorMessage),
      ),
    );
    main.append(panel);
    return main;
  }

  #buildAuthenticatedMain(): HTMLElement {
    if (this.#state === 'loading_batches') {
      return this.#buildCentredStatus('Loading review batches…');
    }
    if (this.#state === 'no_batches') {
      return this.#buildCentredStatus(this.#errorMessage || 'No review batches are available.');
    }
    if (this.#state === 'empty_batch') {
      return this.#buildCentredStatus('This batch has no images to review.');
    }

    const main = element('main', 'review-main');
    if (this.#state === 'loading_image' && !this.#currentItem) {
      main.append(this.#buildImageSkeleton());
      if (this.#errorMessage) {
        const retry = button('Retry image', 'secondary-button retry-queue');
        retry.addEventListener('click', () => {
          if (this.#batchId) void this.#loadCursor(this.#batchId, null, 'resume');
        });
        main.append(this.#buildLiveStatus(this.#errorMessage, true), retry);
      }
      return main;
    }

    const activeBatch = this.#batches.find((candidate) => candidate.id === this.#batchId);
    if (activeBatch?.complete) {
      const completeStatus = element('p', 'completion-status');
      completeStatus.setAttribute('role', 'status');
      completeStatus.textContent = 'All reviewed—answers can still be updated.';
      main.append(completeStatus);
    }
    main.append(this.#buildImageStage(), this.#buildClassifier());
    return main;
  }

  #buildImageSkeleton(): HTMLElement {
    const stage = element('section', 'image-stage image-stage--loading');
    stage.setAttribute('aria-label', 'Loading image');
    const message = element('span', 'stage-message');
    message.textContent = 'Loading image…';
    stage.append(message);
    return stage;
  }

  #buildImageStage(): HTMLElement {
    const stage = element('section', 'image-stage');
    stage.setAttribute('aria-label', 'Image under review');
    const current = this.#currentItem;
    const source = this.#imageAttempt ? currentImageSource(this.#imageAttempt) : null;

    if (this.#state === 'image_error' || !current || !source) {
      stage.classList.add('image-stage--error');
      const marker = element('span', 'image-error-marker');
      marker.setAttribute('aria-hidden', 'true');
      marker.textContent = '!';
      const heading = element('h2');
      heading.textContent = 'Image unavailable';
      const copy = element('p');
      copy.textContent = 'The source image could not be loaded.';
      const retry = button('Retry image', 'secondary-button');
      retry.disabled = this.#state === 'saving' || this.#state === 'loading_image';
      retry.addEventListener('click', () => {
        if (this.#state === 'saving' || this.#state === 'loading_image') return;
        this.#prepareCurrentImage();
        this.#render();
      });
      stage.append(marker, heading, copy, retry);
      if (current) stage.append(this.#buildImageNavigation(current));
      return stage;
    }

    const image = element('img', 'review-image');
    image.alt = 'Image under review';
    image.loading = 'eager';
    image.decoding = 'async';
    image.fetchPriority = 'high';
    image.referrerPolicy = 'no-referrer';
    image.src = source;
    const epoch = this.#sessionEpoch;
    let attempt = this.#imageAttempt;
    image.addEventListener('error', () => {
      if (
        !this.#ownsSession(epoch) ||
        this.#currentItem !== current ||
        !this.#root.contains(image) ||
        !attempt ||
        this.#imageAttempt !== attempt
      )
        return;
      const next = advanceImageAttempt(attempt);
      if (next) {
        attempt = next;
        this.#imageAttempt = next;
        const nextSource = currentImageSource(next);
        if (nextSource) image.src = nextSource;
      } else {
        this.#imageAttempt = null;
        if (this.#state === 'reviewing') this.#state = 'image_error';
        this.#render();
      }
    });

    const controls = element('div', 'image-zoom-controls');
    controls.setAttribute('role', 'group');
    controls.setAttribute('aria-label', 'Image zoom controls');
    const zoomOut = button('−', 'image-zoom-button');
    zoomOut.setAttribute('aria-label', 'Zoom out');
    zoomOut.title = 'Zoom out';
    const resetZoom = button('100%', 'image-zoom-button image-zoom-level');
    resetZoom.setAttribute('aria-label', 'Reset image zoom');
    resetZoom.title = 'Reset image zoom';
    const zoomIn = button('+', 'image-zoom-button');
    zoomIn.setAttribute('aria-label', 'Zoom in');
    zoomIn.title = 'Zoom in';

    const applyZoom = (): void => {
      const percentage = Math.round(this.#imageZoom * 100);
      image.style.setProperty('--image-zoom', String(this.#imageZoom));
      image.dataset.zoom = String(this.#imageZoom);
      zoomOut.disabled = this.#imageZoom <= MIN_IMAGE_ZOOM;
      zoomIn.disabled = this.#imageZoom >= MAX_IMAGE_ZOOM;
      resetZoom.disabled = this.#imageZoom === MIN_IMAGE_ZOOM;
      resetZoom.textContent = `${String(percentage)}%`;
      resetZoom.setAttribute('aria-label', `Reset image zoom from ${String(percentage)}%`);
    };

    zoomOut.addEventListener('click', () => {
      this.#imageZoom = Math.max(MIN_IMAGE_ZOOM, this.#imageZoom - IMAGE_ZOOM_STEP);
      applyZoom();
    });
    resetZoom.addEventListener('click', () => {
      this.#imageZoom = MIN_IMAGE_ZOOM;
      applyZoom();
    });
    zoomIn.addEventListener('click', () => {
      this.#imageZoom = Math.min(MAX_IMAGE_ZOOM, this.#imageZoom + IMAGE_ZOOM_STEP);
      applyZoom();
    });
    applyZoom();
    controls.append(zoomOut, resetZoom, zoomIn);
    stage.append(image, controls, this.#buildImageNavigation(current));
    return stage;
  }

  #buildImageNavigation(current: ReviewItem): HTMLElement {
    const disabled = this.#state === 'saving' || this.#state === 'loading_image';
    const navigation = element('nav', 'image-navigation');
    navigation.setAttribute('aria-label', 'Review image navigation');
    const previous = button('Previous', 'image-navigation-button');
    previous.setAttribute('aria-label', 'Previous image');
    previous.disabled = disabled;
    previous.addEventListener('click', () => void this.#navigate('previous'));
    const position = element('span', 'image-position');
    position.textContent = `${String(current.position)} / ${String(current.totalCount)}`;
    const next = button('Next', 'image-navigation-button');
    next.setAttribute('aria-label', 'Next image');
    next.disabled = disabled;
    next.addEventListener('click', () => void this.#navigate('next'));
    navigation.append(previous, position, next);
    return navigation;
  }

  #buildClassifier(): HTMLElement {
    const disabled = this.#state === 'saving' || this.#state === 'loading_image';
    const section = element('section', 'classification-panel');
    section.tabIndex = -1;
    section.setAttribute('aria-labelledby', 'classification-heading');
    const headingRow = element('div', 'classification-heading-row');
    const heading = element('h2');
    heading.id = 'classification-heading';
    heading.textContent = 'How should this image be classified?';
    const instruction = element('p');
    instruction.textContent = 'Choose the best matching option.';
    headingRow.append(heading, instruction);

    const group = element('div', 'label-groups');
    group.setAttribute('role', 'radiogroup');
    group.setAttribute('aria-labelledby', 'classification-heading');
    for (const definition of REVIEW_LABEL_GROUPS) {
      if (definition.code === 'target_taxon' && !this.#currentItem?.targetScientificName) continue;
      group.append(this.#buildLabelGroup(definition.code, definition.heading, disabled));
    }

    const form = element('div', 'submission-panel');
    const commentHeader = element('div', 'comment-heading');
    const commentLabel = element('label');
    commentLabel.htmlFor = 'review-comment';
    commentLabel.textContent = 'Comment';
    const optional = element('span');
    optional.textContent = 'optional';
    commentHeader.append(commentLabel, optional);
    const textarea = element('textarea');
    textarea.id = 'review-comment';
    textarea.rows = 2;
    textarea.disabled = disabled;
    textarea.value = this.#draft.comment;
    textarea.addEventListener('input', () => {
      const limited = limitCodePoints(textarea.value, MAX_COMMENT_LENGTH);
      textarea.value = limited.value;
      this.#draft.comment = textarea.value;
      const remaining = MAX_COMMENT_LENGTH - limited.length;
      const counter = this.#root.querySelector<HTMLElement>('.comment-count');
      if (counter) {
        counter.textContent = remaining <= 100 ? `${String(remaining)} remaining` : '';
      }
    });
    const counter = element('span', 'comment-count');
    const initialRemaining = MAX_COMMENT_LENGTH - countCodePoints(this.#draft.comment);
    counter.textContent = initialRemaining <= 100 ? `${String(initialRemaining)} remaining` : '';

    const send = element('button', 'send-button');
    send.type = 'button';
    send.textContent = this.#draft.conflicted
      ? 'Compare saved answer'
      : this.#draft.pendingSubmission
        ? 'Retry save'
        : 'Send';
    send.setAttribute(
      'aria-label',
      this.#draft.conflicted
        ? 'Compare saved answer'
        : this.#draft.pendingSubmission
          ? 'Retry original save'
          : 'Save this classification and advance',
    );
    send.disabled =
      disabled ||
      !!this.#comparisonItem ||
      !this.#draft.label ||
      !this.#batchId ||
      !this.#currentItem ||
      !this.#session;
    send.addEventListener('click', () => void this.#submit());

    const action = element('div', 'submission-action');
    action.append(
      this.#buildLiveStatus(
        this.#errorMessage ||
          (this.#state === 'saving'
            ? 'Saving classification…'
            : 'Select one label, then send when ready.'),
        this.#state === 'save_error' || this.#state === 'navigation_error',
      ),
      send,
    );
    form.append(commentHeader, textarea, counter, action);
    if (this.#draft.pendingSubmission && this.#state !== 'saving') {
      form.append(
        this.#buildLiveStatus(
          'Retry sends the original request. Any newer edits will remain unsaved until you send them separately.',
          false,
        ),
      );
    }
    if (this.#comparisonItem) form.append(this.#buildConflictComparison(this.#comparisonItem));
    section.append(headingRow, group, form);
    return section;
  }

  #buildLabelGroup(
    groupCode: ReviewLabelGroup,
    headingText: string,
    disabled: boolean,
  ): HTMLElement {
    const section = element('section', 'label-group');
    if (groupCode === 'target_taxon') section.classList.add('label-group--target-taxon');
    const heading = element('h3');
    heading.textContent = headingText;
    const grid = element('div', 'label-grid');
    for (const label of REVIEW_LABELS.filter((candidate) => candidate.group === groupCode)) {
      const wrapper = element('label', 'label-option');
      const input = element('input');
      input.type = 'radio';
      input.name = 'review-label';
      input.value = label.code;
      input.checked = this.#draft.label === label.code;
      input.disabled = disabled;
      input.addEventListener('change', () => {
        if (input.checked) {
          this.#draft.label = label.code;
          this.#render();
        }
      });
      const card = element('span', 'label-card');
      const check = element('span', 'label-check');
      check.setAttribute('aria-hidden', 'true');
      check.textContent = '✓';
      const text = element('span', 'label-text');
      text.textContent =
        label.code === 'target_scientific_name'
          ? (this.#currentItem?.targetScientificName ?? '')
          : label.displayLabel;
      const shortcut = element('kbd');
      shortcut.textContent = label.shortcut;
      shortcut.setAttribute('aria-hidden', 'true');
      card.append(check, text, shortcut);
      wrapper.append(input, card);
      grid.append(wrapper);
    }
    section.append(heading, grid);
    return section;
  }

  #buildCentredStatus(message: string): HTMLElement {
    const main = element('main', 'status-shell');
    main.append(this.#buildLiveStatus(message, Boolean(this.#errorMessage)));
    return main;
  }

  #buildLiveStatus(message: string, isError: boolean): HTMLElement {
    const status = element('p', `status-text ${isError ? 'status-text--error' : ''}`);
    status.setAttribute('role', isError ? 'alert' : 'status');
    status.setAttribute('aria-live', isError ? 'assertive' : 'polite');
    status.textContent = message;
    return status;
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
