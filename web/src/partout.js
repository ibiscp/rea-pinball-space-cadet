// The table data (PINBALL.DAT) as the Python port's partout.PartoutFile:
// entries of variants, each with the original's raw value bytes and the
// same decoded value. The web build ships it in its own compact form (see
// web/build.mjs): the manifest of src/space_cadet_pinball/data/pinball plus
// one binary blob holding every bitmap's palette indices (top row first)
// and every depth map (u16, top row first); `loadPartout` rebuilds each
// variant's raw bytes exactly as partout.variant_raw does.

const BITMAP_TYPE = 1;
const NAME_TYPE = 3;

class Variant {
  constructor(typeTag, size, offset, raw, decoded) {
    this.type_tag = typeTag;
    this.size = size;
    this.offset = offset;
    this.raw = raw;
    this.decoded = decoded;
  }
}

class Entry {
  constructor(index, offset, variants) {
    this.index = index;
    this.offset = offset;
    this.variants = variants;
    const nameVariant = variants.find((v) => v.type_tag === NAME_TYPE);
    this.name = nameVariant ? nameVariant.decoded : null;
  }
}

class PartoutFile {
  constructor(header, entries) {
    this.header = header;
    this.entries = entries;
    this._byName = new Map();
    for (const e of entries) {
      if (e.name && !this._byName.has(e.name)) this._byName.set(e.name, e);
    }
  }

  find(name) {
    return this._byName.get(name) || null;
  }
}

function _latin1(bytes) {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return s;
}

function decodeBitmap(buf, off) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const start = off;
  const reserved = buf[off];
  off += 1;
  const width = dv.getInt16(off, true);
  const height = dv.getInt16(off + 2, true);
  const originX = dv.getInt16(off + 4, true);
  const originY = dv.getInt16(off + 6, true);
  off += 8;
  const dataSize = dv.getUint32(off, true);
  off += 4;
  const flags = buf[off];
  off += 1;
  let stride = width;
  if (flags & 1 && stride % 4 !== 0) stride = stride - (stride % 4) + 4;
  const pixels = buf.subarray(off, off + dataSize);
  off += dataSize;
  return [
    {
      reserved, width, height, origin_x: originX, origin_y: originY, data_size: dataSize, flags, stride,
      pixel_data: pixels,
    },
    off - start,
  ];
}

function decodeGeneric(typeTag, raw) {
  if (typeTag === NAME_TYPE || typeTag === 9) {
    const nul = raw.indexOf(0);
    return _latin1(nul >= 0 ? raw.subarray(0, nul) : raw);
  }
  const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  if (typeTag === 10 && raw.length === 4) return [dv.getInt16(0, true), dv.getInt16(2, true)];
  if (typeTag === 5 && raw.length === 1024) {
    const out = [];
    for (let i = 0; i < 1024; i += 4) out.push([raw[i + 2], raw[i + 1], raw[i]]);
    return out;
  }
  if (typeTag === 11) {
    const n = raw.length >> 2;
    if (n * 4 === raw.length) {
      const out = new Array(n);
      for (let i = 0; i < n; i++) out[i] = dv.getFloat32(i * 4, true);
      return out;
    }
    return raw;
  }
  if (typeTag === 0 && raw.length === 2) return dv.getInt16(0, true);
  if (typeTag === 18 && raw.length === 1) return raw[0];
  if (typeTag === 13) return null;
  if (raw.length === 4) return { as_i32: dv.getInt32(0, true), as_f32: dv.getFloat32(0, true) };
  return raw;
}

function _b64(text) {
  if (typeof atob === 'function') {
    const s = atob(text);
    const out = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  }
  return new Uint8Array(Buffer.from(text, 'base64'));
}

