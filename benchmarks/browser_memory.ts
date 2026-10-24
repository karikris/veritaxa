import { writeFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { createBrowserFixture } from './browser_fixture.ts';
import { startBrowser, record, type CdpSession } from './browser_cdp.ts';
import { evaluateSoak } from './browser_gates.ts';
import { processFootprint } from './browser_proc.ts';
import { nativeMemory, type DumpAttempt } from './browser_native.ts';
import { ProgressFile } from './browser_worker.ts';

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

const progress = {
  profile: values.profile,
  navigations: steps,
  currentNavigation: 0,
  lastCheckpoint: null as number | null,
  phase: 'fixture',
  samples: [] as unknown[],
  sourceSamples: [] as unknown[],
  measurementAttempts: [] as DumpAttempt[],
  failure: null as { name: string; message: string; stack?: string } | null,
  cleanupErrors: [] as string[],
};
const journal = values.output ? new ProgressFile(`${values.output}.progress.json`) : undefined;
const checkpoint = () => journal?.write(progress);
checkpoint();
let fixture: Awaited<ReturnType<typeof createBrowserFixture>> | undefined;
let browser: Awaited<ReturnType<typeof startBrowser>> | undefined;
try {
  fixture = await createBrowserFixture(values.profile === 'control');
  progress.phase = 'browser-start';
  checkpoint();
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
  const measure = () =>
    nativeMemory(
      browserSession,
      {
        profile: values.profile,
        navigation: progress.currentNavigation,
        phase: progress.phase,
      },
      {
        checkHealth() {
          if (errors.length) throw new Error('Synthetic browser emitted an error or crashed');
        },
        onAttempt(attempt) {
          const index = progress.measurementAttempts.findIndex(
            (entry) =>
              entry.phase === attempt.phase &&
              entry.navigation === attempt.navigation &&
              entry.attempt === attempt.attempt,
          );
          if (index < 0) progress.measurementAttempts.push(attempt);
          else progress.measurementAttempts[index] = attempt;
          checkpoint();
        },
      },
    );
  let discardedDrafts = 0;
  const navigationResult = await page.send('Page.navigate', { url: fixture.url });
  if (navigationResult.errorText) throw new Error('Synthetic fixture navigation failed');
  await paintedImage(page, 1);
  const started = performance.now();
  progress.phase = 'navigation';
  for (let navigation = 0; navigation <= steps; navigation += 1) {
    progress.currentNavigation = navigation;
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
      native: await measure(),
    };
    samples.push(sample);
    progress.samples.push(sample);
    progress.lastCheckpoint = navigation;
    checkpoint();
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
    progress.phase = original ? 'source-inspection' : 'return-to-preview';
    checkpoint();
    await page.evaluate(() => {
      const control = document.querySelector<HTMLButtonElement>('.image-source-button');
      if (!control || control.disabled) throw new Error('Source inspection is unavailable');
      control.click();
    }, undefined);
    await paintedImage(page, (steps % 1000) + 1, original);
    const sourceSample = {
      original,
      process: await processMemory(browserSession),
      native: await measure(),
    };
    sourceSamples.push(sourceSample);
    progress.sourceSamples.push(sourceSample);
    checkpoint();
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
    measurementAttempts: progress.measurementAttempts,
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
      mode: 0o600,
    });
  console.log(JSON.stringify({ profile: values.profile, validation }));
  if (steps === 1000 && !values['record-network'] && !validation.passed) process.exitCode = 1;
} catch (error) {
  progress.failure =
    error instanceof Error
      ? { name: error.name, message: error.message, stack: error.stack }
      : { name: 'Error', message: String(error) };
  checkpoint();
  console.error(progress.failure.stack ?? progress.failure.message);
  process.exitCode = 1;
} finally {
  for (const [name, close] of [
    ['browser', () => browser?.close()],
    ['fixture', () => fixture?.close()],
  ] as const) {
    try {
      await close();
    } catch (error) {
      progress.cleanupErrors.push(
        `${name}: ${error instanceof Error ? error.message : String(error)}`,
      );
      process.exitCode = 1;
    }
  }
  checkpoint();
}
