/* global window, ResizeObserver, setTimeout, clearTimeout */

const LANDING_ZOOM = 2;
const WORLD_BOUNDS = [
  [-85.0511287798, -180],
  [85.0511287798, 180],
];

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
  const clearExclusions = toolbar.querySelector('.clear-exclusions');
  const includeVisible = toolbar.querySelector('.include-visible');
  const continentSelect = toolbar.querySelector('.continent-select');
  const continentSummary = toolbar.querySelector('.continent-summary');
  const labelSelect = toolbar.querySelector('.label-select');
  const labelSummary = toolbar.querySelector('.label-summary');
  const labelOptions = toolbar.querySelector('.label-options');
  const regionOptions = component.parentElement.querySelector('.region-options');
  const limitDates = component.parentElement.querySelector('.limit-csv-dates');
  const exportStatus = toolbar.querySelector('.export-status');
  const excluded = root.querySelector('.photo-excluded');
  const exclusionLabel = root.querySelector('.photo-exclusion-label');
  const imageExcluded = root.querySelector('.photo-image-excluded');
  const imageStatus = root.querySelector('.photo-image-status');
  const modelLabel = root.querySelector('.photo-model-label');
  const locationSummary = root.querySelector('.photo-location-summary');
  const page = root.querySelector('.photo-page');
  const map = L.map(surface, {
    minZoom: LANDING_ZOOM,
    maxZoom: 18,
    zoomSnap: 0.25,
    maxBounds: WORLD_BOUNDS,
    maxBoundsViscosity: 1,
    worldCopyJump: false,
    bounceAtZoomLimits: false,
    wheelDebounceTime: 20,
    wheelPxPerZoomLevel: 80,
    zoomAnimation: false,
  }).setView([14, 0], LANDING_ZOOM);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    noWrap: true,
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
    excludedMarkers: new Map(),
    markerStyles: new Map(),
    catalog: new Map(),
    cellKeys: new Map(),
    visibleKeys: new Set(),
    excludedRegions: new Set(),
    excludedLabels: new Set(),
    labelInputs: new Map(),
    limitDates: false,
    regionInputs: new Map(),
    excluded: new Set(),
    included: new Set(),
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

  state.isExcluded = (key) => imageExclusionReason(state, key) !== null;
  state.includedKeys = () =>
    [...state.catalog.keys()].filter(
      (key) => !state.isExcluded(key) && (!state.limitDates || state.visibleKeys.has(key)),
    );
  state.renderCardSelection = () => {
    const keys = state.cellKeys.get(state.selected) || [];
    const excludedCount = keys.filter((key) => state.isExcluded(key)).length;
    excluded.checked = keys.length > 0 && excludedCount === keys.length;
    excluded.indeterminate = excludedCount > 0 && excludedCount < keys.length;
    excluded.disabled = keys.length === 0;
    exclusionLabel.textContent = `Exclude this location (${keys.length.toLocaleString()} image${keys.length === 1 ? '' : 's'})`;
    locationSummary.textContent = `${excludedCount} of ${keys.length} images excluded at this location`;
    locationSummary.hidden = keys.length <= 1;
    const photo = state.cells.get(state.selected)?.photos[state.index];
    if (photo) {
      const reason = imageExclusionReason(state, photo.key);
      imageExcluded.checked = reason !== null;
      modelLabel.textContent = state.catalog.get(photo.key)?.label || 'Unavailable';
      imageStatus.textContent =
        reason ||
        (state.included.has(photo.key) && filterExclusionReason(state, photo.key)
          ? 'Included individually despite active filters'
          : 'Included in CSV');
      imageStatus.dataset.excluded = String(reason !== null);
    }
    state.positionCard?.();
  };
  state.renderSelection = () => {
    const markersChanged =
      state.drawnRevision !== state.revision ||
      state.drawnSelectionVersion !== state.selectionVersion;
    for (const cell of markersChanged ? state.cells.values() : []) {
      const selected = cell.photos.filter((photo) => !state.isExcluded(photo.key));
      const excludedCount = cell.photos.length - selected.length;
      const seriesCount = new Set(selected.map((photo) => photo.series)).size;
      const radius = Math.min(38, 6 * Math.sqrt(Math.max(1, seriesCount)));
      const styleKey = `${seriesCount}:${excludedCount}:${selected[0]?.colour || ''}`;
      if (state.markerStyles.get(cell.key) === styleKey) continue;
      state.markerStyles.set(cell.key, styleKey);
      const marker = state.markers.get(cell.key);
      marker?.setRadius(radius);
      marker?.setStyle({ fillColor: selected[0]?.colour || '#94a3b8', fillOpacity: 0.88 });
      const circle = marker?.getElement();
      if (circle) circle.style.display = selected.length ? '' : 'none';
      const square = state.excludedMarkers.get(cell.key)?.getElement();
      if (square) {
        square.hidden = excludedCount === 0;
        square.querySelector('span').style.transform = selected.length
          ? `translateX(${radius + 9}px)`
          : '';
        square.setAttribute(
          'aria-label',
          `Open ${excludedCount} excluded photograph${excludedCount === 1 ? '' : 's'}`,
        );
      }
      const label = state.counts.get(cell.key)?.getElement();
      if (label) {
        label.querySelector('span').textContent = String(seriesCount);
        label.hidden = seriesCount <= 1;
      }
    }
    state.drawnRevision = state.revision;
    state.drawnSelectionVersion = state.selectionVersion;
    const count = state.includedKeys().length;
    const total = state.limitDates ? state.visibleKeys.size : state.catalog.size;
    summary.textContent = `${count.toLocaleString()} of ${total.toLocaleString()} images included in CSV`;
    download.disabled = count === 0 || Boolean(state.exportToken);
    clearExclusions.disabled =
      state.excluded.size === 0 &&
      state.included.size === 0 &&
      state.excludedRegions.size === 0 &&
      state.excludedLabels.size === 0;
    includeVisible.disabled = ![...state.visibleKeys].some((key) => state.isExcluded(key));
    const selectedRegions = state.regionInputs.size - state.excludedRegions.size;
    continentSummary.textContent =
      selectedRegions === state.regionInputs.size
        ? 'Continents: all selected'
        : `Continents: ${selectedRegions} selected`;
    const selectedLabels = state.labelInputs.size - state.excludedLabels.size;
    labelSummary.textContent =
      selectedLabels === state.labelInputs.size
        ? 'BioCLIP top-1: all selected'
        : `BioCLIP top-1: ${selectedLabels} selected`;
    for (const [label, input] of state.labelInputs)
      input.checked = !state.excludedLabels.has(label);
    limitDates.checked = state.limitDates;
    for (const [region, input] of state.regionInputs)
      input.checked = !state.excludedRegions.has(region);
    state.renderCardSelection();
  };
  state.saveSelection = () => {
    state.selectionVersion++;
    state.exportToken = null;
    exportStatus.textContent = '';
    state.renderSelection();
    state.component.setStateValue('exclusions', {
      source_revision: state.sourceRevision,
      version: state.selectionVersion,
      keys: [...state.excluded],
      included_keys: [...state.included],
      regions: [...state.excludedRegions],
      labels: [...state.excludedLabels],
      limit_dates: state.limitDates,
    });
  };
  state.buildRegionOptions = (regions) => {
    regionOptions.replaceChildren();
    state.regionInputs.clear();
    for (const region of regions) {
      const count = [...state.catalog.values()].filter((photo) => photo.region === region).length;
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.setAttribute('aria-label', `Include ${region}`);
      input.addEventListener('change', () => {
        if (input.checked) state.excludedRegions.delete(region);
        else state.excludedRegions.add(region);
        state.saveSelection();
      });
      const text = document.createElement('span');
      text.textContent = `${region} (${count.toLocaleString()})`;
      label.append(input, text);
      regionOptions.append(label);
      state.regionInputs.set(region, input);
    }
  };
  state.buildLabelOptions = (labels) => {
    labelOptions.replaceChildren();
    state.labelInputs.clear();
    for (const value of labels) {
      const count = [...state.catalog.values()].filter((photo) => photo.label === value).length;
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.setAttribute('aria-label', `Include BioCLIP ${value || 'Unlabeled'}`);
      input.addEventListener('change', () => {
        if (input.checked) state.excludedLabels.delete(value);
        else state.excludedLabels.add(value);
        state.saveSelection();
      });
      const text = document.createElement('span');
      text.textContent = `${value || 'Unlabeled'} (${count.toLocaleString()})`;
      label.append(input, text);
      labelOptions.append(label);
      state.labelInputs.set(value, input);
    }
  };
  for (const [selector, field, inputs, clear] of [
    ['.region-all', 'excludedRegions', 'regionInputs', true],
    ['.region-none', 'excludedRegions', 'regionInputs', false],
    ['.label-all', 'excludedLabels', 'labelInputs', true],
    ['.label-none', 'excludedLabels', 'labelInputs', false],
  ]) {
    toolbar.querySelector(selector).addEventListener('click', () => {
      state[field] = clear ? new Set() : new Set(state[inputs].keys());
      state.saveSelection();
    });
  }
  toolbar.querySelector('.label-search').addEventListener('input', (event) => {
    const query = event.target.value.trim().toLowerCase();
    for (const option of labelOptions.querySelectorAll('label'))
      option.hidden = !option.textContent.toLowerCase().includes(query);
  });
  imageExcluded.addEventListener('change', () => {
    const photo = state.cells.get(state.selected)?.photos[state.index];
    if (!photo) return;
    setImageExclusion(state, photo.key, imageExcluded.checked);
    state.pinned = true;
    state.saveSelection();
  });
  excluded.addEventListener('change', () => {
    setLocationExclusion(state, state.cellKeys.get(state.selected) || [], excluded.checked);
    state.pinned = true;
    state.saveSelection();
  });
  includeVisible.addEventListener('click', () => {
    for (const key of state.visibleKeys) setImageExclusion(state, key, false);
    state.saveSelection();
  });
  const outsideClick = (event) => {
    for (const dropdown of [continentSelect, labelSelect]) {
      if (!event.composedPath().includes(dropdown)) dropdown.open = false;
    }
  };
  document.addEventListener('pointerdown', outsideClick);
  for (const [dropdown, summary] of [
    [continentSelect, continentSummary],
    [labelSelect, labelSummary],
  ]) {
    dropdown.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        dropdown.open = false;
        summary.focus();
      }
    });
  }
  clearExclusions.addEventListener('click', () => {
    state.excluded.clear();
    state.included.clear();
    state.excludedRegions.clear();
    state.excludedLabels.clear();
    state.saveSelection();
  });
  limitDates.addEventListener('change', () => {
    state.limitDates = limitDates.checked;
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
      limit_dates: state.limitDates,
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
    state.renderCardSelection();
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
  state.open = (key, pin = false, index = null) => {
    clearTimeout(state.hideTimer);
    if (state.pinned && !pin && state.selected !== key) return;
    const changed = state.selected !== key;
    state.selected = key;
    state.pinned = pin || state.pinned;
    if (changed) {
      const firstIncluded = state.cells
        .get(key)
        .photos.findIndex((photo) => !state.isExcluded(photo.key));
      state.index = firstIncluded < 0 ? 0 : firstIncluded;
    }
    if (index !== null) state.index = index;
    card.hidden = false;
    state.positionCard();
    if (changed || !state.token || index !== null) state.requestPhoto(pin ? 0 : 160);
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
  state.constrainViewport = () => {
    map.invalidateSize({ pan: false });
    const minimum = Math.max(
      LANDING_ZOOM,
      Math.log2(Math.max(surface.clientWidth, surface.clientHeight, 1) / 256),
    );
    map.setMinZoom(minimum);
    if (map.getZoom() < minimum) map.setZoom(minimum, { animate: false });
    map.panInsideBounds(WORLD_BOUNDS, { animate: false });
    state.positionCard();
  };
  state.constrainViewport();
  const observer = new ResizeObserver(state.constrainViewport);
  observer.observe(surface);
  state.cleanup = () => {
    clearTimeout(state.hideTimer);
    clearTimeout(state.loadTimer);
    observer.disconnect();
    document.removeEventListener('pointerdown', outsideClick);
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
    state.included = new Set(data.included_keys || []);
    state.selectionVersion = data.selection_version || 0;
    state.exportToken = null;
    state.catalog = new Map(data.catalog.map((photo) => [photo.key, photo]));
    state.cellKeys = new Map();
    for (const photo of data.catalog) {
      if (!state.cellKeys.has(photo.cell)) state.cellKeys.set(photo.cell, []);
      state.cellKeys.get(photo.cell).push(photo.key);
    }
    state.buildRegionOptions(data.regions);
    state.buildLabelOptions(data.labels);
  }
  if ((data.selection_version || 0) >= state.selectionVersion) {
    state.excluded = new Set(data.excluded_keys || []);
    state.included = new Set(data.included_keys || []);
    state.selectionVersion = data.selection_version || 0;
    state.excludedRegions = new Set(data.excluded_regions || []);
    state.excludedLabels = new Set(data.excluded_labels || []);
    state.limitDates = Boolean(data.limit_csv_dates);
  }
  if (state.revision !== data.revision) {
    state.close();
    state.layers.clearLayers();
    state.markers.clear();
    state.counts.clear();
    state.excludedMarkers.clear();
    state.markerStyles.clear();
    state.exportToken = null;
    state.cells = new Map(data.cells.map((cell) => [cell.key, cell]));
    state.visibleKeys = new Set(
      data.cells.flatMap((cell) => cell.photos.map((photo) => photo.key)),
    );
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
      const excludedMarker = L.marker([cell.latitude, cell.longitude], {
        keyboard: true,
        icon: L.divIcon({
          className: 'map-excluded',
          html: '<span class="map-excluded-square"></span>',
          iconSize: [10, 10],
          iconAnchor: [5, 5],
        }),
      }).addTo(state.layers);
      const openExcluded = (pin = false) => {
        const index = cell.photos.findIndex((photo) => state.isExcluded(photo.key));
        if (index !== -1) state.open(cell.key, pin, index);
      };
      excludedMarker.on('mouseover', () => openExcluded());
      excludedMarker.on('mouseout', state.scheduleClose);
      excludedMarker.on('click', () => openExcluded(true));
      state.excludedMarkers.set(cell.key, excludedMarker);
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
            html: `<span>${Number(cell.series_count)}</span>`,
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
