export const REVIEW_LABEL_SCHEMA_VERSION = 'veritaxa-review-label-v3' as const;

export const REVIEW_LABEL_CODES = [
  'target_scientific_name',
  'adult_butterfly',
  'caterpillar',
  'moth',
  'other_insect',
  'arachnid',
  'other_arthropod',
  'plant',
  'mammal_or_person',
  'bird',
  'other_animal',
  'fungus',
  'artifact_or_illustration',
  'no_biological_subject',
  'uncertain',
  'image_unavailable',
] as const;

export type ReviewLabelCode = (typeof REVIEW_LABEL_CODES)[number];
export type ReviewLabelGroup =
  'target_taxon' | 'insecta' | 'arthropods' | 'biological_negatives' | 'review_state';

export type ReviewLabelDefinition = {
  code: ReviewLabelCode;
  displayLabel: string;
  group: ReviewLabelGroup;
  priority: number;
  shortcut: string;
};

export const REVIEW_LABELS: readonly ReviewLabelDefinition[] = [
  {
    code: 'target_scientific_name',
    displayLabel: 'Target scientific name',
    group: 'target_taxon',
    priority: 1,
    shortcut: 'K',
  },
  {
    code: 'adult_butterfly',
    displayLabel: 'Adult butterfly',
    group: 'insecta',
    priority: 2,
    shortcut: 'B',
  },
  {
    code: 'caterpillar',
    displayLabel: 'Caterpillar',
    group: 'insecta',
    priority: 3,
    shortcut: 'C',
  },
  { code: 'moth', displayLabel: 'Moth', group: 'insecta', priority: 4, shortcut: 'M' },
  {
    code: 'other_insect',
    displayLabel: 'Other insect',
    group: 'insecta',
    priority: 5,
    shortcut: 'I',
  },
  {
    code: 'arachnid',
    displayLabel: 'Spider or other arachnid',
    group: 'arthropods',
    priority: 6,
    shortcut: 'A',
  },
  {
    code: 'other_arthropod',
    displayLabel: 'Other arthropod',
    group: 'arthropods',
    priority: 7,
    shortcut: 'R',
  },
  {
    code: 'plant',
    displayLabel: 'Plant',
    group: 'biological_negatives',
    priority: 11,
    shortcut: 'P',
  },
  {
    code: 'mammal_or_person',
    displayLabel: 'Mammal or person',
    group: 'biological_negatives',
    priority: 8,
    shortcut: 'H',
  },
  {
    code: 'bird',
    displayLabel: 'Bird',
    group: 'biological_negatives',
    priority: 9,
    shortcut: 'D',
  },
  {
    code: 'other_animal',
    displayLabel: 'Other animal',
    group: 'biological_negatives',
    priority: 10,
    shortcut: 'O',
  },
  {
    code: 'fungus',
    displayLabel: 'Fungus',
    group: 'biological_negatives',
    priority: 12,
    shortcut: 'F',
  },
  {
    code: 'artifact_or_illustration',
    displayLabel: 'Object, artwork or illustration',
    group: 'review_state',
    priority: 13,
    shortcut: 'X',
  },
  {
    code: 'no_biological_subject',
    displayLabel: 'No clear biological subject',
    group: 'review_state',
    priority: 14,
    shortcut: 'N',
  },
  {
    code: 'uncertain',
    displayLabel: 'Uncertain',
    group: 'review_state',
    priority: 15,
    shortcut: 'U',
  },
  {
    code: 'image_unavailable',
    displayLabel: 'Image unavailable',
    group: 'review_state',
    priority: 16,
    shortcut: 'V',
  },
] as const;

export const REVIEW_LABEL_GROUPS: readonly {
  code: ReviewLabelGroup;
  heading: string;
}[] = [
  { code: 'target_taxon', heading: 'Target scientific name' },
  { code: 'insecta', heading: 'Insecta and Lepidoptera' },
  { code: 'arthropods', heading: 'Other arthropods' },
  { code: 'biological_negatives', heading: 'Other biological negatives' },
  { code: 'review_state', heading: 'Non-biological and review state' },
];

export const PIPELINE_MAPPINGS = {
  targetScientificName: ['target_scientific_name'],
  insectaPositive: ['adult_butterfly', 'caterpillar', 'moth', 'other_insect'],
  lepidopteraEvidence: ['adult_butterfly', 'caterpillar', 'moth'],
  butterflyPositive: ['adult_butterfly'],
  butterflyHardNegatives: ['moth', 'other_insect', 'arachnid', 'other_arthropod'],
  broadBiologicalNegatives: ['plant', 'mammal_or_person', 'bird', 'other_animal', 'fungus'],
  nonBiologicalNegatives: ['artifact_or_illustration', 'no_biological_subject'],
  excludedFromAutomaticTraining: ['uncertain', 'image_unavailable'],
} as const satisfies Record<string, readonly ReviewLabelCode[]>;

const LABEL_CODE_SET = new Set<string>(REVIEW_LABEL_CODES);

export function isReviewLabelCode(value: unknown): value is ReviewLabelCode {
  return typeof value === 'string' && LABEL_CODE_SET.has(value);
}

export const LABEL_BY_SHORTCUT = new Map(
  REVIEW_LABELS.map((label) => [label.shortcut.toLowerCase(), label.code]),
);
