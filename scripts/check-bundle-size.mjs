import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { gzipSync } from 'node:zlib';
import console from 'node:console';
import process from 'node:process';

const limit = 70 * 1024;
const assets = resolve(process.cwd(), 'dist', 'assets');
let files;
try {
  files = readdirSync(assets).filter((file) => file.endsWith('.js'));
} catch {
  console.error('Bundle-size check requires a completed production build.');
  process.exit(1);
}
if (!files.length) {
  console.error('Bundle-size check requires at least one production JavaScript asset.');
  process.exit(1);
}

const rawBytes = files.reduce(
  (total, file) => total + readFileSync(resolve(assets, file)).length,
  0,
);
const gzipBytes = files.reduce(
  (total, file) => total + gzipSync(readFileSync(resolve(assets, file))).length,
  0,
);
/** @param {number} bytes */
const format = (bytes) => `${(bytes / 1024).toFixed(2)} KiB`;

console.log(`JavaScript bundle: raw=${format(rawBytes)} gzip=${format(gzipBytes)}`);
if (gzipBytes > limit) {
  console.error(`Bundle exceeds the ${format(limit)} gzip limit.`);
  process.exit(1);
}