// partout.variant_raw, from the web bundle's spec and blob.
function variantRaw(spec, blob) {
  const kind = spec.kind;
  if (kind === 'text') {
    const out = new Uint8Array(spec.value.length + 1);
    for (let i = 0; i < spec.value.length; i++) out[i] = spec.value.charCodeAt(i) & 0xff;
    return out;
  }
  if (kind === 'int16' || kind === 'int16s') {
    const values = kind === 'int16' ? [spec.value] : spec.value;
    const out = new Uint8Array(values.length * 2);
    const dv = new DataView(out.buffer);
    values.forEach((v, i) => dv.setInt16(i * 2, v, true));
    return out;
  }
  if (kind === 'float32s') {
    const out = new Uint8Array(spec.value.length * 4);
    const dv = new DataView(out.buffer);
    spec.value.forEach((v, i) => dv.setFloat32(i * 4, v, true));
    return out;
  }
  if (kind === 'palette') {
    const out = new Uint8Array(spec.value.length * 4);
    spec.value.forEach(([r, g, b, reserved], i) => {
      out[i * 4] = b;
      out[i * 4 + 1] = g;
      out[i * 4 + 2] = r;
      out[i * 4 + 3] = reserved;
    });
    return out;
  }
  if (kind === 'bitmap') {
    // Rows top-down in the blob; the original keeps them bottom-up, each
    // padded with zeros to the stride.
    const { width, height } = spec;
    const pixels = blob.subarray(spec.data[0], spec.data[0] + spec.data[1]);
    const stride = width + (spec.flags & 1 ? (4 - (width % 4)) % 4 : 0);
    const out = new Uint8Array(14 + stride * height);
    const dv = new DataView(out.buffer);
    out[0] = spec.reserved;
    dv.setInt16(1, width, true);
    dv.setInt16(3, height, true);
    dv.setInt16(5, spec.origin_x, true);
    dv.setInt16(7, spec.origin_y, true);
    dv.setUint32(9, stride * height, true);
    out[13] = spec.flags;
    for (let y = 0; y < height; y++) {
      out.set(pixels.subarray(y * width, (y + 1) * width), 14 + (height - 1 - y) * stride);
    }
    return out;
  }
  if (kind === 'depth') {
    // Seven u16 header words, then the u16 rows bottom-up; the blob holds
    // them top-down, `cols` (= stride) wide.
    const { rows, cols } = spec;
    const src = blob.subarray(spec.data[0], spec.data[0] + spec.data[1]);
    const out = new Uint8Array(14 + rows * cols * 2);
    const dv = new DataView(out.buffer);
    spec.header.forEach((v, i) => dv.setUint16(i * 2, v, true));
    for (let y = 0; y < rows; y++) {
      out.set(src.subarray(y * cols * 2, (y + 1) * cols * 2), 14 + (rows - 1 - y) * cols * 2);
    }
    return out;
  }
  if (kind === 'base64') return _b64(spec.value);
  throw new Error(`unknown ported variant kind ${kind}`);
}

// partout.load_ported, from the web bundle.
function loadPartout(manifest, blob) {
  const entries = manifest.entries.map((ent) => {
    const variants = ent.variants.map((spec) => {
      const raw = variantRaw(spec, blob);
      const decoded = spec.type === BITMAP_TYPE ? decodeBitmap(raw, 0)[0] : decodeGeneric(spec.type, raw);
      return new Variant(spec.type, spec.size, spec.offset, raw, decoded);
    });
    return new Entry(ent.index, ent.offset, variants);
  });
  return new PartoutFile(manifest.header, entries);
}

// The type-10 int16 stream (the first type-10 variant), as table_data._tag10_stream.
function tag10(entry) {
  const v = entry.variants.find((x) => x.type_tag === 10);
  if (!v) return [];
  const dv = new DataView(v.raw.buffer, v.raw.byteOffset, v.raw.byteLength);
  const out = [];
  for (let i = 0; i + 1 < v.raw.length; i += 2) out.push(dv.getInt16(i, true));
  return out;
}

function floatArrays(entry) {
  return entry.variants
    .filter((v) => v.type_tag === 11)
    .map((v) => {
      const dv = new DataView(v.raw.buffer, v.raw.byteOffset, v.raw.byteLength);
      const out = [];
      for (let i = 0; i + 3 < v.raw.length; i += 4) out.push(dv.getFloat32(i, true));
      return out;
    });
}

// projection.tagged_floats: the values after `tag` in one of the entry's
// type-11 float arrays (FUN_0100978e), or null.
function taggedFloats(entry, tag) {
  for (const values of floatArrays(entry)) {
    if (values.length && Math.trunc(values[0]) === tag) return values.slice(1);
  }
  return null;
}

function int16At(raw) {
  return new DataView(raw.buffer, raw.byteOffset, raw.byteLength).getInt16(0, true);
}

export {
  BITMAP_TYPE, NAME_TYPE, Variant, Entry, PartoutFile, decodeBitmap, decodeGeneric, variantRaw, loadPartout,
  tag10, floatArrays, taggedFloats, int16At,
};
