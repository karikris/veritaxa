export function labelGroup(label) {
  const name = (label || '').trim().toLowerCase();
  if (name === 'papilio demoleus') return 'Papilio demoleus';
  if (name === 'papilio demodocus') return 'Papilio demodocus';
  return 'Other';
}

export function selectionGroup(photo) {
  return photo?.group || labelGroup(photo?.label);
}

/** Selection rules act on individual image keys, even when images share a bubble. */
export function filterExclusionReason(selection, key) {
  const photo = selection.catalog.get(key);
  if (selection.excludedRegions.has(photo?.region)) return `Excluded by continent: ${photo.region}`;
  if (selection.excludedLabels.has(selectionGroup(photo)))
    return photo?.group
      ? `Excluded by dataset: ${photo.group}`
      : `Excluded by BioCLIP group: ${labelGroup(photo?.label)} (${photo?.label || 'Unlabeled'})`;
  return null;
}

export function imageExclusionReason(selection, key) {
  if (selection.included.has(key)) return null;
  if (selection.excluded.has(key)) return 'Excluded manually';
  return filterExclusionReason(selection, key);
}

export function setImageExclusion(selection, key, excluded) {
  if (!selection.catalog.has(key)) return;
  if (excluded) {
    selection.included.delete(key);
    selection.excluded.add(key);
  } else {
    selection.excluded.delete(key);
    if (filterExclusionReason(selection, key)) selection.included.add(key);
    else selection.included.delete(key);
  }
}

export function setLocationExclusion(selection, keys, excluded) {
  for (const key of keys) setImageExclusion(selection, key, excluded);
}
