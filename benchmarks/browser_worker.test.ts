import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ProgressFile, runWorker, workerEvidence } from './browser_worker.ts';

function temporary() {
  const directory = mkdtempSync(join(tmpdir(), 'veritaxa-worker-test-'));
  return {
    output: join(directory, 'report.json'),
    close() {
      rmSync(directory, { recursive: true, force: true });
    },
  };
}
const progress = {
  profile: 'desktop',
  currentNavigation: 500,
  lastCheckpoint: 400,
  samples: [{ navigation: 400 }],
  measurementAttempts: [{ attempt: 2, conditions: ['request_failed'] }],
  failure: {
    name: 'NativeMemoryError',
    message: 'Native memory measurement failed: request_failed',
  },
};

await test('progress files are private, replace atomically, and reject reuse', () => {
  const fixture = temporary();
  try {
    const journal = new ProgressFile(`${fixture.output}.progress.json`);
    journal.write({ lastCheckpoint: 300 });
    journal.write(progress);
    assert.deepEqual(JSON.parse(readFileSync(journal.path, 'utf8')), progress);
    assert.equal(statSync(journal.path).mode & 0o777, 0o600);
    assert.throws(() => new ProgressFile(journal.path), /EEXIST/);
  } finally {
    fixture.close();
  }
});

await test('a failed worker preserves its original error and partial samples without a final report', async () => {
  const fixture = temporary();
  try {
    new ProgressFile(`${fixture.output}.progress.json`).write(progress);
    const exit = await runWorker(process.execPath, ['-e', 'process.exit(17)'], process.env);
    const evidence = workerEvidence(fixture.output, 'desktop', exit);
    assert.ok(evidence.failure);
    assert.equal(evidence.failure.message, progress.failure.message);
    assert.equal(evidence.failure.exitCode, 17);
    assert.deepEqual(evidence.failure.progress, progress);
    assert.match(evidence.failure.reportError ?? '', /ENOENT/);
  } finally {
    fixture.close();
  }
});

await test('a worker without a journal still preserves bounded stderr as its cause', async () => {
  const fixture = temporary();
  try {
    const exit = await runWorker(
      process.execPath,
      ['-e', 'console.error("synthetic worker failure"); process.exit(2)'],
      process.env,
    );
    assert.match(
      workerEvidence(fixture.output, 'desktop', exit).failure?.message ?? '',
      /synthetic worker failure/,
    );
  } finally {
    fixture.close();
  }
});

await test('successful exits with absent, corrupt, or incomplete reports fail closed', async () => {
  const fixture = temporary();
  try {
    const exit = await runWorker(process.execPath, ['-e', 'process.exit(0)'], process.env);
    assert.match(
      workerEvidence(fixture.output, 'desktop', exit).failure?.message ?? '',
      /report unavailable/,
    );
    writeFileSync(fixture.output, '{bad json');
    assert.match(
      workerEvidence(fixture.output, 'desktop', exit).failure?.message ?? '',
      /report unavailable/,
    );
    writeFileSync(
      fixture.output,
      JSON.stringify({ profile: 'desktop', samples: [], navigations: 1000 }),
    );
    assert.match(
      workerEvidence(fixture.output, 'desktop', exit).failure?.message ?? '',
      /checkpoints/,
    );
  } finally {
    fixture.close();
  }
});

await test('signal termination records the signal and retains progress', async () => {
  const fixture = temporary();
  try {
    new ProgressFile(`${fixture.output}.progress.json`).write(progress);
    const exit = await runWorker(
      process.execPath,
      ['-e', 'process.kill(process.pid, "SIGTERM")'],
      process.env,
    );
    const failure = workerEvidence(fixture.output, 'desktop', exit).failure;
    assert.ok(failure);
    assert.equal(failure.signal, 'SIGTERM');
    assert.match(failure.message, /SIGTERM/);
    assert.deepEqual(failure.progress, progress);
  } finally {
    fixture.close();
  }
});

await test('deadline terminates the owned process group and keeps the checkpoint', async () => {
  const fixture = temporary();
  try {
    new ProgressFile(`${fixture.output}.progress.json`).write(progress);
    const exit = await runWorker(
      process.execPath,
      ['-e', 'setInterval(() => {}, 1000)'],
      process.env,
      100,
    );
    const failure = workerEvidence(fixture.output, 'desktop', exit).failure;
    assert.ok(failure);
    assert.equal(failure.timedOut, true);
    assert.equal(failure.signal, 'SIGKILL');
    assert.match(failure.message, /deadline/);
    assert.deepEqual(failure.progress, progress);
  } finally {
    fixture.close();
  }
});

await test('spawn failures retain the startup error instead of a missing-report exception', async () => {
  const fixture = temporary();
  try {
    const exit = await runWorker('/veritaxa-synthetic-missing-program', [], process.env);
    const failure = workerEvidence(fixture.output, 'desktop', exit).failure;
    assert.match(failure?.message ?? '', /could not start/);
    assert.ok(failure?.spawnError);
  } finally {
    fixture.close();
  }
});

await test('a nonzero exit retains completed memory-growth validation', async () => {
  const fixture = temporary();
  try {
    writeFileSync(
      fixture.output,
      JSON.stringify({
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
          dom: { documents: 1, nodes: 3, jsEventListeners: 2 },
          processBeforeGC: { rssMiB: 100, pssMiB: 100 },
          process: { rssMiB: i * 100, pssMiB: i * 100 },
          native: {
            allocators: { 'cc/image_memory': 1, 'gpu/shared_images': 1, partition_alloc: 1 },
          },
        })),
      }),
    );
    const exit = await runWorker(process.execPath, ['-e', 'process.exit(1)'], process.env);
    const evidence = workerEvidence(fixture.output, 'desktop', exit);
    assert.equal(evidence.validation?.passed, false);
    assert.match(evidence.failure?.message ?? '', /pssMiB retained growth/);
  } finally {
    fixture.close();
  }
});
