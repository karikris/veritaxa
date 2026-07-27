import type { ReviewLabelCode, ReviewLabelGroup } from './domain/reviewLabels';
import { LABEL_BY_SHORTCUT, REVIEW_LABEL_GROUPS, REVIEW_LABELS } from './domain/reviewLabels';
import {
  CLIENT_VERSION,
  createSubmissionId,
  MAX_COMMENT_LENGTH,
  normalizeComment,
  type ReviewBatch,
  type ReviewItem,
} from './domain/reviewQueue';
import {
  advanceImageAttempt,
  createImageAttempt,
  currentImageSource,
  type ImageAttempt,
} from './image/imageLoader';
import { ImagePrefetch } from './image/imagePrefetch';
import {
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
  | 'image_error'
  | 'batch_complete';

type NavigatorWithConnection = Navigator & {
  readonly connection?: { readonly saveData?: boolean };
};

type AppOptions = {
  storage?: Storage;
  imagePrefetch?: ImagePrefetch;
  navigator?: NavigatorWithConnection;
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
  readonly #prefetch: ImagePrefetch;
  readonly #navigator: NavigatorWithConnection;

  #state: AppStateName = 'auth_loading';
  #session: ReviewerSession | null = null;
  #batches: ReviewBatch[] = [];
  #batchId: string | null = null;
  #queue: ReviewItem[] = [];
  #selectedLabel: ReviewLabelCode | null = null;
  #comment = '';
  #submissionId: string | null = null;
  #imageAttempt: ImageAttempt | null = null;
  #imageZoom = MIN_IMAGE_ZOOM;
  #errorMessage = '';
  #authMessage = '';
  #requestId = 0;
  #requestController: AbortController | null = null;
  #unsubscribeAuth: (() => void) | null = null;
  #lastSaveSucceeded = false;

  constructor(root: HTMLElement, repository: ReviewRepository, options: AppOptions = {}) {
    this.#root = root;
    this.#repository = repository;
    this.#storage = options.storage;
    this.#prefetch = options.imagePrefetch ?? new ImagePrefetch();
    this.#navigator = options.navigator ?? navigator;
  }

  get state(): AppStateName {
    return this.#state;
  }

  async start(): Promise<void> {
    this.#state = 'auth_loading';
    this.#render();
    this.#unsubscribeAuth = this.#repository.onAuthStateChange((session) => {
      void this.#handleSession(session);
    });

    try {
      await this.#handleSession(await this.#repository.getSession());
    } catch {
      this.#session = null;
      this.#state = 'signed_out';
      this.#errorMessage = 'The sign-in session could not be restored.';
      this.#render();
    }

    document.addEventListener('keydown', this.#handleKeydown);
  }

  dispose(): void {
    this.#cancelRequests();
    this.#unsubscribeAuth?.();
    this.#unsubscribeAuth = null;
    this.#prefetch.invalidate();
    document.removeEventListener('keydown', this.#handleKeydown);
  }

  async #handleSession(session: ReviewerSession | null): Promise<void> {
    if (!session) {
      this.#cancelRequests();
      this.#session = null;
      this.#batches = [];
      this.#batchId = null;
      this.#queue = [];
      this.#clearDraft();
      this.#state = 'signed_out';
      this.#render();
      return;
    }

    if (this.#session?.userId === session.userId && this.#batches.length > 0) return;
    this.#session = session;
    if (session.identifiedBy) this.#storage?.setItem(REVIEWER_NAME_KEY, session.identifiedBy);
    await this.#loadBatches();
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
        this.#cancelRequests();
        this.#session = null;
        this.#batches = [];
        this.#batchId = null;
        this.#queue = [];
        this.#clearDraft();
        this.#state = 'signed_out';
        this.#errorMessage = error.message;
        this.#render();
        try {
          await this.#repository.signOut();
        } catch {
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
    this.#batchId = batchId;
    this.#storage?.setItem(LAST_BATCH_KEY, batchId);
    this.#queue = [];
    this.#clearDraft();
    this.#prefetch.invalidate();
    await this.#loadQueue(batchId);
  }

  async #loadQueue(batchId: string, preserveCurrent = false): Promise<void> {
    const { id, signal } = this.#beginRequest();
    if (!preserveCurrent) this.#state = 'loading_image';
    this.#errorMessage = '';
    if (!preserveCurrent) this.#render();

    try {
      const queue = await this.#repository.getQueue(batchId, 2, signal);
      if (!this.#isCurrentRequest(id) || this.#batchId !== batchId) return;
      this.#queue = queue;
      if (queue.length === 0) {
        this.#state = 'batch_complete';
        this.#imageAttempt = null;
        this.#updateBatchProgressFromCompletion();
      } else {
        this.#updateBatchProgress(queue[0]);
        this.#prepareCurrentImage();
      }
      this.#render();
    } catch (error) {
      if (!this.#isCurrentRequest(id) || isAbortError(error)) return;
      this.#state = 'loading_image';
      this.#errorMessage = messageFrom(error, 'Could not load the next image.');
      this.#render();
    }
  }

  #prepareCurrentImage(): void {
    this.#imageZoom = MIN_IMAGE_ZOOM;
    const current = this.#queue[0];
    if (!current) {
      this.#state = 'batch_complete';
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
    return id === this.#requestId;
  }

  #clearDraft(): void {
    this.#selectedLabel = null;
    this.#comment = '';
    this.#submissionId = null;
  }

  async #submit(): Promise<void> {
    const current = this.#queue[0];
    if (!current || !this.#batchId || !this.#selectedLabel || !this.#session) return;

    let comment: string | null;
    try {
      comment = normalizeComment(this.#comment);
    } catch (error) {
      this.#errorMessage = messageFrom(error, 'The comment is not valid.');
      this.#state = 'save_error';
      this.#render();
      return;
    }

    this.#submissionId = createSubmissionId(this.#submissionId);
    this.#state = 'saving';
    this.#errorMessage = '';
    this.#render();

    try {
      const progress = await this.#repository.submitReview({
        itemId: current.id,
        label: this.#selectedLabel,
        comment,
        submissionId: this.#submissionId,
        clientVersion: CLIENT_VERSION,
      });
      const activeBatchId = this.#batchId;
      this.#updateBatchProgressValues(
        activeBatchId,
        progress.reviewedCount,
        progress.totalCount,
        progress.complete,
      );
      this.#lastSaveSucceeded = true;
      this.#queue = this.#queue.slice(1);
      this.#clearDraft();
      this.#prefetch.invalidate();

      if (progress.complete || this.#queue.length === 0) {
        await this.#loadQueue(activeBatchId);
      } else {
        this.#prepareCurrentImage();
        this.#render();
        this.#focusClassification();
        await this.#loadQueue(activeBatchId, true);
        this.#focusClassification();
      }
    } catch (error) {
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

  #updateBatchProgressFromCompletion(): void {
    if (!this.#batchId) return;
    const batch = this.#batches.find((candidate) => candidate.id === this.#batchId);
    if (!batch) return;
    this.#updateBatchProgressValues(this.#batchId, batch.totalCount, batch.totalCount, true);
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
    queueMicrotask(() => {
      this.#root.querySelector<HTMLElement>('.classification-panel')?.focus();
    });
  }

  readonly #handleKeydown = (event: KeyboardEvent): void => {
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
    const label = LABEL_BY_SHORTCUT.get(event.key.toLowerCase());
    if (!label || !this.#queue[0] || this.#state === 'saving') return;
    if (label === 'flickr_keyword_match' && !this.#queue[0].flickrKeyword) return;
    event.preventDefault();
    this.#selectedLabel = label;
    this.#render();
  };

  #isEditable(target: EventTarget | null): boolean {
    return (
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      (target instanceof HTMLInputElement && target.type !== 'radio') ||
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
      select.disabled = this.#state === 'saving' || this.#state === 'loading_batches';
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
      void this.#repository.signOut().catch(() => {
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
      void this.#repository
        .signIn(identifiedBy)
        .then(() => {
          this.#authMessage = '';
        })
        .catch((error: unknown) => {
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
    if (this.#state === 'batch_complete') {
      const batch = this.#batches.find((candidate) => candidate.id === this.#batchId);
      const main = element('main', 'completion-shell');
      const panel = element('section', 'completion-panel');
      const marker = element('span', 'completion-marker');
      marker.setAttribute('aria-hidden', 'true');
      marker.textContent = '✓';
      const heading = element('h1');
      heading.textContent = 'Batch complete';
      const progress = element('p');
      progress.textContent = batch
        ? `${String(batch.reviewedCount)} / ${String(batch.totalCount)} reviewed`
        : 'All images reviewed';
      panel.append(marker, heading, progress);
      main.append(panel);
      return main;
    }

    const main = element('main', 'review-main');
    if (this.#state === 'loading_image' && this.#queue.length === 0) {
      main.append(this.#buildImageSkeleton());
      if (this.#errorMessage) {
        const retry = button('Retry queue', 'secondary-button retry-queue');
        retry.addEventListener('click', () => {
          if (this.#batchId) void this.#loadQueue(this.#batchId);
        });
        main.append(this.#buildLiveStatus(this.#errorMessage, true), retry);
      }
      return main;
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
    const current = this.#queue[0];
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
      retry.addEventListener('click', () => {
        this.#prepareCurrentImage();
        this.#render();
      });
      stage.append(marker, heading, copy, retry);
      return stage;
    }

    const image = element('img', 'review-image');
    image.alt = 'Image under review';
    image.loading = 'eager';
    image.decoding = 'async';
    image.fetchPriority = 'high';
    image.referrerPolicy = 'no-referrer';
    image.src = source;
    image.addEventListener('load', () => this.#prefetchNext());
    image.addEventListener('error', () => {
      if (!this.#imageAttempt) return;
      const next = advanceImageAttempt(this.#imageAttempt);
      if (next) {
        this.#imageAttempt = next;
        const nextSource = currentImageSource(next);
        if (nextSource) image.src = nextSource;
      } else {
        this.#state = 'image_error';
        this.#prefetch.invalidate();
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
    stage.append(image, controls);
    return stage;
  }

  #prefetchNext(): void {
    const next = this.#queue[1];
    if (!next || this.#state === 'image_error' || !this.#session) return;
    const attempt = createImageAttempt(next.displayUrl, next.fallbackImageUrl);
    const source = currentImageSource(attempt);
    if (source) this.#prefetch.start(source, this.#navigator.connection);
  }

  #buildClassifier(): HTMLElement {
    const disabled = this.#state === 'saving';
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
      if (definition.code === 'source_keyword' && !this.#queue[0]?.flickrKeyword) continue;
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
    textarea.value = this.#comment;
    textarea.addEventListener('input', () => {
      const characters = Array.from(textarea.value);
      if (characters.length > MAX_COMMENT_LENGTH) {
        textarea.value = characters.slice(0, MAX_COMMENT_LENGTH).join('');
      }
      this.#comment = textarea.value;
      const remaining = MAX_COMMENT_LENGTH - Array.from(this.#comment).length;
      const counter = this.#root.querySelector<HTMLElement>('.comment-count');
      if (counter) {
        counter.textContent = remaining <= 100 ? `${String(remaining)} remaining` : '';
      }
    });
    const counter = element('span', 'comment-count');
    const initialRemaining = MAX_COMMENT_LENGTH - Array.from(this.#comment).length;
    counter.textContent = initialRemaining <= 100 ? `${String(initialRemaining)} remaining` : '';

    const send = element('button', 'send-button');
    send.type = 'button';
    send.textContent = this.#state === 'save_error' ? 'Retry save' : 'Send';
    send.setAttribute('aria-label', 'Save this classification and load the next image');
    send.disabled =
      disabled || !this.#selectedLabel || !this.#batchId || !this.#queue[0] || !this.#session;
    send.addEventListener('click', () => void this.#submit());

    const action = element('div', 'submission-action');
    action.append(
      this.#buildLiveStatus(
        this.#errorMessage ||
          (this.#state === 'saving'
            ? 'Saving classification…'
            : 'Select one label, then send when ready.'),
        this.#state === 'save_error',
      ),
      send,
    );
    form.append(commentHeader, textarea, counter, action);
    section.append(headingRow, group, form);
    return section;
  }

  #buildLabelGroup(
    groupCode: ReviewLabelGroup,
    headingText: string,
    disabled: boolean,
  ): HTMLElement {
    const section = element('section', 'label-group');
    if (groupCode === 'source_keyword') section.classList.add('label-group--source-keyword');
    const heading = element('h3');
    heading.textContent = headingText;
    const grid = element('div', 'label-grid');
    for (const label of REVIEW_LABELS.filter((candidate) => candidate.group === groupCode)) {
      const wrapper = element('label', 'label-option');
      const input = element('input');
      input.type = 'radio';
      input.name = 'review-label';
      input.value = label.code;
      input.checked = this.#selectedLabel === label.code;
      input.disabled = disabled;
      input.addEventListener('change', () => {
        if (input.checked) {
          this.#selectedLabel = label.code;
          this.#render();
        }
      });
      const card = element('span', 'label-card');
      const check = element('span', 'label-check');
      check.setAttribute('aria-hidden', 'true');
      check.textContent = '✓';
      const text = element('span', 'label-text');
      text.textContent =
        label.code === 'flickr_keyword_match'
          ? `Matches: ${this.#queue[0]?.flickrKeyword ?? ''}`
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
