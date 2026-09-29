import { REVIEW_LABEL_GROUPS, REVIEW_LABELS, type ReviewLabelCode } from '../domain/reviewLabels';
import type { ReviewDraft } from '../domain/reviewDraft';
import { MAX_COMMENT_LENGTH, type ReviewItem } from '../domain/reviewQueue';
import { countCodePoints, limitCodePoints } from '../domain/text';
import type { ImageMode } from '../image/imageLoader';
import { imagePanBounds } from '../image/imagePan';

type ReviewViewActions = {
  selectLabel: (label: ReviewLabelCode) => void;
  editComment: (comment: string) => void;
  submit: () => void;
  discardDraft: () => void;
  navigate: (direction: 'previous' | 'next') => void;
  retryImage: () => void;
  changeImageMode: () => void;
  resolveConflict: (useSaved: boolean) => void;
  imageError: (sources: readonly string[]) => void;
  imageLoaded: (sources: readonly string[], longestEdge: number) => void;
};

export type ReviewViewState = {
  item: ReviewItem | null;
  draft: ReviewDraft;
  draftLimitReached: boolean;
  comparison: ReviewItem | null;
  sources: readonly string[] | null;
  source: string | null;
  imageMode: ImageMode;
  originalAvailable: boolean;
  previewTooLarge: boolean;
  canEdit: boolean;
  canNavigate: boolean;
  canDiscardDraft: boolean;
  canRetryImage: boolean;
  saving: boolean;
  canSubmit: boolean;
  errorMessage: string;
  isError: boolean;
  complete: boolean;
};

function required<T extends HTMLElement>(root: Element, selector: string, kind: new () => T): T {
  const node = root.querySelector(selector);
  if (!(node instanceof kind)) throw new Error(`Missing review control: ${selector}`);
  return node;
}

/** Static markup only. Task values enter the DOM exclusively as text or validated URLs. */
export class ReviewView {
  readonly element = document.createElement('main');
  readonly #stage: HTMLElement;
  readonly #zoomControls: HTMLElement;
  readonly #zoomOut: HTMLButtonElement;
  readonly #zoomIn: HTMLButtonElement;
  readonly #zoomReset: HTMLButtonElement;
  readonly #navigation: HTMLElement;
  readonly #previous: HTMLButtonElement;
  readonly #next: HTMLButtonElement;
  readonly #position: HTMLElement;
  readonly #loading: HTMLElement;
  readonly #queueError: HTMLElement;
  readonly #unavailable: HTMLElement;
  readonly #unavailableHeading: HTMLElement;
  readonly #unavailableCopy: HTMLElement;
  readonly #retry: HTMLButtonElement;
  readonly #sourceControls: HTMLElement;
  readonly #sourceStatus: HTMLElement;
  readonly #sourceButton: HTMLButtonElement;
  readonly #completion: HTMLElement;
  readonly #classifier: HTMLElement;
  readonly #groups: HTMLElement;
  readonly #primaryActions: HTMLElement;
  readonly #targetGroup: HTMLElement;
  readonly #targetText: HTMLElement;
  readonly #labels = new Map<ReviewLabelCode, HTMLInputElement>();
  readonly #comment: HTMLTextAreaElement;
  readonly #counter: HTMLElement;
  readonly #send: HTMLButtonElement;
  readonly #status: HTMLElement;
  readonly #pending: HTMLElement;
  readonly #draftLimit: HTMLElement;
  readonly #draftLimitMessage: HTMLElement;
  readonly #discardDraft: HTMLButtonElement;
  readonly #comparison: HTMLElement;
  readonly #comparisonHeading: HTMLElement;
  readonly #comparisonLabel: HTMLElement;
  readonly #comparisonComment: HTMLElement;
  readonly #actions: ReviewViewActions;
  readonly #resizeObserver: ResizeObserver;
  #image: HTMLImageElement | null = null;
  #sources: readonly string[] | null = null;
  #zoom = 1;
  #pan = { x: 0, y: 0 };
  #panBounds = { x: 0, y: 0 };
  #drag: { pointerId: number; x: number; y: number } | null = null;
  #countedComment: string | null = null;
  #commentLength = 0;

