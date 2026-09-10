import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import process from 'node:process';
import { test } from 'node:test';
import assert from 'node:assert/strict';

await test('provider configuration is allowed while source paths and private markers remain blocked', () => {
  const directory = mkdtempSync(join(tmpdir(), 'veritaxa-data-scan-'));
  const script = fileURLToPath(new URL('./check-no-review-data.mjs', import.meta.url));
  const domain = 'staticflickr.com';
  /** @type {readonly (readonly [string, string, number])[]} */
  const cases = [
    ['provider hostname', `const domain = '${domain}';`, 0],
    ['synthetic image host', 'https://images.example.invalid/preview.png', 0],
    ['literal source path', 'https://live.' + domain + '/1/1_0000000000_b.jpg', 1],
    ['bare source path', domain + '/1/1_0000000000_b.jpg', 1],
    ['source path with port', domain + ':443/1/1_0000000000_b.jpg', 1],
    ['escaped source path', domain + String.raw`\/1\/1_0000000000_b.jpg`, 1],
    ['encoded source path', domain.toUpperCase() + '%2F1%2F1_0000000000_b.jpg', 1],
    ['source page', ['flickr.com', 'photos', 'synthetic'].join('/'), 1],
    ['private campaign', 'papilio' + '_demoleus_candidates', 1],
    ['secret key', 'sb_' + 'secret_' + 'x'.repeat(30), 1],
    ['database URL', 'postgres' + 'ql://synthetic.invalid/synthetic', 1],
  ];
  try {
    assert.equal(spawnSync('git', ['init', '-q', directory]).status, 0);
    writeFileSync(join(directory, 'synthetic.txt'), '');
    assert.equal(spawnSync('git', ['add', 'synthetic.txt'], { cwd: directory }).status, 0);
    for (const [label, contents, status] of cases) {
      writeFileSync(join(directory, 'synthetic.txt'), contents);
      const result = spawnSync(process.execPath, [script], { cwd: directory, encoding: 'utf8' });
      assert.equal(result.status, status, label);
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
