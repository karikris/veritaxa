import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, relative, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import console from 'node:console';
import process from 'node:process';

const root = process.cwd();
const self = 'scripts/check-no-review-data.mjs';
/** @type {readonly (readonly [string, string])[]} */
const forbidden = [
  ['Flickr photo page', 'flickr.com' + '/photos'],
  ['real campaign filename', 'papilio' + '_demoleus_candidates'],
];
// A provider hostname used by URL policy code is public configuration, not task
// data. Continue rejecting every literal source path, including escaped URLs.
const sourceImagePattern = new RegExp(
  'static' + String.raw`flickr\.com\.?(?::\d+)?(?:/|\\/|%2f)`,
  'i',
);
const postgresPattern = new RegExp('postgres(?:ql)?' + String.raw`:\/\/[^\s"']+`, 'i');
const supabaseSecretPattern = new RegExp(
  String.raw`\bsb_` + String.raw`secret_[a-z0-9_-]{20,}`,
  'i',
);
const serviceRoleJwtPayloadPattern = new RegExp('eyJyb2xlIjoic2VydmljZV9yb2xl', 'i');
const textExtensions = new Set([
  '',
  '.css',
  '.html',
  '.js',
  '.json',
  '.md',
  '.mjs',
  '.py',
  '.sql',
  '.svg',
  '.toml',
  '.ts',
  '.txt',
  '.yaml',
  '.yml',
]);

const trackedResult = spawnSync('git', ['ls-files', '-z'], {
  cwd: root,
  encoding: 'utf8',
});
if (trackedResult.status !== 0) {
  console.error('Could not enumerate tracked files.');
  process.exit(1);
}

const trackedOutput = /** @type {string} */ (trackedResult.stdout);
/** @type {string[]} */
const tracked = trackedOutput.split('\0').filter(Boolean);
/** @type {string[]} */
const built = exists(resolve(root, 'dist')) ? walk(resolve(root, 'dist')) : [];
const files = [...new Set([...tracked, ...built.map((path) => relative(root, path))])];
/** @type {string[]} */
const findings = [];

for (const path of files) {
  const normalised = path.replaceAll('\\', '/');
  const basename = normalised.split('/').at(-1) ?? '';
  if (basename === '.env' || (basename.startsWith('.env.') && !basename.endsWith('.example'))) {
    findings.push(`${normalised}: tracked environment file`);
  }
  if (
    extname(normalised).toLowerCase() === '.parquet' &&
    !normalised.startsWith('tests/fixtures/synthetic-only/')
  ) {
    findings.push(`${normalised}: Parquet file outside the synthetic fixture path`);
  }
  if (normalised === self || !textExtensions.has(extname(normalised).toLowerCase())) continue;
  /** @type {string} */
  let contents;
  try {
    contents = readFileSync(resolve(root, normalised), 'utf8').toLowerCase();
  } catch {
    findings.push(`${normalised}: could not be inspected`);
    continue;
  }
  for (const [label, value] of forbidden) {
    if (contents.includes(value.toLowerCase())) findings.push(`${normalised}: ${label}`);
  }
  if (sourceImagePattern.test(contents)) findings.push(`${normalised}: Flickr static image URL`);
  if (supabaseSecretPattern.test(contents)) {
    findings.push(`${normalised}: Supabase secret key`);
  }
  if (serviceRoleJwtPayloadPattern.test(contents)) {
    findings.push(`${normalised}: service-role JWT`);
  }
  if (postgresPattern.test(contents)) findings.push(`${normalised}: direct Postgres URL`);
}

if (findings.length > 0) {
  console.error('Review-data scan failed:');
  for (const finding of findings) console.error(`- ${finding}`);
  process.exit(1);
}

console.log(`Review-data scan passed: ${String(files.length)} files inspected.`);

/**
 * @param {string} directory
 * @returns {string[]}
 */
function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

/** @param {string} path */
function exists(path) {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}
