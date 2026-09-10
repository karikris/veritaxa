type ProcessMemory = { rssMiB: number; pssMiB: number };
type Sample = {
  navigation: number;
  heapBeforeGC: number;
  heapAfterGC: number;
  discardedDrafts: number;
  dom: Record<string, unknown>;
  process: ProcessMemory;
  processBeforeGC: ProcessMemory;
  native: { allocators: Record<string, number> };
};

export type SoakReport = {
  profile: string;
  navigations: number;
  networkRecording: boolean;
  requests: { preview: number; original: number };
  requestsBeforeInspection: { preview: number; original: number };
  samples: Sample[];
  sourceSamples: { original: boolean }[];
};

export const PLATEAU_LIMITS = {
  heapMiB: 1,
  pssMiB: 64,
  rssMiB: 128,
  decodedMiB: 32,
  gpuMiB: 16,
  partitionMiB: 4,
} as const;

function finite(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0)
    throw new Error('Memory evidence contains missing, negative or nonfinite values');
  return value;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) throw new Error('Memory evidence is empty');
  return (sorted[Math.floor((sorted.length - 1) / 2)] + sorted[Math.floor(sorted.length / 2)]) / 2;
}

export function evaluateSoak(report: SoakReport) {
  const issues: string[] = [];
  if (
    report.navigations !== 1000 ||
    report.samples.length !== 11 ||
    report.samples.some((sample, index) => sample.navigation !== index * 100)
  )
    throw new Error('A soak requires 1,000 navigations and all 11 checkpoints');
  if (!['desktop', 'drafts', 'mobile-pressure', 'control'].includes(report.profile))
    throw new Error('Unknown browser profile');
  if (report.networkRecording)
    issues.push('Network recording contaminates the native-memory measurement');
  const drafts = report.profile === 'drafts' || report.profile === 'mobile-pressure';
  for (const sample of report.samples) {
    if (sample.discardedDrafts !== (drafts ? Math.max(0, sample.navigation - 255) : 0))
      issues.push(`Draft capacity was not exercised correctly at ${String(sample.navigation)}`);
    for (const field of ['documents', 'nodes', 'jsEventListeners']) {
      if (finite(sample.dom[field]) !== finite(report.samples[0].dom[field]))
        issues.push(`Retained DOM ${field} changed at ${String(sample.navigation)}`);
    }
    if (finite(sample.heapBeforeGC) > 16 || finite(sample.heapAfterGC) > 16)
      issues.push('Sampled JavaScript heap exceeded 16 MiB');
    finite(sample.processBeforeGC.pssMiB);
    finite(sample.processBeforeGC.rssMiB);
  }
  if (
    report.requestsBeforeInspection.original !== 0 ||
    report.requests.original !== 1 ||
    report.sourceSamples.length !== 2 ||
    !report.sourceSamples[0].original ||
    report.sourceSamples[1].original
  )
    issues.push('Explicit source inspection/return was not demonstrated');
  if (
    report.requestsBeforeInspection.preview < 1000 ||
    report.requests.preview !== report.requestsBeforeInspection.preview
  )
    issues.push('Real image requests or cached return-to-preview were not demonstrated');
  const metrics = {
    heapMiB: (sample: Sample) => finite(sample.heapAfterGC),
    pssMiB: (sample: Sample) => finite(sample.process.pssMiB),
    rssMiB: (sample: Sample) => finite(sample.process.rssMiB),
    decodedMiB: (sample: Sample) => finite(sample.native.allocators['cc/image_memory']) / 1024 ** 2,
    gpuMiB: (sample: Sample) => finite(sample.native.allocators['gpu/shared_images']) / 1024 ** 2,
    partitionMiB: (sample: Sample) => finite(sample.native.allocators.partition_alloc) / 1024 ** 2,
  };
  // Drafts have filled by 255. Use every checkpoint after that warm-up, not
  // just the endpoints: compare three-sample medians and fitted total growth.
  const steady = report.samples.slice(3);
  const plateau = Object.fromEntries(
    Object.entries(metrics).map(([name, get]) => {
      const values = steady.map(get);
      const early = median(values.slice(0, 3));
      const late = median(values.slice(-3));
      const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
      const center = (values.length - 1) / 2;
      const numerator = values.reduce((sum, value, i) => sum + (i - center) * (value - mean), 0);
      const denominator = values.reduce((sum, _, i) => sum + (i - center) ** 2, 0);
      const fittedGrowth = (numerator / denominator) * (values.length - 1);
      const limit = PLATEAU_LIMITS[name as keyof typeof PLATEAU_LIMITS];
      if (Math.max(late - early, fittedGrowth) > limit)
        issues.push(`${name} retained growth exceeded ${String(limit)}`);
      return [
        name,
        {
          early,
          late,
          medianGrowth: late - early,
          fittedGrowth,
          limit,
          maximum: Math.max(...report.samples.map(get)),
        },
      ];
    }),
  );
  return { passed: issues.length === 0, issues, plateau };
}
