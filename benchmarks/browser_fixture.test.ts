import assert from 'node:assert/strict';
import test from 'node:test';
import { inflateSync } from 'node:zlib';
import { pngFactory } from './browser_fixture.ts';

// Independent, bitwise CRC reader: do not verify the writer with its own table.
function readPng(png: Buffer) {
  assert.deepEqual(png.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  const chunks = new Map<string, Buffer>();
  let offset = 8;
  while (offset < png.length) {
    const length = png.readUInt32BE(offset);
    let crc = 0xffffffff;
    for (const byte of png.subarray(offset + 4, offset + 8 + length)) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
    assert.equal((crc ^ 0xffffffff) >>> 0, png.readUInt32BE(offset + 8 + length));
    chunks.set(
      png.toString('ascii', offset + 4, offset + 8),
      png.subarray(offset + 8, offset + 8 + length),
    );
    offset += length + 12;
  }
  assert.equal(offset, png.length);
  assert.deepEqual([...chunks.keys()], ['IHDR', 'IDAT', 'IEND']);
  const header = chunks.get('IHDR');
  const data = chunks.get('IDAT');
  assert.ok(header && data);
  assert.equal(header[8], 8);
  assert.equal(header[9], 6);
  return {
    width: header.readUInt32BE(0),
    height: header.readUInt32BE(4),
    pixels: inflateSync(data),
  };
}

await test('synthetic rasters have valid chunks, exact dimensions and distinct pixels', () => {
  for (const [width, height] of [
    [1600, 1067],
    [3200, 2134],
  ]) {
    const create = pngFactory(width, height);
    const first = create(1);
    const last = create(1000);
    assert.notDeepEqual(first, last);
    assert.deepEqual(create(1), first);
    const decoded = readPng(last);
    assert.equal(decoded.width, width);
    assert.equal(decoded.height, height);
    assert.equal(decoded.pixels.length, (width * 4 + 1) * height);
    assert.equal(decoded.pixels[1] + decoded.pixels[2] * 256, 1000);
    for (let row = 0; row < height; row += 1)
      assert.equal(decoded.pixels[row * (width * 4 + 1)], 0);
  }
});

await test('raster fixture rejects unbounded dimensions and invalid identities', () => {
  for (const dimension of [-1, 0, 3201, Infinity, NaN, 1.5]) {
    assert.throws(() => pngFactory(dimension, 10), /dimensions/);
    assert.throws(() => pngFactory(10, dimension), /dimensions/);
  }
  const create = pngFactory(2, 2);
  for (const ordinal of [0, -1, 1001, NaN, Infinity, 1.5])
    assert.throws(() => create(ordinal), /ordinal/);
});