  constructor(actions: ReviewViewActions) {
    this.#actions = actions;
    this.element.className = 'review-main';
    this.element.innerHTML = `
      <p class="completion-status" role="status" hidden>All reviewed—answers can still be updated.</p>
      <section class="image-stage" aria-label="Image under review">
        <span class="stage-message" hidden>Loading image…</span>
        <div class="image-unavailable" hidden>
          <span class="image-error-marker" aria-hidden="true">!</span>
          <h2></h2><p></p>
        </div>
        <button type="button" class="secondary-button retry-image" hidden>Retry image</button>
        <div class="image-zoom-controls" role="group" aria-label="Image zoom controls">
          <button type="button" class="image-zoom-button" aria-label="Zoom out" title="Zoom out">−</button>
          <button type="button" class="image-zoom-button image-zoom-level" title="Reset image zoom">100%</button>
          <button type="button" class="image-zoom-button" aria-label="Zoom in" title="Zoom in">+</button>
        </div>
        <nav class="image-navigation" aria-label="Review image navigation">
          <button type="button" class="image-navigation-button" aria-label="Previous image">Previous</button>
          <span class="image-position"></span>
          <button type="button" class="image-navigation-button" aria-label="Next image">Next</button>
        </nav>
      </section>
      <p class="status-text status-text--error queue-error" role="alert" hidden></p>
      <section class="classification-panel" tabindex="-1" aria-labelledby="classification-heading">
        <div role="radiogroup" aria-labelledby="classification-heading">
          <div class="classification-primary-actions">
            <button type="button" class="send-button">Send</button>
          </div>
          <div class="image-source-controls" role="group" aria-label="Image source">
            <p class="image-source-status" role="status"></p>
            <button type="button" class="secondary-button image-source-button">Inspect source image</button>
          </div>
          <div class="classification-heading-row">
            <h2 id="classification-heading">How should this image be classified?</h2>
            <p>Choose the best matching option.</p>
          </div>
          <div class="label-groups"></div>
        </div>
        <div class="submission-panel">
          <div class="comment-heading"><label for="review-comment">Comment</label><span>optional</span></div>
          <textarea id="review-comment" rows="2"></textarea><span class="comment-count"></span>
          <div class="submission-action">
            <p class="status-text" aria-live="polite" role="status"></p>
          </div>
          <p class="status-text pending-notice" role="status" hidden>Retry sends the original request. Any newer edits will remain unsaved until you send them separately.</p>
          <section class="draft-limit" aria-label="Unsaved draft limit" hidden>
            <p class="status-text status-text--error" role="alert"></p>
            <button type="button" class="secondary-button discard-draft">Discard local edits</button>
          </section>
          <section class="conflict-comparison" aria-label="Saved answer comparison" hidden>
            <h3></h3><p class="saved-label"></p><p class="saved-comment"></p>
            <button type="button" class="secondary-button use-saved">Use saved answer</button>
            <button type="button" class="secondary-button reapply">Reapply my changes</button>
          </section>
        </div>
      </section>`;
    const find = <T extends HTMLElement>(selector: string, kind: new () => T): T =>
      required(this.element, selector, kind);
    this.#stage = find('.image-stage', HTMLElement);
    this.#zoomControls = find('.image-zoom-controls', HTMLElement);
    this.#zoomOut = find('[aria-label="Zoom out"]', HTMLButtonElement);
    this.#zoomIn = find('[aria-label="Zoom in"]', HTMLButtonElement);
    this.#zoomReset = find('.image-zoom-level', HTMLButtonElement);
    this.#navigation = find('.image-navigation', HTMLElement);
    this.#previous = find('[aria-label="Previous image"]', HTMLButtonElement);
    this.#next = find('[aria-label="Next image"]', HTMLButtonElement);
    this.#position = find('.image-position', HTMLElement);
    this.#loading = find('.stage-message', HTMLElement);
    this.#queueError = find('.queue-error', HTMLElement);
    this.#unavailable = find('.image-unavailable', HTMLElement);
    this.#unavailableHeading = find('.image-unavailable h2', HTMLElement);
    this.#unavailableCopy = find('.image-unavailable p', HTMLElement);
    this.#retry = find('.retry-image', HTMLButtonElement);
    this.#sourceControls = find('.image-source-controls', HTMLElement);
    this.#sourceStatus = find('.image-source-status', HTMLElement);
    this.#sourceButton = find('.image-source-button', HTMLButtonElement);
    this.#completion = find('.completion-status', HTMLElement);
    this.#classifier = find('.classification-panel', HTMLElement);
    this.#groups = find('.label-groups', HTMLElement);
    this.#primaryActions = find('.classification-primary-actions', HTMLElement);
    this.#comment = find('#review-comment', HTMLTextAreaElement);
    this.#counter = find('.comment-count', HTMLElement);
    this.#send = find('.send-button', HTMLButtonElement);
    this.#status = find('.submission-action .status-text', HTMLElement);
    this.#pending = find('.pending-notice', HTMLElement);
    this.#draftLimit = find('.draft-limit', HTMLElement);
    this.#draftLimitMessage = find('.draft-limit p', HTMLElement);
    this.#discardDraft = find('.discard-draft', HTMLButtonElement);
    this.#comparison = find('.conflict-comparison', HTMLElement);
    this.#comparisonHeading = find('.conflict-comparison h3', HTMLElement);
    this.#comparisonLabel = find('.saved-label', HTMLElement);
    this.#comparisonComment = find('.saved-comment', HTMLElement);
    for (const definition of REVIEW_LABEL_GROUPS) {
      const group = document.createElement('section');
      group.className = 'label-group';
      group.dataset.group = definition.code;
      const heading = document.createElement('h3');
      heading.textContent = definition.heading;
      const grid = document.createElement('div');
      grid.className = 'label-grid';
      for (const label of REVIEW_LABELS.filter(
        (candidate) => candidate.group === definition.code,
      )) {
        const wrapper = document.createElement('label');
        wrapper.className = 'label-option';
        wrapper.innerHTML = `<input type="radio" name="review-label"><span class="label-card"><span class="label-check" aria-hidden="true">✓</span><span class="label-text"></span><kbd aria-hidden="true"></kbd></span>`;
        const input = required(wrapper, 'input', HTMLInputElement);
        input.value = label.code;
        input.addEventListener('change', () => {
          if (input.checked && !input.disabled) actions.selectLabel(label.code);
        });
        required(wrapper, '.label-text', HTMLElement).textContent = label.displayLabel;
        required(wrapper, 'kbd', HTMLElement).textContent = label.shortcut;
        this.#labels.set(label.code, input);
        grid.append(wrapper);
      }
      group.append(heading, grid);
      this.#groups.append(group);
    }
    this.#targetGroup = find('[data-group="target_taxon"]', HTMLElement);
    this.#targetGroup.classList.add('label-group--target-taxon');
    this.#targetText = required(this.#targetGroup, '.label-text', HTMLElement);
    this.#primaryActions.prepend(this.#targetGroup);
    this.#previous.addEventListener('click', () => actions.navigate('previous'));
    this.#next.addEventListener('click', () => actions.navigate('next'));
    this.#retry.addEventListener('click', actions.retryImage);
    this.#sourceButton.addEventListener('click', actions.changeImageMode);
    this.#send.addEventListener('click', actions.submit);
    this.#discardDraft.addEventListener('click', actions.discardDraft);
    this.#comment.addEventListener('input', () => {
      if (this.#comment.disabled) return;
      const comment = limitCodePoints(this.#comment.value, MAX_COMMENT_LENGTH);
      this.#countedComment = comment.value;
      this.#commentLength = comment.length;
      actions.editComment(comment.value);
    });
    find('.use-saved', HTMLButtonElement).addEventListener('click', () =>
      actions.resolveConflict(true),
    );
    find('.reapply', HTMLButtonElement).addEventListener('click', () =>
      actions.resolveConflict(false),
    );
    this.#zoomOut.addEventListener('click', () => this.#setZoom(this.#zoom - 0.25));
    this.#zoomIn.addEventListener('click', () => this.#setZoom(this.#zoom + 0.25));
    this.#zoomReset.addEventListener('click', () => this.#setZoom(1));
    this.#stage.addEventListener('pointerdown', (event) => {
      if (event.target !== this.#image || !event.isPrimary || event.button !== 0 || this.#drag)
        return;
      this.#refreshPanBounds();
      if (this.#panBounds.x === 0 && this.#panBounds.y === 0) return;
      this.#stage.setPointerCapture(event.pointerId);
      this.#drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
      this.#stage.classList.add('image-stage--dragging');
      event.preventDefault();
    });
    this.#stage.addEventListener('pointermove', (event) => this.#moveImage(event));
    this.#stage.addEventListener('pointerup', (event) => {
      if (event.pointerId !== this.#drag?.pointerId) return;
      this.#moveImage(event);
      this.#endDrag();
    });
    for (const type of ['pointercancel', 'lostpointercapture'] as const) {
      this.#stage.addEventListener(type, (event) => {
        if (event.pointerId === this.#drag?.pointerId) this.#endDrag();
      });
    }
    this.#resizeObserver = new ResizeObserver(() => this.#refreshPanBounds());
    this.#resizeObserver.observe(this.#stage);
  }

  update(state: ReviewViewState): void {
    const { item, draft, comparison, source, sources, canEdit } = state;
    this.#completion.hidden = !state.complete;
    this.#classifier.hidden = !item;
    this.#navigation.hidden = !item;
    this.#previous.disabled = this.#next.disabled = !state.canNavigate;
    this.#position.textContent = item
      ? `${String(item.position)} / ${String(item.totalCount)}`
      : '';
    this.#loading.hidden = !!item;
    this.#queueError.hidden = !!item || !state.errorMessage;
    this.#queueError.textContent = item ? '' : state.errorMessage;
    this.#unavailable.hidden = !item || !!source;
    this.#unavailableHeading.textContent =
      state.imageMode === 'preview' ? 'Preview unavailable' : 'Source image unavailable';
    this.#unavailableCopy.textContent =
      state.imageMode === 'preview'
        ? 'A display-sized image is not available for automatic review.'
        : 'The supplied source image could not be loaded.';
    this.#retry.hidden = item ? !!source : !state.errorMessage;
    this.#retry.disabled = !state.canRetryImage;
    this.#stage.classList.toggle('image-stage--loading', !item);
    this.#stage.classList.toggle('image-stage--error', !!item && !source);
    this.#stage.setAttribute('aria-label', item ? 'Image under review' : 'Loading image');
    this.#zoomControls.hidden = !source;
    this.#updateImage(sources, source);
    this.#sourceControls.hidden = !item;
    this.#sourceButton.hidden = !state.originalAvailable;
    this.#sourceButton.disabled = !canEdit;
    this.#sourceButton.textContent =
      state.imageMode === 'original' ? 'Return to preview' : 'Inspect source image';
    this.#sourceStatus.textContent =
      state.imageMode === 'original'
        ? 'Source image: resolution is uncontrolled. Return to preview to release it.'
        : state.previewTooLarge
          ? 'Preview exceeded 1,600 pixels and was released. A smaller upstream rendition is needed.'
          : source
            ? 'Upstream preview. Source-image inspection is optional.'
            : 'No preview is available. Source-image inspection may use more memory.';
    if (item?.targetScientificName) {
      if (!this.#targetGroup.isConnected) this.#primaryActions.prepend(this.#targetGroup);
      this.#targetText.textContent = item.targetScientificName;
    } else {
      this.#targetGroup.remove();
      this.#targetText.textContent = '';
    }
    for (const [label, input] of this.#labels) {
      input.checked = draft.label === label;
      input.disabled = !canEdit;
    }
    this.#comment.disabled = !canEdit;
    // Assigning an unchanged textarea value can disturb selection/IME composition.
    if (this.#comment.value !== draft.comment) this.#comment.value = draft.comment;
    // Typing already counted while truncating. Restored/server drafts are counted
    // once when their value changes, never again for label/status/image updates.
    if (this.#countedComment !== draft.comment) {
      this.#countedComment = draft.comment;
      this.#commentLength = countCodePoints(draft.comment);
    }
    const remaining = MAX_COMMENT_LENGTH - this.#commentLength;
    this.#counter.textContent = remaining <= 100 ? `${String(remaining)} remaining` : '';
    this.#send.textContent = draft.conflicted
      ? 'Compare saved answer'
      : draft.pendingSubmission
        ? 'Retry save'
        : 'Send';
    this.#send.setAttribute(
      'aria-label',
      draft.conflicted
        ? 'Compare saved answer'
        : draft.pendingSubmission
          ? 'Retry original save'
          : 'Save this classification and advance',
    );
    this.#send.disabled = !state.canSubmit;
    this.#status.textContent =
      state.errorMessage ||
      (state.saving ? 'Saving classification…' : 'Select one label, then send when ready.');
    this.#status.classList.toggle('status-text--error', state.isError);
    this.#status.setAttribute('role', state.isError ? 'alert' : 'status');
    this.#status.setAttribute('aria-live', state.isError ? 'assertive' : 'polite');
    this.#pending.hidden = !draft.pendingSubmission || state.saving;
    this.#draftLimit.hidden = !state.draftLimitReached;
    this.#discardDraft.disabled = !state.canDiscardDraft;
    this.#draftLimitMessage.textContent = state.draftLimitReached
      ? 'Unsaved draft budget reached (256 entries or 1 MiB, including an active-editor reserve). ' +
        (draft.pendingSubmission
          ? 'Retry the original save to resolve its outcome before navigating; it may already have committed.'
          : 'Save this review or explicitly discard its local edits before navigating. Other drafts are unchanged.')
      : '';
    if (comparison) {
      if (!this.#comparison.isConnected) this.#pending.after(this.#comparison);
      this.#comparison.hidden = false;
    } else {
      this.#comparison.remove();
    }
    this.#comparisonHeading.textContent = comparison
      ? `Your saved answer (version ${String(comparison.currentVersion)})`
      : '';
    this.#comparisonLabel.textContent =
      comparison?.currentLabel === 'target_scientific_name'
        ? comparison.targetScientificName
        : comparison
          ? (REVIEW_LABELS.find((label) => label.code === comparison.currentLabel)?.displayLabel ??
            'No classification')
          : '';
    this.#comparisonComment.textContent = comparison
      ? (comparison.currentComment ?? 'No comment')
      : '';
  }

  #updateImage(sources: readonly string[] | null, source: string | null): void {
    if (this.#sources !== sources || !source) {
      this.#releaseImage();
      this.#sources = sources;
    }
    if (!source || !sources) return;
    if (!this.#image) {
      const image = document.createElement('img');
      image.className = 'review-image';
      image.alt = 'Image under review';
      image.loading = 'eager';
      image.decoding = 'async';
      image.fetchPriority = 'high';
      image.referrerPolicy = 'no-referrer';
      image.draggable = false;
      // A new node only for a new owned attempt, never for label/comment/status changes.
      image.onerror = () => {
        if (this.#image === image && this.element.contains(image))
          this.#actions.imageError(sources);
      };
      image.onload = () => {
        if (this.#image === image && this.element.contains(image)) {
          this.#refreshPanBounds();
          this.#actions.imageLoaded(sources, Math.max(image.naturalWidth, image.naturalHeight));
        }
      };
      this.#image = image;
      this.#stage.prepend(image);
    }
    if (this.#image.getAttribute('src') !== source) {
      this.#resetImagePosition();
      this.#image.src = source;
    }
    this.#setZoom(this.#zoom);
  }

  #setZoom(value: number): void {
    const zoom = Math.max(1, Math.min(4, value));
    if (zoom !== this.#zoom) {
      this.#endDrag();
      // Keep the point at the frame center in view as magnification changes.
      this.#pan.x *= zoom / this.#zoom;
      this.#pan.y *= zoom / this.#zoom;
      this.#zoom = zoom;
      this.#refreshPanBounds();
    }
    this.#image?.style.setProperty('--image-zoom', String(this.#zoom));
    if (this.#image) this.#image.dataset.zoom = String(this.#zoom);
    this.#zoomOut.disabled = this.#zoom === 1;
    this.#zoomIn.disabled = this.#zoom === 4;
    this.#zoomReset.disabled = this.#zoom === 1;
    const percentage = String(Math.round(this.#zoom * 100));
    this.#zoomReset.textContent = `${percentage}%`;
    this.#zoomReset.setAttribute('aria-label', `Reset image zoom from ${percentage}%`);
  }

  #refreshPanBounds(): void {
    this.#panBounds = imagePanBounds(
      this.#image?.naturalWidth ?? 0,
      this.#image?.naturalHeight ?? 0,
      this.#stage.clientWidth,
      this.#stage.clientHeight,
      this.#zoom,
    );
    const pannable = this.#panBounds.x > 0 || this.#panBounds.y > 0;
    this.#stage.classList.toggle('image-stage--pannable', pannable);
    if (!pannable) this.#endDrag();
    this.#applyPan();
  }

  #moveImage(event: PointerEvent): void {
    if (!this.#drag || event.pointerId !== this.#drag.pointerId) return;
    this.#pan.x += event.clientX - this.#drag.x;
    this.#pan.y += event.clientY - this.#drag.y;
    this.#drag.x = event.clientX;
    this.#drag.y = event.clientY;
    this.#applyPan();
  }

  #applyPan(): void {
    this.#pan.x = Math.max(-this.#panBounds.x, Math.min(this.#panBounds.x, this.#pan.x));
    this.#pan.y = Math.max(-this.#panBounds.y, Math.min(this.#panBounds.y, this.#pan.y));
    this.#image?.style.setProperty('--image-pan-x', `${String(this.#pan.x)}px`);
    this.#image?.style.setProperty('--image-pan-y', `${String(this.#pan.y)}px`);
  }

  #endDrag(): void {
    const pointerId = this.#drag?.pointerId;
    this.#drag = null;
    this.#stage.classList.remove('image-stage--dragging');
    if (pointerId !== undefined && this.#stage.hasPointerCapture(pointerId))
      this.#stage.releasePointerCapture(pointerId);
  }

  #resetImagePosition(): void {
    this.#endDrag();
    this.#zoom = 1;
    this.#pan = { x: 0, y: 0 };
    this.#panBounds = { x: 0, y: 0 };
    this.#stage.classList.remove('image-stage--pannable');
    this.#applyPan();
  }

  #releaseImage(): void {
    this.#resetImagePosition();
    if (!this.#image) return;
    this.#image.onerror = null;
    this.#image.onload = null;
    this.#image.removeAttribute('src');
    this.#image.remove();
    this.#image = null;
  }

  dispose(): void {
    this.#resizeObserver.disconnect();
    this.#releaseImage();
    this.#sources = null;
    this.element.remove();
  }
}
