import assert from 'node:assert/strict';
import test from 'node:test';
import { CdpSession } from './browser_cdp.ts';
import { nativeMemory, NativeMemoryError, type DumpAttempt } from './browser_native.ts';
import { evaluateSoak, type SoakReport } from './browser_gates.ts';

const context = { profile: 'desktop', navigation: 500, phase: 'navigation' };
const sizes = { 'cc/image_memory': '100', 'gpu/shared_images': '10', partition_alloc: '20' };
type Scenario = {
  success?: unknown;
  dumpGuid?: unknown;
  malformedTrace?: boolean;
  dataLoss?: unknown;
  sizes?: Record<string, string>;
  noDumps?: boolean;
  noComplete?: boolean;
  requestError?: string;
  endError?: string;
  startError?: string;
  badUnits?: boolean;
  groupingNodes?: boolean;
};
function fake(scenarios: Scenario[]) {
  const calls: string[] = [];
  let attempt = -1;
  const session = new CdpSession((method) => {
    calls.push(method);
    if (method === 'Tracing.start') attempt++;
    const scenario = scenarios[Math.min(attempt, scenarios.length - 1)];
    if (method === 'Tracing.start' && scenario.startError)
      return Promise.reject(new Error(scenario.startError));
    if (method === 'Tracing.requestMemoryDump') {
      if (scenario.requestError) return Promise.reject(new Error(scenario.requestError));
      return Promise.resolve({
        success: 'success' in scenario ? scenario.success : true,
        dumpGuid: 'dumpGuid' in scenario ? scenario.dumpGuid : '0x42',
      });
    }
    if (method === 'Tracing.end') {
      if (scenario.malformedTrace) session.emit('Tracing.dataCollected', { value: null });
      if (scenario.endError) return Promise.reject(new Error(scenario.endError));
      if (scenario.groupingNodes)
        session.emit('Tracing.dataCollected', {
          value: [{ args: { dumps: { allocators: { partition_alloc: { attrs: {} } } } } }],
        });
      if (!scenario.noDumps)
        session.emit('Tracing.dataCollected', {
          value: [
            {
              args: {
                dumps: {
                  allocators: Object.fromEntries(
                    Object.entries(scenario.sizes ?? sizes).map(([name, value]) => [
                      name,
                      {
                        attrs: { size: { value, units: scenario.badUnits ? 'objects' : 'bytes' } },
                      },
                    ]),
                  ),
                },
              },
            },
          ],
        });
      if (!scenario.noComplete)
        session.emit('Tracing.tracingComplete', {
          dataLossOccurred: 'dataLoss' in scenario ? scenario.dataLoss : false,
        });
    }
    return Promise.resolve({});
  });
  return { session, calls };
}
function observers() {
  const attempts: DumpAttempt[] = [];
  const delays: number[] = [];
  return {
    attempts,
    delays,
    timeoutMs: 5,
    onAttempt(value: DumpAttempt) {
      attempts.push(structuredClone(value));
    },
    delay(ms: number) {
      delays.push(ms);
      return Promise.resolve();
    },
  };
}
function noListeners(session: CdpSession) {
  assert.equal(session.listenerCount('Tracing.dataCollected'), 0);
  assert.equal(session.listenerCount('Tracing.tracingComplete'), 0);
}

await test('complete trace accepts zero metrics, records context, and clears listeners', async () => {
  const { session, calls } = fake([
    { sizes: Object.fromEntries(Object.keys(sizes).map((name) => [name, '0'])) },
  ]);
  const options = observers();
  const result = await nativeMemory(session, context, options);
  assert.equal(result.allocators['cc/image_memory'], 0);
  assert.equal(result.dumps, 1);
  assert.deepEqual(calls, ['Tracing.start', 'Tracing.requestMemoryDump', 'Tracing.end']);
  assert.equal(options.attempts.at(-1)?.dumpGuid, '0x42');
  assert.equal(options.attempts.at(-1)?.navigation, 500);
  assert.equal(options.attempts.at(-1)?.phase, 'navigation');
  assert.deepEqual(options.attempts.at(-1)?.conditions, []);
  noListeners(session);
});

for (const [condition, scenario] of Object.entries({
  request_failed: { success: false },
  trace_data_loss: { dataLoss: true },
  no_allocator_dumps: { noDumps: true },
  missing_allocator: { sizes: { 'cc/image_memory': '100' } },
})) {
  await test(`${condition} retries one fresh trace after 250 ms and retains evidence`, async () => {
    const { session, calls } = fake([scenario, {}]);
    const options = observers();
    const result = await nativeMemory(session, context, options);
    assert.equal(result.allocators['cc/image_memory'], 256); // Never sums attempts.
    assert.equal(calls.filter((method) => method === 'Tracing.start').length, 2);
    assert.deepEqual(options.delays, [250]);
    assert.ok(options.attempts[1].conditions.includes(condition));
    assert.equal(options.attempts.at(-1)?.attempt, 2);
    assert.deepEqual(options.attempts.at(-1)?.conditions, []);
    noListeners(session);
  });
  await test(`persistent ${condition} fails after exactly two attempts`, async () => {
    const { session, calls } = fake([scenario]);
    await assert.rejects(
      nativeMemory(session, context, observers()),
      (error: unknown) =>
        error instanceof NativeMemoryError &&
        error.diagnostic.conditions.includes(condition) &&
        error.diagnostic.attempt === 2,
    );
    assert.equal(calls.filter((method) => method === 'Tracing.start').length, 2);
    noListeners(session);
  });
}

