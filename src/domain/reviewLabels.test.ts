import { describe, expect, it } from 'vitest';

import labelSchema from '../../schemas/review-labels-v1.json';
import {
  highestPriorityLabel,
  PIPELINE_MAPPINGS,
  REVIEW_LABEL_CODES,
  REVIEW_LABEL_SCHEMA_VERSION,
  REVIEW_LABELS,
} from './reviewLabels';

describe('canonical review labels', () => {
  it('defines all 15 stored codes exactly once', () => {
    expect(REVIEW_LABEL_CODES).toHaveLength(15);
    expect(new Set(REVIEW_LABEL_CODES)).toHaveLength(15);
    expect(REVIEW_LABELS.map((label) => label.code)).toEqual(REVIEW_LABEL_CODES);
  });

  it('agrees with the machine-readable versioned schema', () => {
    expect(labelSchema.schemaVersion).toBe(REVIEW_LABEL_SCHEMA_VERSION);
    expect(labelSchema.singleSelect).toBe(true);
    expect(labelSchema.labels).toEqual(REVIEW_LABELS);
    expect(labelSchema.mappings).toEqual(PIPELINE_MAPPINGS);
  });

  it('keeps every pipeline mapping canonical and training exclusions separate', () => {
    const validCodes = new Set<string>(REVIEW_LABEL_CODES);
    for (const mapping of Object.values(PIPELINE_MAPPINGS)) {
      expect(mapping.every((code) => validCodes.has(code))).toBe(true);
    }

    const exclusions = new Set<string>(PIPELINE_MAPPINGS.excludedFromAutomaticTraining);
    expect(PIPELINE_MAPPINGS.insectaPositive.every((code) => !exclusions.has(code))).toBe(true);
    expect(PIPELINE_MAPPINGS.butterflyPositive.every((code) => !exclusions.has(code))).toBe(true);
  });

  it('applies the deterministic multi-subject priority rule', () => {
    expect(highestPriorityLabel(['plant', 'adult_butterfly'])).toBe('adult_butterfly');
    expect(highestPriorityLabel(['plant', 'other_insect'])).toBe('other_insect');
    expect(highestPriorityLabel(['bird', 'mammal_or_person'])).toBe('mammal_or_person');
    expect(highestPriorityLabel([])).toBeNull();
  });
});
