import assert from 'node:assert/strict';
import test from 'node:test';
import { evaluateSoak, type SoakReport } from './browser_gates.ts';
import { CdpSession, record } from './browser_cdp.ts';
import { processFootprint } from './browser_proc.ts';

function report(profile = 'desktop'): SoakReport {
  return {
    profile,
    navigations: 1000,
    networkRecording: false,
    requestsBeforeInspection: { preview: 1000, original: 0 },
    requests: { preview: 1000, original: 1 },
    sourceSamples: [{ original: true }, { original: false }],
    samples: Array.from({ length: 11 }, (_, i) => ({
      navigation: i * 100,
      heapBeforeGC: 3,
      heapAfterGC: 1,
      discardedDrafts: profile === 'desktop' ? 0 : Math.max(0, i * 100 - 255),
      dom: { documents: 1, nodes: 300, jsEventListeners: 30 },
      process: { rssMiB: 600, pssMiB: 400 },
      processBeforeGC: { rssMiB: 605, pssMiB: 405 },
      native: {
        allocators: {
          'cc/image_memory': 128 * 1024 ** 2,
          'gpu/shared_images': 8 * 1024 ** 2,
          partition_alloc: 4 * 1024 ** 2,
        },
      },
    })),
  };
}

await test('steady memory passes with bounded, deliberately resolved drafts', () => {
  for (const profile of ['desktop', 'drafts', 'mobile-pressure'])
    assert.equal(evaluateSoak(report(profile)).passed, true);
});
await test('growth cannot hide behind stable JS or a low final checkpoint', () => {
  const growing = report();
  for (const sample of growing.samples) {
    sample.process.pssMiB += sample.navigation / 2;
    sample.native.allocators.partition_alloc += sample.navigation * 100_000;
  }
  growing.samples[10].process.pssMiB = 400;
  const result = evaluateSoak(growing);
  assert.equal(result.passed, false);
  assert.ok(result.issues.some((issue) => issue.startsWith('pssMiB')));
  assert.ok(result.issues.some((issue) => issue.startsWith('partitionMiB')));
});
await test('missing checkpoints, metrics and nonfinite values fail closed', () => {
  const short = report();
  short.samples.pop();
  assert.throws(() => evaluateSoak(short), /checkpoints/);
  const absent = report();
  delete absent.samples[4].native.allocators['cc/image_memory'];
  assert.throws(() => evaluateSoak(absent), /missing/);
  const nan = report();
  nan.samples[4].heapAfterGC = NaN;
  assert.throws(() => evaluateSoak(nan), /nonfinite/);
});
await test('DOM leaks, missing draft pressure, automatic originals and disabled caching fail', () => {
  const bad = report('drafts');
  bad.samples[5].dom.nodes = 301;
  bad.samples[10].discardedDrafts = 0;
  bad.requestsBeforeInspection.original = 1;
  bad.requests.preview += 1;
  bad.networkRecording = true;
  const result = evaluateSoak(bad);
  for (const marker of ['DOM', 'capacity', 'source', 'cached', 'Network'])
    assert.ok(result.issues.some((issue) => issue.includes(marker)));
});

await test('direct evaluation propagates browser exceptions and requests by-value results', async () => {
  const calls: string[] = [];
  const session = new CdpSession((method, params) => {
    calls.push(method);
    assert.ok(params);
    assert.equal(params.returnByValue, true);
    assert.equal(params.awaitPromise, true);
    assert.equal(params.timeout, 30_000);
    return Promise.resolve({ result: { value: 42 } });
  });
  assert.equal(await session.evaluate((value) => value + 1, 41), 42);
  assert.deepEqual(calls, ['Runtime.evaluate']);
  const failed = new CdpSession(() =>
    Promise.resolve({ exceptionDetails: { text: 'Synthetic failure' } }),
  );
  await assert.rejects(
    failed.evaluate((value) => value, 1),
    /Synthetic failure/,
  );
  for (const value of [undefined, null, 1, 'text', []]) assert.deepEqual(record(value), {});
});

await test('a closing thread cannot erase its live parent from process measurements', () => {
  const result = processFootprint(
    42,
    (path) => {
      if (path.endsWith('/smaps_rollup')) return 'Rss: 2048 kB\nPss: 1024 kB\n';
      if (path.endsWith('/42/children')) return '99 100';
      throw Object.assign(new Error('Synthetic thread exited'), { code: 'ENOENT' });
    },
    () => ['42', '43'],
  );
  assert.ok(result);
  assert.equal(result.rssMiB, 2);
  assert.equal(result.pssMiB, 1);
  assert.deepEqual([...result.children], [99, 100]);
  assert.equal(
    processFootprint(42, () => {
      throw Object.assign(new Error(), { code: 'ESRCH' });
    }),
    null,
  );
  assert.throws(
    () =>
      processFootprint(42, () => {
        throw Object.assign(new Error(), { code: 'EACCES' });
      }),
    /Error/,
  );
  assert.throws(() => processFootprint(42, () => 'Rss: missing'), /unavailable/);
});
