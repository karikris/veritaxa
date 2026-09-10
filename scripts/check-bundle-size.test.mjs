import assert from 'node:assert/strict';
import { Buffer } from 'node:buffer';
import { randomBytes } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import process from 'node:process';
import test from 'node:test';

await test('bundle gate enforces 70 KiB gzip and rejects missing or empty builds', () => {
  const directory = mkdtempSync(join(tmpdir(), 'veritaxa-bundle-test-'));
  const script = join(import.meta.dirname, 'check-bundle-size.mjs');
  const run = () => spawnSync(process.execPath, [script], { cwd: directory, encoding: 'utf8' });
  try {
    assert.equal(run().status, 1);
    const assets = join(directory, 'dist', 'assets');
    mkdirSync(assets, { recursive: true });
    assert.equal(run().status, 1);
    // Raw size is not the policy: highly compressible JavaScript is allowed.
    writeFileSync(join(assets, 'synthetic.js'), Buffer.alloc(512 * 1024, 120));
    assert.equal(run().status, 0);
    // Incompressible bytes above 70 KiB but below the old 250 KiB threshold.
    writeFileSync(join(assets, 'synthetic.js'), randomBytes(96 * 1024));
    const failed = run();
    assert.equal(failed.status, 1);
    assert.match(failed.stderr, /70\.00 KiB gzip limit/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
