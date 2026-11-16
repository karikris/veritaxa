/* global window, ResizeObserver, setTimeout, clearTimeout */

const LANDING_ZOOM = 2;

function createMap(component, surface) {
  const L = window.L;
  const root = surface.parentElement;
  const card = root.querySelector('.photo-card');
  const image = root.querySelector('.photo-image');
  const loading = root.querySelector('.photo-loading');
  const date = root.querySelector('.photo-date');
  const pager = root.querySelector('.photo-pager');
  const previous = root.querySelector('.photo-previous');
  const next = root.querySelector('.photo-next');
  const toolbar = component.parentElement.querySelector('.map-toolbar');
  const summary = toolbar.querySelector('.selection-summary');
  const download = toolbar.querySelector('.download-csv');
  const includeVisible = toolbar.querySelector('.include-visible');
  const exportStatus = toolbar.querySelector('.export-status');
  const included = root.querySelector('.photo-included');
  const page = root.querySelector('.photo-page');
  const map = L.map(surface, { worldCopyJump: true, minZoom: LANDING_ZOOM, maxZoom: 18 }).setView(
    [14, 10],
    LANDING_ZOOM,
  );
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>',
  }).addTo(map);
  const layers = L.layerGroup().addTo(map);
  const state = {
    component,
    map,
    layers,
    root,
    card,
    image,
    loading,
    cells: new Map(),
    markers: new Map(),
    counts: new Map(),
    excluded: new Set(),
    selectionVersion: 0,
    exportToken: null,
    cache: new Map(),
    selected: null,
    index: 0,
    pinned: false,
    token: null,
    sequence: 0,
    hideTimer: null,
    loadTimer: null,
  };

  state.includedKeys = () =>
    [...state.cells.values()].flatMap((cell) =>
      cell.photos.filter((photo) => !state.excluded.has(photo.key)).map((photo) => photo.key),
    );
  state.renderSelection = () => {
    let total = 0,
      count = 0;
    for (const cell of state.cells.values()) {
      const selected = cell.photos.filter((photo) => !state.excluded.has(photo.key));
      total += cell.photos.length;
      count += selected.length;
      const marker = state.markers.get(cell.key);
      marker?.setRadius(Math.min(38, 6 * Math.sqrt(Math.max(1, selected.length))));
      marker?.setStyle({
        fillColor: selected[0]?.colour || '#94a3b8',
        fillOpacity: selected.length ? 0.88 : 0.2,
      });
      const label = state.counts.get(cell.key)?.getElement();
      if (label) {
        label.querySelector('span').textContent = String(selected.length);
        label.hidden = selected.length <= 1;
      }
    }
    summary.textContent = `${count.toLocaleString()} of ${total.toLocaleString()} visible observations selected`;
    download.disabled = count === 0 || Boolean(state.exportToken);
    includeVisible.disabled = count === total;
    const photo = state.cells.get(state.selected)?.photos[state.index];
    if (photo) included.checked = !state.excluded.has(photo.key);
  };
  state.saveSelection = () => {
    state.selectionVersion++;
    // A changed selection cancels an export still in flight.
    state.exportToken = null;
    exportStatus.textContent = '';
    state.renderSelection();
    state.component.setStateValue('exclusions', {
      source_revision: state.sourceRevision,
      version: state.selectionVersion,
      keys: [...state.excluded],
    });
  };
  included.addEventListener('change', () => {
    const photo = state.cells.get(state.selected)?.photos[state.index];
    if (!photo) return;
    if (included.checked) state.excluded.delete(photo.key);
    else state.excluded.add(photo.key);
    state.pinned = true;
    state.saveSelection();
  });
  includeVisible.addEventListener('click', () => {
    for (const cell of state.cells.values())
      for (const photo of cell.photos) state.excluded.delete(photo.key);
    state.saveSelection();
  });
  download.addEventListener('click', () => {
    const keys = state.includedKeys();
    if (!keys.length || state.exportToken) return;
    state.exportToken = `export:${Date.now()}:${++state.sequence}`;
    exportStatus.textContent = 'Preparing CSV…';
    state.renderSelection();
    state.component.setTriggerValue('export_request', {
      keys,
      token: state.exportToken,
      view_revision: state.revision,
    });
  });
  state.showExport = (response) => {
    if (!response || response.token !== state.exportToken) return;
    state.exportToken = null;
    if (response.csv && /^[A-Za-z0-9+/=]+$/.test(response.csv)) {
      const bytes = Uint8Array.from(window.atob(response.csv), (char) => char.charCodeAt(0));
      const url = window.URL.createObjectURL(new Blob([bytes], { type: 'text/csv;charset=utf-8' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'selected-observations.csv';
      root.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => window.URL.revokeObjectURL(url), 1000);
      exportStatus.textContent = 'CSV downloaded.';
    } else exportStatus.textContent = response.error || 'Could not prepare CSV. Please try again.';
    state.renderSelection();
  };
  state.positionCard = () => {
    if (!state.selected || card.hidden) return;
    const cell = state.cells.get(state.selected);
    if (!cell) return;
    const point = map.latLngToContainerPoint([cell.latitude, cell.longitude]);
    const width = surface.clientWidth;
    const height = surface.clientHeight;
    const cardWidth = card.offsetWidth || 320;
    const cardHeight = card.offsetHeight || 290;
    let left = point.x + cell.radius + 14;
    if (left + cardWidth > width - 12) left = point.x - cardWidth - cell.radius - 14;
    card.style.left = `${Math.max(12, Math.min(width - cardWidth - 12, left))}px`;
    card.style.top = `${Math.max(12, Math.min(height - cardHeight - 12, point.y - cardHeight / 2))}px`;
  };
  state.close = () => {
    clearTimeout(state.hideTimer);
    clearTimeout(state.loadTimer);
    card.hidden = true;
    state.selected = null;
    state.token = null;
    state.pinned = false;
  };
  state.scheduleClose = () => {
    clearTimeout(state.hideTimer);
    if (!state.pinned) state.hideTimer = setTimeout(state.close, 350);
  };
  state.showResponse = (response) => {
    if (!response || response.token !== state.token) return;
    if (response.image && /^data:image\/webp;base64,[A-Za-z0-9+/=]+$/.test(response.image)) {
      image.src = response.image;
      image.hidden = false;
      loading.hidden = true;
    } else if (response.unavailable) {
      image.hidden = true;
      loading.hidden = false;
      loading.textContent = 'Image unavailable';
    }
  };
  state.requestPhoto = (delay = 160) => {
    clearTimeout(state.loadTimer);
    const cell = state.cells.get(state.selected);
    if (!cell) return;
    const photo = cell.photos[state.index];
    date.textContent = photo.date;
    included.checked = !state.excluded.has(photo.key);
    pager.hidden = cell.count === 1;
    page.textContent = `${state.index + 1} / ${cell.count}`;
    previous.disabled = state.index === 0;
    next.disabled = state.index >= cell.photos.length - 1;
    image.hidden = true;
    image.removeAttribute('src');
    loading.hidden = false;
    loading.textContent = 'Loading image…';
    state.token = `${photo.key}:${++state.sequence}`;
    const token = state.token;
    const cached = state.cache.get(photo.key);
    if (cached) {
      state.showResponse({ ...cached, token });
      return;
    }
    state.loadTimer = setTimeout(() => {
      if (token === state.token)
        state.component.setTriggerValue('photo_request', { key: photo.key, token });
    }, delay);
  };
  state.open = (key, pin = false) => {
    clearTimeout(state.hideTimer);
    if (state.pinned && !pin && state.selected !== key) return;
    const changed = state.selected !== key;
    state.selected = key;
    state.pinned = pin || state.pinned;
    if (changed) state.index = 0;
    card.hidden = false;
    state.positionCard();
    if (changed || !state.token) state.requestPhoto(pin ? 0 : 160);
  };
  card.addEventListener('mouseenter', () => clearTimeout(state.hideTimer));
  card.addEventListener('mouseleave', state.scheduleClose);
  root.querySelector('.photo-close').addEventListener('click', state.close);
  root.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') state.close();
  });
  previous.addEventListener('click', () => {
    if (state.index > 0) {
      state.index--;
      state.pinned = true;
      state.requestPhoto(0);
    }
  });
  next.addEventListener('click', () => {
    const cell = state.cells.get(state.selected);
    if (cell && state.index < cell.photos.length - 1) {
      state.index++;
      state.pinned = true;
      state.requestPhoto(0);
    }
  });
  map.on('move zoom resize', state.positionCard);
  const observer = new ResizeObserver(() => {
    map.invalidateSize({ pan: false });
    state.positionCard();
  });
  observer.observe(surface);
  state.cleanup = () => {
    clearTimeout(state.hideTimer);
    clearTimeout(state.loadTimer);
    observer.disconnect();
    map.remove();
  };
  return state;
}

