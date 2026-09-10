import { writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { createBrowserFixture } from './browser_fixture.ts';
import { startBrowser, record, type CdpSession } from './browser_cdp.ts';
import { evaluateSoak } from './browser_gates.ts';
import { processFootprint } from './browser_proc.ts';

const { values } = parseArgs({
  options: {
    steps: { type: 'string', default: '1000' },
    profile: { type: 'string', default: 'desktop' },
    output: { type: 'string' },
    'record-network': { type: 'boolean', default: false },
  },
});
const steps = Number(values.steps);
if (
  !Number.isInteger(steps) ||
  steps < 1 ||
  steps > 1000 ||
  !['desktop', 'drafts', 'mobile-pressure', 'control'].includes(values.profile)
)
  throw new Error('Invalid synthetic browser probe arguments');
if (process.platform !== 'linux')
  throw new Error('The browser process-memory probe requires Linux');
const mobile = values.profile === 'mobile-pressure';
const drafts = values.profile === 'drafts' || mobile;
const mib = (bytes: number) => bytes / 1024 ** 2;

/** Capture named native allocators as well as total process memory, not JS alone. */
async function nativeMemory(session: CdpSession) {
  const allocators: Record<string, number> = {};
  let dumps = 0;
  const roots = new Set([
    'cc/image_memory',
    'discardable',
    'gpu/shared_images',
    'skia/sk_resource_cache',
    'web_cache/Image_resources',
  ]);
  const onData = ({ value }: { value: unknown[] }) => {
    for (const raw of value) {
      const event = record(raw);
      const dump = record(record(event.args).dumps);
      const entries = record(dump.allocators);
      if (!Object.keys(entries).length) continue;
      dumps += 1;
      for (const [name, entry] of Object.entries(entries)) {
        if (name.includes('/') && !roots.has(name)) continue;
        const size = record(record(record(entry).attrs).size);
        if (size.units !== 'bytes' || typeof size.value !== 'string') continue;
        const bytes = Number.parseInt(size.value, 16);
        if (Number.isFinite(bytes)) allocators[name] = (allocators[name] ?? 0) + bytes;
      }
    }
  };
  session.on('Tracing.dataCollected', onData);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onComplete: ((result: unknown) => void) | undefined;
  try {
    await session.send('Tracing.start', {
      traceConfig: {
        includedCategories: ['disabled-by-default-memory-infra'],
        traceBufferSizeInKb: 8192,
      },
    });
    const request = record(
      await session.send('Tracing.requestMemoryDump', {
        deterministic: false,
        levelOfDetail: 'detailed',
      }),
    );
    const done = new Promise<Record<string, unknown>>((resolve, reject) => {
      timer = setTimeout(
        () => reject(new Error('Native memory trace did not finish within 30 seconds')),
        30_000,
      );
      onComplete = (result: unknown) => resolve(record(result));
      session.once('Tracing.tracingComplete', onComplete);
    });
    const [, finished] = await Promise.all([session.send('Tracing.end'), done]);
    if (!request.success || finished.dataLossOccurred || !dumps || !allocators['cc/image_memory'])
      throw new Error('Native memory dump was incomplete');
    return { dumps, allocators };
  } finally {
    clearTimeout(timer);
    if (onComplete) session.off('Tracing.tracingComplete', onComplete);
    session.off('Tracing.dataCollected', onData);
  }
}

async function processMemory(session: CdpSession) {
  const result = record(await session.send('SystemInfo.getProcessInfo'));
  if (!Array.isArray(result.processInfo)) throw new Error('Browser process list is missing');
  const processes: { type: string; rssMiB: number; pssMiB: number }[] = [];
  const types = new Map<number, string>();
  for (const raw of result.processInfo) {
    const info = record(raw);
    if (typeof info.id !== 'number' || typeof info.type !== 'string') continue;
    types.set(info.id, info.type);
  }
  const root = [...types].find(([, type]) => type === 'browser')?.[0];
  if (!root) throw new Error('Browser root process is missing');
  const pending = new Set([root, ...types.keys()]);
  for (const pid of pending) {
    const footprint = processFootprint(pid);
    if (!footprint) continue;
    for (const child of footprint.children) pending.add(child);
    processes.push({
      type: types.get(pid) ?? 'browser-child',
      rssMiB: footprint.rssMiB,
      pssMiB: footprint.pssMiB,
    });
  }
  if (
    !processes.some((entry) => entry.type === 'renderer') ||
    !processes.some((entry) => entry.type === 'browser')
  )
    throw new Error('Browser/renderer process coverage was incomplete');
  return {
    rssMiB: processes.reduce((total, entry) => total + entry.rssMiB, 0),
    pssMiB: processes.reduce((total, entry) => total + entry.pssMiB, 0),
    processes,
  };
}

async function paintedImage(page: CdpSession, expectedPosition: number, original = false) {
  await page.evaluate(
    async ({ position, source }) => {
      const frame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      const started = performance.now();
      for (;;) {
        const node = document.querySelector<HTMLImageElement>('img.review-image');
        if (
          document.querySelector('.image-position')?.textContent === `${String(position)} / 1000` &&
          node?.complete &&
          node.naturalWidth === (source ? 3200 : 1600) &&
          node.naturalHeight === (source ? 2134 : 1067)
        ) {
          await node.decode();
          await frame();
          await frame();
          return;
        }
        if (performance.now() - started > 25_000)
          throw new Error('Expected real raster was not decoded');
        await frame();
      }
    },
    { position: expectedPosition, source: original },
  );
}

const fixture = await createBrowserFixture(values.profile === 'control');
let browser: Awaited<ReturnType<typeof startBrowser>> | undefined;
try {
  browser = await startBrowser(mobile);
  const page = browser.page;
  const errors: string[] = [];
  page.on('Runtime.exceptionThrown', () => errors.push('pageerror'));
  page.on('Inspector.targetCrashed', () => errors.push('crash'));
  const session = page;
  const browserSession = browser.root;
  if (values['record-network']) await session.send('Network.enable');
  await session.send('Performance.enable');
  const samples = [];
  let discardedDrafts = 0;
  const navigationResult = await page.send('Page.navigate', { url: fixture.url });
  if (navigationResult.errorText) throw new Error('Synthetic fixture navigation failed');
  await paintedImage(page, 1);
  const started = performance.now();
  for (let navigation = 0; navigation <= steps; navigation += 1) {
    if (navigation > 0) {
      discardedDrafts += await page.evaluate((retainDrafts) => {
        const next = document.querySelector<HTMLButtonElement>('[aria-label="Next image"]');
        if (!next) throw new Error('Navigation is missing');
        if (retainDrafts) {
          document.querySelector<HTMLInputElement>('input[value="plant"]')?.click();
          const comment = document.querySelector<HTMLTextAreaElement>('#review-comment');
          if (!comment) throw new Error('Comment is missing');
          comment.value = 'Synthetic 🦋 '.repeat(70);
          comment.dispatchEvent(new Event('input', { bubbles: true }));
        }
        next.click();
        const limit = document.querySelector<HTMLElement>('.draft-limit');
        if (limit && !limit.hidden) {
          document.querySelector<HTMLButtonElement>('.discard-draft')?.click();
          next.click();
          return 1;
        }
        return 0;
      }, drafts);
      await paintedImage(page, (navigation % 1000) + 1);
    }
    if (navigation % 100 !== 0 && navigation !== steps) continue;
    const before = record(await session.send('Performance.getMetrics'));
    const processBeforeGC = await processMemory(browserSession);
    if (mobile && navigation > 0) {
      await session.send('Memory.simulatePressureNotification', { level: 'critical' });
      // The notification is asynchronous across browser processes.
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    await session.send('HeapProfiler.collectGarbage');
    const after = record(await session.send('Performance.getMetrics'));
    const heap = (metrics: Record<string, unknown>) => {
      const found = Array.isArray(metrics.metrics)
        ? metrics.metrics.map(record).find((entry) => entry.name === 'JSHeapUsedSize')
        : undefined;
      if (typeof found?.value !== 'number') throw new Error('JS heap metric is missing');
      return mib(found.value);
    };
    const sample = {
      navigation,
      heapBeforeGC: heap(before),
      heapAfterGC: heap(after),
      discardedDrafts,
      processBeforeGC,
      dom: record(await session.send('Memory.getDOMCounters')),
      process: await processMemory(browserSession),
      native: await nativeMemory(browserSession),
    };
    samples.push(sample);
    console.log(
      JSON.stringify({
        profile: values.profile,
        navigation,
        heapMiB: sample.heapAfterGC,
        pssMiB: sample.process.pssMiB,
        decodedMiB: mib(sample.native.allocators['cc/image_memory']),
        discardedDrafts,
      }),
    );
    if (errors.length) throw new Error('Synthetic browser emitted an error or crashed');
  }
  if (fixture.requests.original !== 0)
    throw new Error('An original loaded without explicit inspection');
  const requestsBeforeInspection = { ...fixture.requests };
  const sourceSamples = [];
  for (const original of [true, false]) {
    await page.evaluate(() => {
      const control = document.querySelector<HTMLButtonElement>('.image-source-button');
      if (!control || control.disabled) throw new Error('Source inspection is unavailable');
      control.click();
    }, undefined);
    await paintedImage(page, (steps % 1000) + 1, original);
    sourceSamples.push({
      original,
      process: await processMemory(browserSession),
      native: await nativeMemory(browserSession),
    });
  }
  if (errors.length) throw new Error('Synthetic browser emitted an error or crashed');
  const report = {
    profile: values.profile,
    navigations: steps,
    browser: browser.version,
    node: process.version,
    networkRecording: values['record-network'],
    seconds: (performance.now() - started) / 1000,
    requests: fixture.requests,
    requestsBeforeInspection,
    samples,
    sourceSamples,
    notes: [
      values.profile === 'control'
        ? 'Image-only negative control; no application code or live database.'
        : 'Compiled application with synthetic navigation adapter; no live database.',
      'Loopback HTTPS raster server; HTTP cache enabled.',
      values['record-network']
        ? 'Diagnostic network recording enabled; response retention is included.'
        : 'Network recording disabled; browser HTTP/decoded caches are not disabled or cleared.',
      'RSS sums shared mappings; PSS accounts proportionally for sharing.',
      'Native allocator entries can overlap; do not sum parent/child entries.',
      mobile
        ? 'Emulated mobile with 64 MiB V8 old-space limit and simulated critical pressure, not a physical low-RAM phone.'
        : 'Desktop, no simulated memory pressure.',
    ],
  };
  const validation =
    steps === 1000
      ? evaluateSoak(report)
      : { passed: false, issues: ['Pilot only: fewer than 1,000 navigations'] };
  if (values.output)
    writeFileSync(values.output, JSON.stringify({ ...report, validation }, null, 2) + '\n', {
      flag: 'wx',
    });
  console.log(JSON.stringify({ profile: values.profile, validation }));
  if (steps === 1000 && !values['record-network'] && !validation.passed) process.exitCode = 1;
} finally {
  await browser?.close();
  await fixture.close();
}
