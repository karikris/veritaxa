import { ReviewView } from './view/reviewView';
import { createReviewDraft, submissionForDraft, type ReviewDraft } from './domain/reviewDraft';
import { limitCodePoints } from './domain/text';
import { LABEL_BY_SHORTCUT } from './domain/reviewLabels';
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
  readonly #shell = element('div', 'app-shell');
  #main: HTMLElement | null = null;
  #reviewView: ReviewView | null = null;
  #updateHeader: (() => void) | null = null;

  #state: AppStateName = 'auth_loading';
  #session: ReviewerSession | null = null;
  #batches: ReviewBatch[] = [];
  #batchId: string | null = null;
  #currentItem: ReviewItem | null = null;
  readonly #drafts = new Map<string, ReviewDraft>();
  #draft = createReviewDraft();
  #comparisonItem: ReviewItem | null = null;
  #imageAttempt: ImageAttempt | null = null;
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
    this.#updateHeader?.();
    this.#updateHeader = null;
    this.#main = null;
    this.#shell.replaceChildren();
    this.#root.replaceChildren();
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
    this.#reviewView?.dispose();
    this.#reviewView = null;
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
    this.#imageAttempt = null;
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
    if (!this.#updateHeader) {
      this.#shell.append(this.#buildHeader());
      this.#root.replaceChildren(this.#shell);
    }
    this.#updateHeader?.();
    let main: HTMLElement;
    if (this.#state === 'auth_loading') {
      main = this.#buildCentredStatus('Checking sign-in…');
    } else if (this.#state === 'signed_out') {
      main = this.#main?.classList.contains('login-shell') ? this.#main : this.#buildLogin();
      const status = main.querySelector<HTMLElement>('.status-text');
      if (status) {
        status.textContent =
          this.#errorMessage ||
          this.#authMessage ||
          'Your name, session, and review progress will be remembered on this device.';
        status.classList.toggle('status-text--error', !!this.#errorMessage);
        status.setAttribute('role', this.#errorMessage ? 'alert' : 'status');
      }
      const submit = main.querySelector<HTMLButtonElement>('[type="submit"]');
      if (submit) submit.disabled = !!this.#authMessage;
    } else if (
      this.#state === 'loading_batches' ||
      this.#state === 'no_batches' ||
      this.#state === 'empty_batch'
    ) {
      main = this.#buildCentredStatus(
        this.#state === 'loading_batches'
          ? 'Loading review batches…'
          : this.#state === 'empty_batch'
            ? 'This batch has no images to review.'
            : this.#errorMessage || 'No review batches are available.',
      );
    } else {
      this.#reviewView ??= this.#createReviewView();
      const busy = this.#state === 'saving' || this.#state === 'loading_image';
      this.#reviewView.update({
        item: this.#currentItem,
        draft: this.#draft,
        comparison: this.#comparisonItem,
        sources: this.#imageAttempt?.sources ?? null,
        source: this.#imageAttempt ? currentImageSource(this.#imageAttempt) : null,
        busy,
        saving: this.#state === 'saving',
        canSubmit:
          !busy &&
          !this.#comparisonItem &&
          !!this.#draft.label &&
          !!this.#batchId &&
          !!this.#currentItem &&
          !!this.#session,
        errorMessage: this.#errorMessage,
        isError: this.#state === 'save_error' || this.#state === 'navigation_error',
        complete: this.#batches.find((batch) => batch.id === this.#batchId)?.complete ?? false,
      });
      main = this.#reviewView.element;
    }
    if (this.#reviewView && main !== this.#reviewView.element) {
      this.#reviewView.dispose();
      this.#reviewView = null;
    }
    if (main !== this.#main) {
      this.#main?.remove();
      this.#shell.append(main);
      this.#main = main;
    }
  }

  #createReviewView(): ReviewView {
    const epoch = this.#sessionEpoch;
    const owns = (): boolean => this.#ownsSession(epoch) && this.#reviewView === view;
    const view: ReviewView = new ReviewView({
      selectLabel: (label) => {
        if (!owns()) return;
        this.#draft.label = label;
        this.#render();
      },
      editComment: (comment) => {
        if (!owns()) return;
        this.#draft.comment = limitCodePoints(comment, MAX_COMMENT_LENGTH).value;
        this.#render();
      },
      submit: () => {
        if (owns()) void this.#submit();
      },
      navigate: (direction) => {
        if (owns()) void this.#navigate(direction);
      },
      retryImage: () => {
        if (!owns()) return;
        if (!this.#currentItem) {
          if (this.#batchId) void this.#loadCursor(this.#batchId, null, 'resume');
          return;
        }
        if (this.#state === 'saving' || this.#state === 'loading_image') return;
        this.#prepareCurrentImage();
        this.#render();
      },
      resolveConflict: (useSaved) => {
        if (owns() && this.#comparisonItem) this.#resolveConflict(this.#comparisonItem, useSaved);
      },
      imageError: (sources) => {
        const attempt = this.#imageAttempt;
        if (!owns() || attempt?.sources !== sources) return;
        this.#imageAttempt = advanceImageAttempt(attempt);
        if (!this.#imageAttempt && this.#state === 'reviewing') this.#state = 'image_error';
        this.#render();
      },
    });
    return view;
  }

  #buildHeader(): HTMLElement {
    const header = element('header', 'site-header');
    const brand = element('span', 'wordmark');
    brand.textContent = 'VeriTaxa';
    const controls = element('div', 'header-controls');
    const selectLabel = element('label', 'visually-hidden');
    selectLabel.htmlFor = 'batch-select';
    selectLabel.textContent = 'Review batch';
    const select = element('select', 'batch-select');
    select.id = 'batch-select';
    select.addEventListener('change', () => {
      if (!this.#disposed && this.#session && !select.disabled)
        void this.#selectBatch(select.value);
    });
    const progress = element('span', 'header-progress');
    const saveState = element('span', 'save-state');
    saveState.setAttribute('role', 'status');
    const signOut = button('Sign out', 'text-button');
    signOut.addEventListener('click', () => {
      if (this.#disposed || !this.#session) return;
      const epoch = this.#sessionEpoch;
      void this.#repository.signOut().catch(() => {
        if (!this.#ownsSession(epoch)) return;
        this.#errorMessage = 'Could not sign out. Try again.';
        this.#render();
      });
    });
    controls.append(selectLabel, select, progress, saveState, signOut);
    header.append(brand, controls);
    this.#updateHeader = () => {
      header.classList.toggle('site-header--active', !!this.#session);
      controls.hidden = !this.#session;
      select.hidden = selectLabel.hidden = this.#batches.length === 0;
      select.disabled =
        this.#state === 'saving' ||
        this.#state === 'loading_batches' ||
        this.#state === 'loading_image';
      while (select.options.length > this.#batches.length) select.remove(select.options.length - 1);
      this.#batches.forEach((batch, index) => {
        let option = select.options[index];
        if (!option) {
          option = element('option');
          select.add(option);
        }
        if (option.value !== batch.id) option.value = batch.id;
        const text = `${batch.code} · ${batch.name}`;
        if (option.textContent !== text) option.textContent = text;
      });
      select.value = this.#batchId ?? '';
      const active = this.#batches.find((batch) => batch.id === this.#batchId);
      progress.textContent = active
        ? `${String(active.reviewedCount)} / ${String(active.totalCount)}`
        : '— / —';
      saveState.textContent =
        this.#state === 'saving'
          ? 'Saving…'
          : this.#state === 'save_error'
            ? 'Save failed'
            : this.#lastSaveSucceeded
              ? 'Saved'
              : '';
    };
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
