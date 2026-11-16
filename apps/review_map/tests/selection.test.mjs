import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterExclusionReason,
  labelGroup,
  imageExclusionReason,
  setImageExclusion,
  setLocationExclusion,
} from '../frontend/selection.js';

function selection() {
  return {
    catalog: new Map([
      ['a', { label: 'Papilio demoleus', region: 'Europe' }],
      ['b', { label: 'Papilio demodocus', region: 'Europe' }],
      ['c', { label: 'Papilio demoleus', region: 'Asia' }],
    ]),
    excluded: new Set(),
    included: new Set(),
    excludedLabels: new Set(),
    excludedRegions: new Set(),
  };
}

test('a top-1 label excludes matching images, preserving other images at the same location', () => {
  const state = selection();
  state.excludedLabels.add('Papilio demoleus');
  assert.match(imageExclusionReason(state, 'a'), /BioCLIP/);
  assert.equal(imageExclusionReason(state, 'b'), null);
  assert.match(imageExclusionReason(state, 'c'), /BioCLIP/);
  assert.equal(state.excluded.size, 0);
});

test('individual exclusions and restores affect only the current image', () => {
  const state = selection();
  setImageExclusion(state, 'b', true);
  assert.equal(imageExclusionReason(state, 'b'), 'Excluded manually');
  assert.equal(imageExclusionReason(state, 'a'), null);
  setImageExclusion(state, 'b', false);
  assert.equal(imageExclusionReason(state, 'b'), null);
  assert.equal(state.included.size, 0);
});

test('an image can be restored individually under an active label filter', () => {
  const state = selection();
  state.excludedLabels.add('Papilio demoleus');
  setImageExclusion(state, 'a', false);
  assert.equal(imageExclusionReason(state, 'a'), null);
  assert.match(filterExclusionReason(state, 'a'), /BioCLIP/);
  assert.match(imageExclusionReason(state, 'c'), /BioCLIP/);
  assert.equal(state.excludedLabels.has('Papilio demoleus'), true);
  setImageExclusion(state, 'a', true);
  assert.equal(state.included.has('a'), false);
  assert.equal(imageExclusionReason(state, 'a'), 'Excluded manually');
});

test('whole-location actions remain explicit and leave other locations alone', () => {
  const state = selection();
  state.excludedLabels.add('Papilio demoleus');
  setLocationExclusion(state, ['a', 'b'], true);
  assert.equal(imageExclusionReason(state, 'a'), 'Excluded manually');
  assert.equal(imageExclusionReason(state, 'b'), 'Excluded manually');
  setLocationExclusion(state, ['a', 'b'], false);
  assert.equal(imageExclusionReason(state, 'a'), null);
  assert.equal(imageExclusionReason(state, 'b'), null);
  assert.match(imageExclusionReason(state, 'c'), /BioCLIP/);
});

test('continent filters and individual exceptions do not spill into adjacent images', () => {
  const state = selection();
  state.excludedRegions.add('Europe');
  setImageExclusion(state, 'a', false);
  assert.equal(imageExclusionReason(state, 'a'), null);
  assert.match(imageExclusionReason(state, 'b'), /continent/);
  assert.equal(imageExclusionReason(state, 'c'), null);
});

test('Other groups odd top1 labels without rewriting their exact names', () => {
  assert.equal(labelGroup(' Papilio demoleus '), 'Papilio demoleus');
  assert.equal(labelGroup('Papilio demodocus'), 'Papilio demodocus');
  for (const name of ['Synthetic gamma', 'Synthetic delta', ''])
    assert.equal(labelGroup(name), 'Other');
  const state = selection();
  state.catalog.set('odd', { label: 'Synthetic gamma', region: 'Europe' });
  state.excludedLabels.add('Other');
  assert.match(imageExclusionReason(state, 'odd'), /Synthetic gamma/);
  assert.equal(imageExclusionReason(state, 'a'), null);
  assert.equal(imageExclusionReason(state, 'b'), null);
  setImageExclusion(state, 'odd', false);
  assert.equal(imageExclusionReason(state, 'odd'), null);
  assert.equal(state.catalog.get('odd').label, 'Synthetic gamma');
});