for (const [condition, scenario] of Object.entries({
  malformed_response: { success: undefined },
  invalid_allocator: { sizes: { ...sizes, partition_alloc: '12g' } },
  trace_timeout: { noComplete: true },
  cdp_timeout: { requestError: 'Tracing.requestMemoryDump timed out' },
  cdp_error: { requestError: 'Browser connection closed' },
})) {
  await test(`${condition} fails without retry and keeps original details`, async () => {
    const { session, calls } = fake([scenario]);
    const options = observers();
    await assert.rejects(
      nativeMemory(session, context, options),
      (error: unknown) =>
        error instanceof NativeMemoryError && error.diagnostic.conditions.includes(condition),
    );
    assert.equal(calls.filter((method) => method === 'Tracing.start').length, 1);
    assert.deepEqual(options.delays, []);
    noListeners(session);
  });
}

await test('missing completion flag, invalid units, negative and overflowing metrics fail closed', async () => {
  for (const scenario of [
    { dataLoss: undefined },
    { badUnits: true },
    { sizes: { ...sizes, partition_alloc: '-1' } },
    { sizes: { ...sizes, partition_alloc: 'fffffffffffffffff' } },
  ]) {
    const { session, calls } = fake([scenario]);
    await assert.rejects(nativeMemory(session, context, observers()), NativeMemoryError);
    assert.equal(calls.filter((method) => method === 'Tracing.start').length, 1);
    noListeners(session);
  }
});

await test('cleanup failure cannot replace the original request error', async () => {
  const { session } = fake([
    { requestError: 'original transport error', endError: 'cleanup failed' },
  ]);
  await assert.rejects(
    nativeMemory(session, context, observers()),
    (error: unknown) =>
      error instanceof NativeMemoryError &&
      error.diagnostic.error === 'original transport error' &&
      error.diagnostic.cleanupErrors.some((text) => text.includes('cleanup failed')),
  );
  noListeners(session);
});

await test('a crashed page prevents retry of an otherwise recoverable dump', async () => {
  const { session, calls } = fake([{ success: false }]);
  const options = observers();
  await assert.rejects(
    nativeMemory(session, context, {
      ...options,
      checkHealth() {
        if (calls.length) throw new Error('page crashed');
      },
    }),
    /page crashed/,
  );
  assert.equal(calls.filter((method) => method === 'Tracing.start').length, 1);
});

await test('growth detected after a valid dump does not trigger another measurement', async () => {
  const { session, calls } = fake([{}]);
  const native = await nativeMemory(session, context, observers());
  const report: SoakReport = {
    profile: 'desktop',
    navigations: 1000,
    networkRecording: false,
    requests: { preview: 1000, original: 1 },
    requestsBeforeInspection: { preview: 1000, original: 0 },
    sourceSamples: [{ original: true }, { original: false }],
    samples: Array.from({ length: 11 }, (_, i) => ({
      navigation: i * 100,
      heapBeforeGC: 1,
      heapAfterGC: 1,
      discardedDrafts: 0,
      dom: { nodes: 10, documents: 1, jsEventListeners: 3 },
      process: { rssMiB: 100 + i * 100, pssMiB: 100 + i * 100 },
      processBeforeGC: { rssMiB: 100, pssMiB: 100 },
      native,
    })),
  };
  assert.equal(evaluateSoak(report).passed, false);
  assert.equal(calls.filter((method) => method === 'Tracing.start').length, 1);
});

await test('hierarchy-only parent nodes do not invalidate measured totals from other dumps', async () => {
  const { session } = fake([{ groupingNodes: true }]);
  const result = await nativeMemory(session, context, observers());
  assert.equal(result.allocators.partition_alloc, 32);
  assert.equal(result.dumps, 2);
});

await test('start and end command failures remove listeners and never retry', async () => {
  for (const scenario of [
    { startError: 'Browser connection closed' },
    { endError: 'Tracing.end rejected' },
  ]) {
    const { session, calls } = fake([scenario]);
    await assert.rejects(
      nativeMemory(session, context, observers()),
      (error: unknown) =>
        error instanceof NativeMemoryError && error.diagnostic.conditions.includes('cdp_error'),
    );
    assert.equal(calls.filter((method) => method === 'Tracing.start').length, 1);
    noListeners(session);
  }
});

await test('malformed event payloads and missing dump identifiers fail without retry', async () => {
  for (const [scenario, condition] of [
    [{ malformedTrace: true }, 'malformed_trace'],
    [{ dumpGuid: undefined }, 'malformed_response'],
  ] as const) {
    const { session, calls } = fake([scenario]);
    await assert.rejects(
      nativeMemory(session, context, observers()),
      (error: unknown) =>
        error instanceof NativeMemoryError && error.diagnostic.conditions.includes(condition),
    );
    assert.equal(calls.filter((method) => method === 'Tracing.start').length, 1);
    noListeners(session);
  }
});

await test('events delivered after the end response are retained until tracingComplete', async () => {
  const session = new CdpSession((method) => {
    if (method === 'Tracing.requestMemoryDump')
      return Promise.resolve({ success: true, dumpGuid: '0x43' });
    if (method === 'Tracing.end')
      setTimeout(() => {
        for (const [name, value] of Object.entries(sizes))
          session.emit('Tracing.dataCollected', {
            value: [
              {
                args: {
                  dumps: { allocators: { [name]: { attrs: { size: { value, units: 'bytes' } } } } },
                },
              },
            ],
          });
        session.emit('Tracing.tracingComplete', { dataLossOccurred: false });
      }, 1);
    return Promise.resolve({});
  });
  const result = await nativeMemory(session, context, { ...observers(), timeoutMs: 100 });
  assert.equal(result.dumps, 3);
  assert.equal(result.allocators.partition_alloc, 32);
  noListeners(session);
});
