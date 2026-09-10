import { spawn } from 'node:child_process';
import { closeSync, mkdtempSync, openSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { evaluateSoak, PLATEAU_LIMITS, type SoakReport } from './browser_gates.ts';

const { values } = parseArgs({ options: { output: { type: 'string' } } });
if (!values.output || process.platform !== 'linux') throw new Error('Supply --output on Linux');
const descriptor = openSync(values.output, 'wx', 0o600);
const directory = mkdtempSync(join(tmpdir(), 'veritaxa-browser-suite-'));
const runs: unknown[] = [];
const failures: string[] = [];
try {
  for (const profile of ['desktop', 'drafts', 'mobile-pressure']) {
    for (let repeat = 1; repeat <= 3; repeat += 1) {
      const output = join(directory, `${profile}-${String(repeat)}.json`);
      const code = await new Promise<number>((resolve, reject) => {
        const child = spawn(
          process.execPath,
          [
            join(import.meta.dirname, 'browser_memory.js'),
            '--profile',
            profile,
            '--output',
            output,
          ],
          {
            stdio: 'inherit',
            detached: true,
            env: { ...process.env, VERITAXA_BROWSER_TMP: directory },
          },
        );
        // This is an exclusively owned process group, including its Chromium
        // children. Stop the entire group if a probe exceeds its deadline.
        const stop = () => {
          if (!child.pid) return;
          try {
            process.kill(-child.pid, 'SIGKILL');
          } catch (error) {
            if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
          }
        };
        const timer = setTimeout(stop, 180_000);
        child.once('error', (error) => {
          clearTimeout(timer);
          stop();
          reject(error);
        });
        child.once('exit', (exitCode) => {
          clearTimeout(timer);
          stop();
          resolve(exitCode ?? 1);
        });
      });
      const raw: unknown = JSON.parse(readFileSync(output, 'utf8'));
      const report = raw as SoakReport;
      const validation = evaluateSoak(report);
      if (report.profile !== profile || code !== 0 || !validation.passed)
        failures.push(`${profile} repeat ${String(repeat)} failed`);
      runs.push({ repeat, report, validation });
    }
  }
} catch (error) {
  failures.push(error instanceof Error ? error.message : 'Browser suite failed');
} finally {
  const passed = runs.length === 9 && failures.length === 0;
  writeFileSync(
    descriptor,
    JSON.stringify({ passed, failures, limits: PLATEAU_LIMITS, runs }, null, 2) + '\n',
  );
  closeSync(descriptor);
  rmSync(directory, { recursive: true, force: true });
  console.log(JSON.stringify({ passed, runs: runs.length, failures }));
  if (!passed) process.exitCode = 1;
}
