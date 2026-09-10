import { readFileSync, readdirSync } from 'node:fs';

function live<T>(read: () => T): T | undefined {
  try {
    return read();
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== 'ENOENT' && code !== 'ESRCH') throw error;
    return undefined;
  }
}

export function processFootprint(
  pid: number,
  read = (path: string) => readFileSync(path, 'utf8'),
  list = (path: string) => readdirSync(path),
) {
  const path = `/proc/${String(pid)}`;
  const contents = live(() => read(`${path}/smaps_rollup`));
  if (contents === undefined) return null;
  const rss = /^Rss:\s+(\d+) kB$/m.exec(contents);
  const pss = /^Pss:\s+(\d+) kB$/m.exec(contents);
  if (!rss || !pss) throw new Error('Browser process memory was unavailable');
  const children = new Set<number>();
  // Threads may exit between listing and reading. Losing one thread must not
  // discard the successfully read memory of its still-live parent process.
  for (const tid of live(() => list(`${path}/task`)) ?? []) {
    const childList = live(() => read(`${path}/task/${tid}/children`)) ?? '';
    for (const child of childList.split(/\s+/).filter(Boolean)) {
      if (!/^\d+$/.test(child) || Number(child) < 1) throw new Error('Invalid browser child PID');
      children.add(Number(child));
    }
  }
  return { rssMiB: Number(rss[1]) / 1024, pssMiB: Number(pss[1]) / 1024, children };
}
