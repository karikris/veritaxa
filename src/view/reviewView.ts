import { REVIEW_LABELS } from '../domain/reviewLabels';
import type { ReviewDraft } from '../domain/reviewDraft';
import type { ReviewItem } from '../domain/reviewQueue';
import type { ImageMode } from '../image/imageLoader';
import { imagePanBounds } from '../image/imagePan';

type ReviewViewActions = {
  answer: (label: 'target_scientific_name' | 'target_not_present' | 'no_butterfly') => void;
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
  canAnswer: boolean;
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
  readonly #reviewStatus: HTMLElement;
  readonly #loading: HTMLElement;
  readonly #queueError: HTMLElement;
  readonly #unavailable: HTMLElement;
  readonly #unavailableHeading: HTMLElement;
  readonly #unavailableCopy: HTMLElement;
  readonly #retry: HTMLButtonElement;
  readonly #sourceButton: HTMLButtonElement;
  readonly #completion: HTMLElement;
  readonly #classifier: HTMLElement;
  readonly #heading: HTMLElement;
  readonly #yes: HTMLButtonElement;
  readonly #no: HTMLButtonElement;
  readonly #noButterfly: HTMLButtonElement;
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

  constructor(actions: ReviewViewActions) {
    this.#actions = actions;
    this.element.className = 'review-main';
    this.element.innerHTML = `
      <p class="completion-status" role="status" hidden>All reviewed—answers can still be updated.</p>
      <p class="image-review-status" role="status" hidden></p>
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
      <p class="image-gesture-help">Scroll over the picture to zoom at the pointer. Drag when zoomed to move around. Double-click to zoom; use the percentage button to reset.</p>
      <p class="status-text status-text--error queue-error" role="alert" hidden></p>
      <section class="classification-panel" tabindex="-1" aria-label="Image classification">
        <div class="classification-heading-row">
          <h2 id="classification-heading"></h2>
          <p>Choose an answer to save and show the next image.</p>
        </div>
        <div class="review-choices" role="group" aria-labelledby="classification-heading">
          <button type="button" class="answer-button answer-button--yes" data-label="target_scientific_name" aria-label="Yes">Yes <kbd aria-hidden="true">Y</kbd></button>
          <button type="button" class="answer-button answer-button--no" data-label="target_not_present" aria-label="No">No <kbd aria-hidden="true">N</kbd></button>
          <button type="button" class="answer-button answer-button--no-butterfly" data-label="no_butterfly" aria-label="No butterfly">No butterfly <kbd aria-hidden="true">0</kbd></button>
        </div>
        <div class="classification-primary-actions">
          <button type="button" class="secondary-button image-source-button">Inspect source image</button>
          <button type="button" class="secondary-button retry-save" hidden>Retry save</button>
        </div>
        <div class="submission-panel">
          <div class="submission-action">
            <p class="status-text" aria-live="polite" role="status"></p>
          </div>
          <p class="status-text pending-notice" role="status" hidden>Retry saves your original answer. The image advances after the save is confirmed.</p>
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
    this.#reviewStatus = find('.image-review-status', HTMLElement);
    this.#loading = find('.stage-message', HTMLElement);
    this.#queueError = find('.queue-error', HTMLElement);
    this.#unavailable = find('.image-unavailable', HTMLElement);
    this.#unavailableHeading = find('.image-unavailable h2', HTMLElement);
    this.#unavailableCopy = find('.image-unavailable p', HTMLElement);
    this.#retry = find('.retry-image', HTMLButtonElement);
    this.#sourceButton = find('.image-source-button', HTMLButtonElement);
    this.#completion = find('.completion-status', HTMLElement);
    this.#classifier = find('.classification-panel', HTMLElement);
    this.#heading = find('#classification-heading', HTMLElement);
    this.#yes = find('[aria-label="Yes"]', HTMLButtonElement);
    this.#no = find('[aria-label="No"]', HTMLButtonElement);
    this.#noButterfly = find('[aria-label="No butterfly"]', HTMLButtonElement);
    this.#send = find('.retry-save', HTMLButtonElement);
    this.#status = find('.submission-action .status-text', HTMLElement);
    this.#pending = find('.pending-notice', HTMLElement);
    this.#draftLimit = find('.draft-limit', HTMLElement);
    this.#draftLimitMessage = find('.draft-limit p', HTMLElement);
    this.#discardDraft = find('.discard-draft', HTMLButtonElement);
    this.#comparison = find('.conflict-comparison', HTMLElement);
    this.#comparisonHeading = find('.conflict-comparison h3', HTMLElement);
    this.#comparisonLabel = find('.saved-label', HTMLElement);
    this.#comparisonComment = find('.saved-comment', HTMLElement);
    this.#yes.addEventListener('click', () => actions.answer('target_scientific_name'));
    this.#no.addEventListener('click', () => actions.answer('target_not_present'));
    this.#noButterfly.addEventListener('click', () => actions.answer('no_butterfly'));
    this.#previous.addEventListener('click', () => actions.navigate('previous'));
    this.#next.addEventListener('click', () => actions.navigate('next'));
    this.#retry.addEventListener('click', actions.retryImage);
    this.#sourceButton.addEventListener('click', actions.changeImageMode);
    this.#send.addEventListener('click', actions.submit);
    this.#discardDraft.addEventListener('click', actions.discardDraft);
    find('.use-saved', HTMLButtonElement).addEventListener('click', () =>
      actions.resolveConflict(true),
    );
    find('.reapply', HTMLButtonElement).addEventListener('click', () =>
      actions.resolveConflict(false),
    );
    this.#zoomOut.addEventListener('click', () => this.#setZoom(this.#zoom - 0.25));
    this.#zoomIn.addEventListener('click', () => this.#setZoom(this.#zoom + 0.25));
    this.#zoomReset.addEventListener('click', () => this.#setZoom(1));
    this.#stage.addEventListener(
      'wheel',
      (event) => {
        if (!this.#isImageTarget(event.target) || !this.#image?.naturalWidth) return;
        const delta = event.deltaY || event.deltaX;
        if (!delta) return;
        event.preventDefault();
        const unit =
          event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? this.#stage.clientHeight : 1;
        const pixels = Math.max(-240, Math.min(240, delta * unit));
        this.#zoomAt(this.#zoom * Math.exp(-pixels * 0.002), event);
      },
      { passive: false },
    );
    this.#stage.addEventListener('dblclick', (event) => {
      if (!this.#isImageTarget(event.target) || !this.#image?.naturalWidth) return;
      event.preventDefault();
      this.#zoomAt(this.#zoom === 4 ? 1 : this.#zoom * 2, event);
    });
    this.#stage.addEventListener('pointerdown', (event) => {
      if (
        !this.#isImageTarget(event.target) ||
        !event.isPrimary ||
        event.button !== 0 ||
        this.#drag
      )
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
    this.#reviewStatus.hidden = !item;
    this.#reviewStatus.textContent = item?.currentVersion
      ? '✓ Reviewed by you in this dataset'
      : item?.reviewedByAnyone
        ? '✓ Reviewed by another reviewer in this dataset · Your review is still open'
        : 'Needs review in this dataset';
    this.#reviewStatus.classList.toggle(
      'image-review-status--saved',
      !!item && (item.currentVersion > 0 || !!item.reviewedByAnyone),
    );
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
        ? state.previewTooLarge
          ? 'Preview exceeded 1,600 pixels and was released. A smaller upstream rendition is needed.'
          : 'No preview is available.'
        : 'The supplied source image could not be loaded.';
    this.#retry.hidden = item ? !!source : !state.errorMessage;
    this.#retry.disabled = !state.canRetryImage;
    this.#stage.classList.toggle('image-stage--loading', !item);
    this.#stage.classList.toggle('image-stage--error', !!item && !source);
    this.#stage.setAttribute('aria-label', item ? 'Image under review' : 'Loading image');
    this.#zoomControls.hidden = !source;
    this.#updateImage(sources, source);
    this.#sourceButton.hidden = !state.originalAvailable;
    this.#sourceButton.disabled = !canEdit;
    this.#sourceButton.textContent =
      state.imageMode === 'original' ? 'Return to preview' : 'Inspect source image';
    this.#heading.textContent = item?.targetScientificName
      ? `Is this ${item.targetScientificName}?`
      : 'No target species configured';
    this.#yes.disabled = this.#no.disabled = this.#noButterfly.disabled = !state.canAnswer;
    this.#classifier.setAttribute('aria-busy', String(state.saving));
    this.#send.hidden = !draft.pendingSubmission && !draft.conflicted;
    this.#send.textContent = draft.conflicted
      ? 'Compare saved answer'
      : draft.pendingSubmission
        ? 'Retry save'
        : 'Retry save';
    this.#send.setAttribute(
      'aria-label',
      draft.conflicted
        ? 'Compare saved answer'
        : draft.pendingSubmission
          ? 'Retry save'
          : 'Retry save',
    );
    this.#send.disabled = !state.canSubmit;
    this.#status.textContent =
      state.errorMessage ||
      (state.saving
        ? 'Saving answer…'
        : !item?.targetScientificName
          ? 'This batch needs a target species before it can be reviewed.'
          : !source
            ? 'Retry the image or use Next to skip it.'
            : item.currentLabel === 'target_scientific_name'
              ? 'Your saved answer: Yes. Choose again to update it.'
              : item.currentLabel === 'target_not_present'
                ? 'Your saved answer: No. Choose again to update it.'
                : item.currentLabel === 'no_butterfly'
                  ? 'Your saved answer: No butterfly. Choose again to update it.'
                  : '');
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

  #isImageTarget(target: EventTarget | null): boolean {
    return !!this.#image && (target === this.#image || target === this.#stage);
  }

  #zoomAt(value: number, point: { clientX: number; clientY: number }): void {
    const frame = this.#stage.getBoundingClientRect();
    this.#setZoom(value, {
      x: point.clientX - frame.left - this.#stage.clientLeft - this.#stage.clientWidth / 2,
      y: point.clientY - frame.top - this.#stage.clientTop - this.#stage.clientHeight / 2,
    });
  }

  #setZoom(value: number, focal = { x: 0, y: 0 }): void {
    const zoom = Math.max(1, Math.min(4, value));
    if (zoom !== this.#zoom) {
      this.#endDrag();
      // Keep the image point under the pointer fixed as magnification changes.
      const ratio = zoom / this.#zoom;
      this.#pan.x = focal.x + (this.#pan.x - focal.x) * ratio;
      this.#pan.y = focal.y + (this.#pan.y - focal.y) * ratio;
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
