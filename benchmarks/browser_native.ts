import { record, type CdpSession } from './browser_cdp.ts';

export type DumpContext = { profile: string; navigation: number; phase: string };
export type DumpAttempt = DumpContext & {
  attempt: number;
  stage: string;
  dumpGuid: string | null;
  requestSuccess: boolean | null;
  traceCompleted: boolean;
  dataLossOccurred: boolean | null;
  dumps: number;
  requiredAllocators: Record<string, number | null>;
  conditions: string[];
  invalidAllocators: { name: string; value: string | null; units: string | null }[];
  cleanupErrors: string[];
  error: string | null;
};
const required = ['cc/image_memory', 'gpu/shared_images', 'partition_alloc'];
const roots = new Set([
  ...required,
  'discardable',
  'skia/sk_resource_cache',
  'web_cache/Image_resources',
]);
const retryable = new Set([
  'request_failed',
  'trace_data_loss',
  'no_allocator_dumps',
  'missing_allocator',
]);

export class NativeMemoryError extends Error {
  constructor(readonly diagnostic: DumpAttempt) {
    super(
      `Native memory measurement failed: ${diagnostic.conditions.join(', ')} (${diagnostic.stage})`,
    );
    this.name = 'NativeMemoryError';
  }
}

type Options = {
  delay?: (ms: number) => Promise<void>;
  onAttempt?: (attempt: DumpAttempt) => void;
  timeoutMs?: number;
  checkHealth?: () => void;
};

/** Keep partial trace evidence local to one attempt; never combine retry metrics. */
async function collect(
  session: CdpSession,
  context: DumpContext,
  attempt: number,
  options: Options,
) {
  const diagnostic: DumpAttempt = {
    ...context,
    attempt,
    stage: 'start',
    dumpGuid: null,
    requestSuccess: null,
    traceCompleted: false,
    dataLossOccurred: null,
    dumps: 0,
    requiredAllocators: Object.fromEntries(required.map((name) => [name, null])),
    conditions: [],
    invalidAllocators: [],
    cleanupErrors: [],
    error: null,
  };
  const allocators: Record<string, number> = {};
  let active = false;
  let endRequested = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const condition = (code: string) => {
    if (!diagnostic.conditions.includes(code)) diagnostic.conditions.push(code);
  };
  const onData = (payload: unknown) => {
    const events = record(payload).value;
    if (!Array.isArray(events)) {
      condition('malformed_trace');
      return;
    }
    for (const raw of events) {
      const entries = record(record(record(record(raw).args).dumps).allocators);
      if (!Object.keys(entries).length) continue;
      diagnostic.dumps++;
      for (const [name, entry] of Object.entries(entries)) {
        if (name.includes('/') && !roots.has(name)) continue;
        const attrs = record(record(entry).attrs);
        // Hierarchy-only parent nodes have no size; other process dumps supply
        // their measured totals. Require aggregate metrics after all events.
        if (!('size' in attrs)) continue;
        const size = record(attrs.size);
        if (
          size.units !== 'bytes' ||
          typeof size.value !== 'string' ||
          !/^(?:0x)?[0-9a-f]+$/i.test(size.value)
        ) {
          if (required.includes(name)) {
            condition('invalid_allocator');
            diagnostic.invalidAllocators.push({
              name,
              value: typeof size.value === 'string' ? size.value : null,
              units: typeof size.units === 'string' ? size.units : null,
            });
          }
          continue;
        }
        const bytes = Number.parseInt(size.value, 16);
        const total = (allocators[name] ?? 0) + bytes;
        if (!Number.isSafeInteger(total) || total < 0) {
          diagnostic.invalidAllocators.push({ name, value: size.value, units: 'bytes' });
          condition('invalid_allocator');
          continue;
        }
        allocators[name] = total;
      }
    }
  };
  let onComplete: ((payload: unknown) => void) | undefined;
  options.onAttempt?.(diagnostic);
  session.on('Tracing.dataCollected', onData);
  try {
    await session.send('Tracing.start', {
      traceConfig: {
        includedCategories: ['disabled-by-default-memory-infra'],
        traceBufferSizeInKb: 8192,
      },
    });
    active = true;
    diagnostic.stage = 'request';
    const request = await session.send('Tracing.requestMemoryDump', {
      deterministic: false,
      levelOfDetail: 'detailed',
    });
    diagnostic.dumpGuid = typeof request.dumpGuid === 'string' ? request.dumpGuid : null;
    diagnostic.requestSuccess = typeof request.success === 'boolean' ? request.success : null;
    diagnostic.stage = 'finish';
    const done = new Promise<void>((resolve, reject) => {
      timer = setTimeout(() => {
        condition('trace_timeout');
        reject(new NativeMemoryError(diagnostic));
      }, options.timeoutMs ?? 30_000);
      onComplete = (payload: unknown) => {
        diagnostic.traceCompleted = true;
        const value = record(payload).dataLossOccurred;
        diagnostic.dataLossOccurred = typeof value === 'boolean' ? value : null;
        active = false;
        resolve();
      };
      session.once('Tracing.tracingComplete', onComplete);
    });
    endRequested = true;
    await Promise.all([session.send('Tracing.end'), done]);
    diagnostic.stage = 'validate';
    if (
      diagnostic.requestSuccess === null ||
      diagnostic.dataLossOccurred === null ||
      !diagnostic.dumpGuid
    )
      condition('malformed_response');
    if (diagnostic.requestSuccess === false) condition('request_failed');
    if (diagnostic.dataLossOccurred === true) condition('trace_data_loss');
    if (!diagnostic.dumps) condition('no_allocator_dumps');
    for (const name of required) {
      diagnostic.requiredAllocators[name] = allocators[name] ?? null;
      if (!(name in allocators)) condition('missing_allocator');
    }
    if (diagnostic.conditions.length) throw new NativeMemoryError(diagnostic);
    diagnostic.stage = 'complete';
    return { dumps: diagnostic.dumps, allocators };
  } catch (error) {
    if (!(error instanceof NativeMemoryError)) {
      condition(
        error instanceof Error && /timed out/i.test(error.message) ? 'cdp_timeout' : 'cdp_error',
      );
      diagnostic.error = error instanceof Error ? error.message : String(error);
    }
    throw new NativeMemoryError(diagnostic);
  } finally {
    clearTimeout(timer);
    if (onComplete) session.off('Tracing.tracingComplete', onComplete);
    session.off('Tracing.dataCollected', onData);
    // Do not send a second end command after a failed/unfinished end.
    if (active && !endRequested) {
      try {
        await session.send('Tracing.end');
      } catch (error) {
        diagnostic.cleanupErrors.push(
          `Tracing.end: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
    for (const name of required) diagnostic.requiredAllocators[name] = allocators[name] ?? null;
    options.onAttempt?.(diagnostic);
  }
}

export async function nativeMemory(
  session: CdpSession,
  context: DumpContext,
  options: Options = {},
) {
  for (let attempt = 1; attempt <= 2; attempt++) {
    options.checkHealth?.();
    try {
      return await collect(session, context, attempt, options);
    } catch (error) {
      if (
        !(error instanceof NativeMemoryError) ||
        attempt === 2 ||
        !error.diagnostic.traceCompleted ||
        error.diagnostic.cleanupErrors.length ||
        !error.diagnostic.conditions.length ||
        !error.diagnostic.conditions.every((code) => retryable.has(code))
      )
        throw error;
      options.checkHealth?.();
      await (options.delay ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms))))(250);
    }
  }
  throw new Error('Unreachable native memory attempt');
}
