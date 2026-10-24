import { closeSync, mkdtempSync, openSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { PLATEAU_LIMITS } from './browser_gates.ts';
import { runWorker, workerEvidence } from './browser_worker.ts';

const { values } = parseArgs({ options: { output: { type: 'string' } } });
if (!values.output || process.platform !== 'linux') throw new Error('Supply --output on Linux');
const descriptor = openSync(values.output, 'wx', 0o600);
const directory = mkdtempSync(join(tmpdir(), 'veritaxa-browser-suite-'));
const runs: unknown[] = [];
const failures: string[] = [];
const workerFailures: unknown[] = [];
try {
  profiles: for (const profile of ['desktop', 'drafts', 'mobile-pressure']) {
    for (let repeat = 1; repeat <= 3; repeat += 1) {
      const output = join(directory, `${profile}-${String(repeat)}.json`);
      const exit = await runWorker(
        process.execPath,
        [join(import.meta.dirname, 'browser_memory.js'), '--profile', profile, '--output', output],
        { ...process.env, VERITAXA_BROWSER_TMP: directory },
      );
      const evidence = workerEvidence(output, profile, exit);
      if (evidence.report && evidence.validation)
        runs.push({ repeat, report: evidence.report, validation: evidence.validation });
      if (evidence.failure) {
        failures.push(`${profile} repeat ${String(repeat)}: ${evidence.failure.message}`);
        workerFailures.push({
          profile,
          repeat,
          ...evidence.failure,
          report: evidence.report,
          validation: evidence.validation,
        });
        break profiles;
      }
    }
  }
} catch (error) {
  failures.push(error instanceof Error ? error.message : 'Browser suite failed');
} finally {
  const passed = runs.length === 9 && failures.length === 0;
  try {
    writeFileSync(
      descriptor,
      JSON.stringify({ passed, failures, limits: PLATEAU_LIMITS, runs, workerFailures }, null, 2) +
        '\n',
    );
  } finally {
    closeSync(descriptor);
    rmSync(directory, { recursive: true, force: true });
  }
  console.log(JSON.stringify({ passed, runs: runs.length, failures }));
  if (!passed) process.exitCode = 1;
}
