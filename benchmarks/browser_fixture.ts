import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join, sep, extname } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createServer as httpServer, type Server } from 'node:http';
import { createServer as httpsServer } from 'node:https';
import { deflateSync } from 'node:zlib';
import { build } from 'vite';

const project = process.cwd();
const crcTable = Uint32Array.from({ length: 256 }, (_, value) => {
  let crc = value;
  for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  return crc >>> 0;
});

function chunk(name: string, data = Buffer.alloc(0)): Buffer {
  const result = Buffer.alloc(data.length + 12);
  result.writeUInt32BE(data.length);
  result.write(name, 4, 4, 'ascii');
  data.copy(result, 8);
  let crc = 0xffffffff;
  for (const byte of result.subarray(4, -4)) crc = crcTable[(crc ^ byte) & 255] ^ (crc >>> 8);
  result.writeUInt32BE((crc ^ 0xffffffff) >>> 0, result.length - 4);
  return result;
}

/** Each URL receives distinct RGBA pixels, not one shared decoded bitmap. */
export function pngFactory(width: number, height: number): (ordinal: number) => Buffer {
  if (
    !Number.isInteger(width) ||
    !Number.isInteger(height) ||
    width < 1 ||
    height < 1 ||
    width > 3200 ||
    height > 3200
  )
    throw new Error('Synthetic raster dimensions are out of bounds');
  const stride = width * 4 + 1;
  const pixels = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = y * stride + 1 + x * 4;
      pixels[index] = 40 + (x % 64);
      pixels[index + 1] = 80 + (y % 64);
      pixels[index + 2] = 110;
      pixels[index + 3] = 255;
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;
  return (ordinal) => {
    if (!Number.isInteger(ordinal) || ordinal < 1 || ordinal > 1000)
      throw new Error('Synthetic raster ordinal is out of bounds');
    pixels[1] = ordinal & 255;
    pixels[2] = (ordinal >>> 8) & 255;
    return Buffer.concat([
      Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
      chunk('IHDR', header),
      chunk('IDAT', deflateSync(pixels, { level: 1 })),
      chunk('IEND'),
    ]);
  };
}

async function listen(server: Server): Promise<number> {
  await new Promise<void>((done, fail) => {
    server.once('error', fail);
    server.listen(0, '127.0.0.1', done);
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Synthetic server did not bind');
  return address.port;
}

async function close(server: Server | undefined): Promise<void> {
  if (!server) return;
  server.closeAllConnections();
  await new Promise<void>((done) => server.close(() => done()));
}

export async function createBrowserFixture(control = false) {
  const entry = control ? 'image-control' : 'long-session';
  const directory = mkdtempSync(
    join(process.env.VERITAXA_BROWSER_TMP ?? tmpdir(), 'veritaxa-browser-fixture-'),
  );
  const output = join(directory, 'built');
  let assets: Server | undefined;
  let images: Server | undefined;
  const requests = { preview: 0, original: 0 };
  try {
    // Disposable private test key; never print, copy into build output or commit it.
    execFileSync(
      'openssl',
      [
        'req',
        '-x509',
        '-newkey',
        'rsa:2048',
        '-nodes',
        '-days',
        '1',
        '-subj',
        '/CN=127.0.0.1',
        '-addext',
        'subjectAltName=IP:127.0.0.1',
        '-keyout',
        join(directory, 'key.pem'),
        '-out',
        join(directory, 'cert.pem'),
      ],
      { stdio: 'ignore' },
    );
    await build({
      configFile: false,
      root: project,
      base: '/veritaxa/',
      logLevel: 'silent',
      build: {
        outDir: output,
        emptyOutDir: false,
        target: 'es2022',
        rolldownOptions: {
          input: resolve(project, `tests/fixtures/synthetic-only/${entry}.html`),
        },
      },
    });
    const preview = pngFactory(1600, 1067);
    const original = pngFactory(3200, 2134);
    images = httpsServer(
      {
        key: readFileSync(join(directory, 'key.pem')),
        cert: readFileSync(join(directory, 'cert.pem')),
      },
      (request, response) => {
        const match = /^\/(display|original)-(\d+)\.png$/.exec(request.url ?? '');
        const ordinal = Number(match?.[2]);
        if (!match || ordinal < 1 || ordinal > 1000) {
          response.writeHead(404).end();
          return;
        }
        const isOriginal = match[1] === 'original';
        requests[isOriginal ? 'original' : 'preview'] += 1;
        const body = (isOriginal ? original : preview)(ordinal);
        response
          .writeHead(200, {
            'Content-Type': 'image/png',
            'Content-Length': body.length,
            'Cache-Control': 'public, max-age=3600, immutable',
          })
          .end(body);
      },
    );
    const imagePort = await listen(images);
    assets = httpServer((request, response) => {
      try {
        const path = decodeURIComponent(new URL(request.url ?? '/', 'http://127.0.0.1').pathname);
        if (!path.startsWith('/veritaxa/')) {
          response.writeHead(404).end();
          return;
        }
        const file = resolve(output, path.slice('/veritaxa/'.length));
        if (!file.startsWith(output + sep)) {
          response.writeHead(404).end();
          return;
        }
        const mime: Record<string, string> = {
          '.html': 'text/html',
          '.js': 'text/javascript',
          '.css': 'text/css',
        };
        response
          .writeHead(200, { 'Content-Type': mime[extname(file)] ?? 'application/octet-stream' })
          .end(readFileSync(file));
      } catch {
        response.writeHead(404).end();
      }
    });
    const pagePort = await listen(assets);
    return {
      url: `http://127.0.0.1:${String(pagePort)}/veritaxa/tests/fixtures/synthetic-only/${entry}.html?image-port=${String(imagePort)}`,
      requests,
      close: async () => {
        await close(assets);
        await close(images);
        rmSync(directory, { recursive: true, force: true });
      },
    };
  } catch (error) {
    await close(assets);
    await close(images);
    rmSync(directory, { recursive: true, force: true });
    throw error;
  }
}
