// Builds web/dist/space-cadet.html: one self-contained page with the game
// code and all of its data, playable offline and over file://.
//
//   node web/build.mjs
//
// Data comes from the Python package's ported data (single source of
// truth): python/src/space_cadet_pinball/data/ -- the table (manifest.json +
// indexed PNGs + depth .npy), the PBMSG_FT font, the splash and the WAVs --
// plus web/assets/pinball-theme.ogg, PINBALL.MID rendered once with
// timidity (browsers can't play MIDI). It is packed into this build's own
// compact format (a JSON header and one binary blob: bitmap palette
// indices, u16 depth maps, the font resource, PNG/WAV/OGG bytes), gzipped
// and base64'd into the page; the page inflates it with DecompressionStream.
//
// The JS modules in web/src are ES modules; this script concatenates them
// into one script (each module wrapped in a function, imports turned into
// references to the earlier modules' exports).

import fs from 'fs';
import path from 'path';
import zlib from 'zlib';
import { fileURLToPath } from 'url';

const WEB = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(WEB, '..');
const DATA = path.join(ROOT, 'python', 'src', 'space_cadet_pinball', 'data');
const THEME = path.join(WEB, 'assets', 'pinball-theme.ogg');
const OUT = path.join(WEB, 'dist', 'space-cadet.html');

// -- data ----------------------------------------------------------------

// 8-bit indexed PNG -> { width, height, pixels } (top row first).
function readIndexedPng(buf) {
  const sig = buf.subarray(0, 8);
  if (!sig.equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) throw new Error('not a PNG');
  let pos = 8;
  let width = 0;
  let height = 0;
  const idat = [];
  while (pos < buf.length) {
    const length = buf.readUInt32BE(pos);
    const kind = buf.toString('latin1', pos + 4, pos + 8);
    const body = buf.subarray(pos + 8, pos + 8 + length);
    pos += 12 + length;
    if (kind === 'IHDR') {
      width = body.readUInt32BE(0);
      height = body.readUInt32BE(4);
      if (body[8] !== 8 || body[9] !== 3 || body[12] !== 0) throw new Error('expected 8-bit indexed PNG');
    } else if (kind === 'IDAT') {
      idat.push(body);
    } else if (kind === 'IEND') {
      break;
    }
  }
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const out = new Uint8Array(width * height);
  const prev = new Uint8Array(width);
  for (let y = 0; y < height; y++) {
    const kind = raw[y * (width + 1)];
    const line = raw.subarray(y * (width + 1) + 1, (y + 1) * (width + 1));
    const row = out.subarray(y * width, (y + 1) * width);
    for (let x = 0; x < width; x++) {
      const a = x ? row[x - 1] : 0;
      const b = prev[x];
      const c = x ? prev[x - 1] : 0;
      let pred = 0;
      if (kind === 1) pred = a;
      else if (kind === 2) pred = b;
      else if (kind === 3) pred = (a + b) >> 1;
      else if (kind === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a);
        const pb = Math.abs(p - b);
        const pc = Math.abs(p - c);
        pred = pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      row[x] = (line[x] + pred) & 0xff;
    }
    prev.set(row);
  }
  return { width, height, pixels: out };
}

// A little-endian u2 .npy -> { shape, data } (raw bytes, row-major).
function readNpy(buf) {
  if (buf.toString('latin1', 1, 6) !== 'NUMPY') throw new Error('not a .npy');
  const major = buf[6];
  const headerLen = major === 1 ? buf.readUInt16LE(8) : buf.readUInt32LE(8);
  const start = major === 1 ? 10 : 12;
  const header = buf.toString('latin1', start, start + headerLen);
  if (!header.includes("'<u2'") || header.includes("'fortran_order': True")) throw new Error(`unexpected npy ${header}`);
  const shape = header.match(/'shape': \((\d+), (\d+)\)/).slice(1, 3).map(Number);
  return { shape, data: buf.subarray(start + headerLen, start + headerLen + shape[0] * shape[1] * 2) };
}

