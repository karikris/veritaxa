import { spawn } from 'node:child_process';
import { openSync, closeSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { record } from './browser_cdp.ts';
import { evaluateSoak, type SoakReport } from './browser_gates.ts';

/** Reserve the destination, then replace snapshots atomically with private files. */
export class ProgressFile {
  constructor(readonly path: string) {
    closeSync(openSync(path, 'wx', 0o600));
  }
  write(value: unknown) {
    const staging = `${this.path}.${String(process.pid)}.tmp`;
    try {
      writeFileSync(staging, JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
      renameSync(staging, this.path);
    } catch (error) {
      try {
        unlinkSync(staging);
      } catch {
        /* Preserve the write/rename error. */
      }
      throw error;
    }
  }
}

export type WorkerExit = {
  exitCode: number | null;
  signal: NodeJS.Signals | null;
  timedOut: boolean;
  deadlineMs: number;
  spawnError: string | null;
  stderrTail: string;
};

export function runWorker(
  command: string,
  args: string[],
  env: NodeJS.ProcessEnv,
  timeoutMs = 180_000,
): Promise<WorkerExit> {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      detached: true,
      env,
      stdio: ['ignore', 'inherit', 'pipe'],
    });
    const result: WorkerExit = {
      exitCode: null,
      signal: null,
      timedOut: false,
      deadlineMs: timeoutMs,
      spawnError: null,
      stderrTail: '',
    };
    const stop = () => {
      if (!child.pid) return;
      try {
        process.kill(-child.pid, 'SIGKILL');
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
      }
    };
    const timer = setTimeout(() => {
      result.timedOut = true;
      stop();
    }, timeoutMs);
    child.stderr.on('data', (chunk: Buffer) => {
      process.stderr.write(chunk);
      result.stderrTail = (result.stderrTail + chunk.toString()).slice(-16_384);
    });
    child.once('error', (error) => {
      result.spawnError = error.message;
    });
    child.once('exit', (code, signal) => {
      result.exitCode = code;
      result.signal = signal;
      clearTimeout(timer);
      stop();
    });
    child.once('close', () => {
      clearTimeout(timer);
      stop();
      resolve(result);
    });
  });
}

function readJson(path: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(readFileSync(path, 'utf8')) as unknown };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

/** A missing final report is secondary evidence, never the worker's root error. */
export function workerEvidence(output: string, profile: string, exit: WorkerExit) {
  const final = readJson(output);
  const partial = readJson(`${output}.progress.json`);
  const progress = partial.value;
  const data = record(final.value);
  const original = record(record(progress).failure);
  let failure: string | undefined;
  let validation: ReturnType<typeof evaluateSoak> | undefined;
  let validationError: string | undefined;
  if (!final.error) {
    try {
      if (data.profile !== profile) throw new Error('Worker profile did not match');
      validation = evaluateSoak(data as SoakReport);
      if (!validation.passed) validationError = validation.issues.join('; ');
    } catch (error) {
      validationError = error instanceof Error ? error.message : String(error);
    }
  }
  if (exit.timedOut)
    failure = `Worker exceeded its ${String(exit.deadlineMs / 1000)}-second deadline`;
  else if (exit.spawnError) failure = `Worker could not start: ${exit.spawnError}`;
  else if (exit.signal) failure = `Worker terminated by ${exit.signal}`;
  else if (typeof original.message === 'string') failure = original.message;
  else if (exit.exitCode !== 0 || data.status === 'failed') {
    const cleanup = record(progress).cleanupErrors;
    failure =
      exit.stderrTail.trim() ||
      (Array.isArray(cleanup) ? cleanup.join('; ') : '') ||
      (validationError ?? `Worker exited with code ${String(exit.exitCode)}`);
  } else if (final.error) failure = `Worker final report unavailable: ${final.error}`;
  else failure = validationError;
  return {
    report: final.value,
    validation,
    failure: failure
      ? {
          message: failure,
          ...exit,
          reportError: final.error,
          progressError: partial.error,
          progress,
        }
      : undefined,
  };
}