export default function (component) {
  const { parentElement, data } = component;
  const surface = parentElement.querySelector('.map-surface');
  const state = surface.__reviewMapState || createMap(component, surface);
  surface.__reviewMapState = state;
  state.component = component;
  if (state.sourceRevision !== data.source_revision) {
    state.cache.clear();
    state.sourceRevision = data.source_revision;
    state.excluded = new Set(data.excluded_keys || []);
    state.selectionVersion = data.selection_version || 0;
    state.exportToken = null;
  }
  if ((data.selection_version || 0) >= state.selectionVersion) {
    state.excluded = new Set(data.excluded_keys || []);
    state.selectionVersion = data.selection_version || 0;
  }
  if (state.revision !== data.revision) {
    state.close();
    state.layers.clearLayers();
    state.markers.clear();
    state.counts.clear();
    state.exportToken = null;
    state.cells = new Map(data.cells.map((cell) => [cell.key, cell]));
    const L = window.L;
    for (const cell of data.cells) {
      const marker = L.circleMarker([cell.latitude, cell.longitude], {
        radius: cell.radius,
        color: '#ffffff',
        weight: 1.5,
        fillColor: cell.colour,
        fillOpacity: 0.88,
        bubblingMouseEvents: false,
      }).addTo(state.layers);
      state.markers.set(cell.key, marker);
      marker.on('mouseover', () => state.open(cell.key));
      marker.on('mouseout', state.scheduleClose);
      marker.on('click', () => state.open(cell.key, true));
      const node = marker.getElement();
      if (node) {
        node.setAttribute('tabindex', '0');
        node.setAttribute('role', 'button');
        node.setAttribute(
          'aria-label',
          `Open ${cell.count} photograph${cell.count === 1 ? '' : 's'}`,
        );
        node.addEventListener('focus', () => state.open(cell.key));
        node.addEventListener('blur', state.scheduleClose);
        node.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            state.open(cell.key, true);
          }
        });
      }
      if (cell.count > 1) {
        const countMarker = L.marker([cell.latitude, cell.longitude], {
          interactive: false,
          keyboard: false,
          icon: L.divIcon({
            className: 'map-count',
            html: `<span>${Number(cell.count)}</span>`,
            iconSize: [48, 22],
            iconAnchor: [24, 11],
          }),
        }).addTo(state.layers);
        state.counts.set(cell.key, countMarker);
      }
    }
    state.root.querySelector('.map-empty').hidden = data.cells.length > 0;
    state.revision = data.revision;
  }
  state.renderSelection();
  state.showExport(data.export_response);
  const response = data.photo_response;
  if (response && response.token === state.token) {
    const photo = state.cells.get(state.selected)?.photos[state.index];
    if (photo) {
      state.cache.set(photo.key, response);
      while (state.cache.size > 48) state.cache.delete(state.cache.keys().next().value);
    }
    state.showResponse(response);
  }
  return state.cleanup;
}