function buildBundle() {
  const parts = [];
  let offset = 0;
  const add = (bytes) => {
    const at = [offset, bytes.length];
    parts.push(Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength));
    offset += bytes.length;
    return at;
  };

  const pinballDir = path.join(DATA, 'pinball');
  const manifest = JSON.parse(fs.readFileSync(path.join(pinballDir, 'manifest.json'), 'utf8'));
  for (const entry of manifest.entries) {
    for (const spec of entry.variants) {
      if (spec.kind === 'bitmap') {
        const png = readIndexedPng(fs.readFileSync(path.join(pinballDir, spec.png)));
        spec.width = png.width;
        spec.height = png.height;
        spec.data = add(png.pixels);
        delete spec.png;
      } else if (spec.kind === 'depth') {
        const npy = readNpy(fs.readFileSync(path.join(pinballDir, spec.npy)));
        [spec.rows, spec.cols] = npy.shape;
        spec.data = add(npy.data);
        delete spec.npy;
      }
    }
  }

  // The PBMSG_FT resource bytes, exactly as assets.font_data() rebuilds them.
  const meta = JSON.parse(fs.readFileSync(path.join(DATA, 'pbmsg_ft.json'), 'utf8'));
  const atlas = readIndexedPng(fs.readFileSync(path.join(DATA, 'pbmsg_ft.png')));
  const fontBytes = [];
  for (const value of [meta.gap, meta.unused, meta.height]) fontBytes.push(value & 0xff, (value >> 8) & 0xff);
  fontBytes.push(...meta.widths);
  let ax = 0;
  meta.widths.forEach((width, code) => {
    if (!width) return;
    fontBytes.push(meta.lead[String(code)]);
    for (let y = 0; y < atlas.height; y++) {
      for (let x = 0; x < width; x++) fontBytes.push(atlas.pixels[y * atlas.width + ax + x]);
    }
    ax += width;
  });

  const sounds = {};
  for (const name of fs.readdirSync(path.join(DATA, 'sounds')).sort()) {
    if (!name.toLowerCase().endsWith('.wav')) continue;
    sounds[name.toLowerCase()] = add(fs.readFileSync(path.join(DATA, 'sounds', name)));
  }

  const header = {
    format: 'space-cadet-web/1',
    manifest: { header: manifest.header, entries: manifest.entries },
    font: add(Uint8Array.from(fontBytes)),
    splash: add(fs.readFileSync(path.join(DATA, 'splash.png'))),
    sounds,
    music: fs.existsSync(THEME) ? add(fs.readFileSync(THEME)) : null,
  };
  return { header, blob: Buffer.concat(parts) };
}

function packBundle({ header, blob }) {
  const json = Buffer.from(JSON.stringify(header), 'utf8');
  const head = Buffer.alloc(4);
  head.writeUInt32LE(json.length, 0);
  return zlib.gzipSync(Buffer.concat([head, json, blob]), { level: 9 });
}

function unpackBundle(packed) {
  const raw = zlib.gunzipSync(packed);
  const length = raw.readUInt32LE(0);
  const header = JSON.parse(raw.toString('utf8', 4, 4 + length));
  const blob = new Uint8Array(raw.buffer, raw.byteOffset + 4 + length, raw.length - 4 - length);
  return { header, blob };
}

// -- code ----------------------------------------------------------------

const IMPORT_RE = /import\s+(?:\*\s+as\s+(\w+)|\{([^}]*)\})\s+from\s+'\.\/(\w+)\.js';/g;

function bundleModules(entry) {
  const order = [];
  const seen = new Set();
  const sources = new Map();
  const visit = (name) => {
    if (seen.has(name)) return;
    seen.add(name);
    const src = fs.readFileSync(path.join(WEB, 'src', `${name}.js`), 'utf8');
    sources.set(name, src);
    for (const m of src.matchAll(IMPORT_RE)) visit(m[3]);
    order.push(name);
  };
  visit(entry);
  const chunks = order.map((name) => {
    let src = sources.get(name).replace(IMPORT_RE, (all, ns, names, from) => (
      ns ? `const ${ns} = __mod_${from};` : `const {${names}} = __mod_${from};`));
    const exportRe = /export\s*\{([^}]*)\};?\s*$/;
    const m = src.match(exportRe);
    src = m ? src.replace(exportRe, `return {${m[1]}};`) : src;
    if (/\bexport\b/.test(src.replace(/\/\/.*$/gm, ''))) throw new Error(`${name}.js: only a final "export { ... }" is supported`);
    return `const __mod_${name} = (() => {\n${src}\n})();`;
  });
  return `(() => {\n'use strict';\n${chunks.join('\n')}\n})();`;
}

function page(script, dataB64) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>3D Pinball for Windows - Space Cadet</title>
<style>
html,body{margin:0;width:100%;height:100%;background:#000;overflow:hidden}
canvas{display:block;width:100%;height:100%;outline:none;cursor:default}
#status{position:fixed;left:0;right:0;bottom:12px;text-align:center;font:13px Tahoma,Arial,sans-serif;color:#888}
</style>
</head>
<body>
<canvas id="screen" tabindex="0"></canvas>
<div id="status">Loading...</div>
<script type="application/octet-stream" id="pinball-data">${dataB64}</script>
<script>
${script}
</script>
</body>
</html>
`;
}

function main() {
  const bundle = buildBundle();
  const packed = packBundle(bundle);
  const script = bundleModules('shell');
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, page(script, packed.toString('base64')));
  const size = fs.statSync(OUT).size;
  console.log(`wrote ${path.relative(ROOT, OUT)}: ${(size / 1048576).toFixed(2)} MB `
    + `(data ${(bundle.blob.length / 1048576).toFixed(2)} MB raw, ${(packed.length / 1048576).toFixed(2)} MB gzipped)`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();

export { buildBundle, packBundle, unpackBundle, readIndexedPng };
