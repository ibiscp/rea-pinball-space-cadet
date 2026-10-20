// Port of render.py: the original renderer. Everything is composed in
// palette indices (a 600x416 8-bit buffer, the z-buffered table layer, the
// ball, the digit boxes, the text boxes in the PBMSG_FT bitmap font), as
// the original does; the browser shell only maps indices to RGB.

import { BITMAP_TYPE, int16At, tag10, floatArrays, taggedFloats } from './partout.js';
import { Vec2 } from './vec2.js';

const CONTINUATION = 201;

// A 2-D array: Uint8Array / Uint16Array `data` of h rows by w columns.
class Grid2D {
  constructor(w, h, data) {
    this.w = w;
    this.h = h;
    this.data = data;
  }
}

// Type-1 pixels, stored bottom-up: top row first.
function bitmapArray(bitmap) {
  const { width, height, stride } = bitmap;
  const out = new Uint8Array(width * height);
  const src = bitmap.pixel_data;
  for (let y = 0; y < height; y++) {
    const row = height - 1 - y;
    out.set(src.subarray(row * stride, row * stride + width), y * width);
  }
  return new Grid2D(width, height, out);
}

// Type-12 depth map: u16 width, height, stride, 8 header bytes, then
// stride*height u16 depths, bottom-up.
function zmapArray(raw) {
  const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const width = dv.getUint16(0, true);
  const height = dv.getUint16(2, true);
  const stride = dv.getUint16(4, true);
  const out = new Uint16Array(width * height);
  for (let y = 0; y < height; y++) {
    const row = height - 1 - y;
    for (let x = 0; x < width; x++) out[y * width + x] = dv.getUint16(14 + (row * stride + x) * 2, true);
  }
  return new Grid2D(width, height, out);
}

function isContinuation(entry) {
  return entry.variants.some((v) => v.type_tag === 0 && v.raw.length === 2 && int16At(v.raw) === CONTINUATION);
}

class Frame {
  constructor(pixels, zmap, x, y) {
    this.pixels = pixels;
    this.zmap = zmap;
    this.x = x;
    this.y = y;
  }
}

function entryFrames(pf, index, origin) {
  const frames = [];
  const entries = pf.entries;
  let i = index;
  while (i < entries.length && (i === index || isContinuation(entries[i]))) {
    const bv = entries[i].variants.find((v) => v.type_tag === BITMAP_TYPE);
    const zv = entries[i].variants.find((v) => v.type_tag === 12);
    if (bv) {
      const b = bv.decoded;
      frames.push(new Frame(bitmapArray(b), zv ? zmapArray(zv.raw) : null, b.origin_x - origin[0], b.origin_y - origin[1]));
    }
    i += 1;
  }
  return frames;
}

class Sprite {
  constructor(name, frames) {
    this.name = name;
    this.frames = frames;
    const first = frames[0];
    this.pixels = first.pixels;
    this.zmap = first.zmap;
    this.x = first.x;
    this.y = first.y;
  }

  setBitmap(index) {
    this.pixels = index === null ? null : this.frames[index].pixels;
  }

  setFrame(index) {
    const f = this.frames[index];
    this.pixels = f.pixels;
    this.zmap = f.zmap;
    this.x = f.x;
    this.y = f.y;
  }
}

function clip(x, y, h, w, height, width) {
  const x0 = Math.max(x, 0);
  const y0 = Math.max(y, 0);
  const x1 = Math.min(x + w, width);
  const y1 = Math.min(y + h, height);
  if (x1 <= x0 || y1 <= y0) return null;
  return [x0, y0, x1, y1];
}

// FUN_01004a76.
function zblit(screen, zbuf, W, H, sprite, tableZmap) {
  const pixels = sprite.pixels;
  if (pixels === null) return;
  let zsrc;
  let zx;
  let zy;
  if (sprite.zmap === null) {
    zsrc = tableZmap;
    zx = 0;
    zy = 0;
  } else {
    zsrc = sprite.zmap;
    zx = sprite.x;
    zy = sprite.y;
  }
  const h = Math.min(pixels.h, zsrc.h + zy - sprite.y);
  const w = Math.min(pixels.w, zsrc.w + zx - sprite.x);
  const box = clip(sprite.x, sprite.y, h, w, H, W);
  if (box === null) return;
  const [x0, y0, x1, y1] = box;
  for (let y = y0; y < y1; y++) {
    const prow = (y - sprite.y) * pixels.w - sprite.x;
    const zrow = (y - zy) * zsrc.w - zx;
    const srow = y * W;
    for (let x = x0; x < x1; x++) {
      const depth = zsrc.data[zrow + x];
      if (depth <= zbuf[srow + x]) {
        screen[srow + x] = pixels.data[prow + x];
        zbuf[srow + x] = depth;
      }
    }
  }
}

// FUN_01004b75.
function ballBlit(screen, zbuf, W, H, pixels, depth, x, y) {
  const box = clip(x, y, pixels.h, pixels.w, H, W);
  if (box === null) return;
  const [x0, y0, x1, y1] = box;
  for (let yy = y0; yy < y1; yy++) {
    for (let xx = x0; xx < x1; xx++) {
      const v = pixels.data[(yy - y) * pixels.w + (xx - x)];
      if (v !== 0 && depth < zbuf[yy * W + xx]) screen[yy * W + xx] = v;
    }
  }
}

// FUN_010139ec.
function depth16(distance, zmin, scale) {
  if (!(distance >= zmin)) return 0;
  const value = (distance - zmin) * scale;
  if (value > 4294967296.0 / scale + zmin) return 0xffff;
  return Number(BigInt(Math.trunc(value)) & 0xffffn);
}

// FUN_01015c08.
function ballSpriteIndex(distance, thresholds) {
  for (let i = 0; i < thresholds.length - 1; i++) if (thresholds[i] <= distance) return i;
  return thresholds.length - 1;
}

class BitmapFont {
  constructor(gap, height, glyphs) {
    this.gap = gap;
    this.height = height;
    this.glyphs = glyphs;
  }

  // The PBMSG_FT resource bytes (see assets.font_data).
  static parse(data) {
    const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
    const gap = dv.getInt16(0, true);
    const height = dv.getInt16(4, true);
    const widths = data.subarray(6, 134);
    const glyphs = new Map();
    let offset = 134;
    widths.forEach((width, code) => {
      if (!width) return;
      const size = width * height;
      glyphs.set(code, new Grid2D(width, height, data.slice(offset + 1, offset + 1 + size)));
      offset += size + 1;
    });
    return new BitmapFont(gap, height, glyphs);
  }
}

// FUN_01014269's line breaking: [char, x, y] placements.
function layoutText(font, text, boxW, boxH) {
  const data = [...text].map((ch) => ch.charCodeAt(0) & 0x7f);
  data.push(0);
  const placed = [];
  let pos = 0;
  let y = 0;
  while (data[pos] !== 0 && y + font.height <= boxH) {
    let end = pos;
    let width = 0;
    let lastSpace = null;
    while (data[end] !== 0 && data[end] !== 10) {
      const glyph = font.glyphs.get(data[end]);
      if (glyph === undefined) {
        end += 1;
        continue;
      }
      width += font.gap + glyph.w;
      if (width > boxW) {
        if (lastSpace !== null) end = lastSpace;
        break;
      }
      if (data[end] === 32) lastSpace = end;
      end += 1;
    }
    let x = 0;
    while (pos < end) {
      const glyph = font.glyphs.get(data[pos]);
      if (glyph !== undefined) {
        placed.push([data[pos], x, y]);
        x += font.gap + glyph.w;
      }
      pos += 1;
    }
    while (data[pos] === 32) pos += 1;
    if (data[pos] === 10) pos += 1;
    y += font.height;
  }
  return placed;
}

// The flipper sprite's own frame timer (0x101c070 / 0x101c178).
class FlipperAnimation {
  constructor(sprite, upTime, downTime, timers) {
    this.sprite = sprite;
    this.count = sprite.frames.length;
    this.durations = { 1: upTime, 2: downTime };
    this.frame_times = { 1: upTime / (this.count - 1), 2: downTime / (this.count - 1) };
    this.timers = timers;
    this.mode = 0;
    this.frame = 0;
    this.start = 0.0;
    this.frame_time = this.frame_times[1];
    this._timer = 0;
    this._swing_start = 0.0;
    this._swing_end = -1.0;
  }

  message(code) {
    const now = this.timers.now;
    this.frame_time = this.frame_times[code];
    if (this._timer) {
      this.timers.cancel(this._timer);
      this._timer = 0;
    }
    let delay;
    if (this.mode === 0) {
      delay = this.frame_time;
    } else {
      const elapsed = now - this._swing_start;
      delay = elapsed - Math.floor(elapsed / this.frame_time) * this.frame_time;
      delay = Math.max(delay, 0.0);
    }
    this.mode = code;
    this.start = now;
    this._timer = this.timers.schedule(delay, () => this._tick());
    if (now > this._swing_end) this._swing_start = now;
    this._swing_end = this._swing_start + this.durations[code];
  }

  reset() {
    if (!this.mode) return;
    if (this._timer) {
      this.timers.cancel(this._timer);
      this._timer = 0;
    }
    this.frame = -1;
    this.mode = 2;
    this._tick();
  }

  _tick() {
    this._timer = 0;
    let steps = Math.floor((this.timers.now - this.start) / this.frame_time + 0.5);
    steps = Math.max(1, Math.min(steps, this.count));
    let done = false;
    if (this.mode === 1) {
      this.frame += steps;
      if (this.frame >= this.count - 1) {
        this.frame = this.count - 1;
        done = true;
      }
    } else if (this.mode === 2) {
      this.frame -= steps;
      if (this.frame <= 0) {
        this.frame = 0;
        done = true;
      }
    }
    if (done) this.mode = 0;
    else this._timer = this.timers.schedule(this.frame_time, () => this._tick());
    this.sprite.setFrame(this.frame);
  }
}

function nudgeShift(x, y) {
  return [Math.floor(x + 0.5), Math.floor(0.5 - y)];
}

function manifestPairs(pf) {
  const values = tag10(pf.find('table_objects'));
  const out = [];
  for (let i = 1; i + 1 < values.length; i += 2) out.push([values[i], values[i + 1]]);
  return out;
}

class Renderer {
  constructor(pf, palette, camera, fontData = null) {
    const [width, height] = tag10(pf.find('table_size'));
    this.width = width;
    this.height = height;
    this.palette = palette;
    const tableEntry = pf.find('table');
    const tableBitmap = tableEntry.variants.find((v) => v.type_tag === BITMAP_TYPE).decoded;
    this.origin = [tableBitmap.origin_x, tableBitmap.origin_y];
    this.camera = camera.withOffset(0.0, 0.0);
    const cam = floatArrays(pf.find('camera_info'))[0];
    this.zmin = cam[13];
    this.zscale = cam[14];

    const indexOf = new Map(pf.entries.map((e, i) => [e, i]));
    const tableFrames = entryFrames(pf, indexOf.get(tableEntry), this.origin);
    const tf = tableFrames[0];
    this.table = new Sprite('table', [new Frame(tf.pixels, tf.zmap, 0, 0)]);
    this.table_zmap = this.table.zmap;

    this.base = new Uint8Array(width * height);
    const panel = pf.find('background');
    if (panel !== null) {
      const b = panel.variants.find((v) => v.type_tag === BITMAP_TYPE).decoded;
      const px = bitmapArray(b);
      for (let y = 0; y < px.h; y++) {
        const dy = b.origin_y + y;
        if (dy < 0 || dy >= height) continue;
        for (let x = 0; x < px.w; x++) {
          const dx = b.origin_x + x;
          if (dx >= 0 && dx < width) this.base[dy * width + dx] = px.data[y * px.w + x];
        }
      }
    }

    this.sprites = [];
    this.by_name = new Map();
    this.types = new Map();
    for (const [typeId, entryIndex] of manifestPairs(pf)) {
      const frames = entryFrames(pf, entryIndex, this.origin);
      if (!frames.length) continue;
      const name = pf.entries[entryIndex].name || `#${entryIndex}`;
      const sprite = new Sprite(name, frames);
      this.sprites.push(sprite);
      this.by_name.set(name, sprite);
      this.types.set(name, typeId);
    }

    const ball = pf.find('ball');
    const ballIndex = indexOf.get(ball);
    this.ball_frames = entryFrames(pf, ballIndex, [0, 0]).map((f) => f.pixels);
    this.ball_thresholds = [];
    for (let i = 0; i < this.ball_frames.length; i++) {
      const point = taggedFloats(pf.entries[ballIndex + i], 501);
      this.ball_thresholds.push(this.distance(new Vec2(point[0], point[1]), point[2]));
    }

    this.digit_boxes = new Map();
    this.digits = [];
    for (const name of ['score1', 'ballcount1', 'player_number1']) {
      const values = tag10(pf.find(name));
      const [first, x, y, w, h] = values;
      this.digit_boxes.set(name, { x, y, w, h });
      if (!this.digits.length) {
        for (let d = 0; d < 10; d++) this.digits.push(entryFrames(pf, first + d, [0, 0])[0].pixels);
      }
    }

    this.text_boxes = new Map();
    for (const name of ['info_text_box', 'mission_text_box']) {
      const stream = tag10(pf.find(name));
      const at = stream.indexOf(1500);
      this.text_boxes.set(name, stream.slice(at + 1, at + 5));
    }
    this.font = fontData ? BitmapFont.parse(fontData) : null;

    this.shift = [0, 0];
    this.screen = this.base.slice();
    this.table_w = this.table.frames[0].pixels.w;
  }

  setPalette(palette) {
    this.palette = palette;
  }

  // FUN_01008ed8.
  distance(p, z) {
    const m = this.camera.matrix;
    const v = [0, 1, 2].map((r) => m[r][0] * p.x + m[r][1] * p.y + m[r][2] * z + m[r][3]);
    return Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
  }

  compose(ball, score, ballNumber, player, texts) {
    const W = this.width;
    const H = this.height;
    const vscreen = this.base.slice();
    const zbuf = new Uint16Array(W * H).fill(0xffff);
    zblit(vscreen, zbuf, W, H, this.table, this.table_zmap);
    for (const sprite of this.sprites) zblit(vscreen, zbuf, W, H, sprite, this.table_zmap);
    if (ball !== null) this._drawBall(vscreen, zbuf, ball[0], ball[1]);
    this._drawDigits(vscreen, 'score1', score);
    this._drawDigits(vscreen, 'ballcount1', ballNumber);
    this._drawDigits(vscreen, 'player_number1', player);
    for (const [name, text] of texts) this._drawTextBox(vscreen, name, text);
    this._present(vscreen);
    return vscreen;
  }

  _drawBall(vscreen, zbuf, position, z) {
    const distance = this.distance(position, z);
    const pixels = this.ball_frames[ballSpriteIndex(distance, this.ball_thresholds)];
    const screen = this.camera.toScreen(position, z);
    const x = Math.trunc(screen.x) - Math.floor(pixels.w / 2);
    const y = Math.trunc(screen.y) - Math.floor(pixels.h / 2);
    ballBlit(vscreen, zbuf, this.width, this.height, pixels, depth16(distance, this.zmin, this.zscale), x, y);
  }

  _drawDigits(vscreen, name, value) {
    const box = this.digit_boxes.get(name);
    const W = this.width;
    const H = this.height;
    if (value !== null && value > 1000000000) return;
    for (let y = Math.max(box.y, 0); y < Math.min(box.y + box.h, H); y++) {
      for (let x = Math.max(box.x, 0); x < Math.min(box.x + box.w, W); x++) vscreen[y * W + x] = 0;
    }
    if (value === null || value < 0) return;
    let x = box.x + box.w;
    const digits = String(value);
    for (let i = digits.length - 1; i >= 0; i--) {
      const glyph = this.digits[Number(digits[i])];
      x -= glyph.w;
      const region = clip(x, box.y, glyph.h, glyph.w, H, W);
      if (region !== null) {
        const [x0, y0, x1, y1] = region;
        for (let yy = y0; yy < y1; yy++) {
          for (let xx = x0; xx < x1; xx++) vscreen[yy * W + xx] = glyph.data[(yy - box.y) * glyph.w + (xx - x)];
        }
      }
    }
  }

  _drawTextBox(vscreen, name, text) {
    const [x, y, w, h] = this.text_boxes.get(name);
    const W = this.width;
    const H = this.height;
    for (let yy = Math.max(y, 0); yy < Math.min(y + h, H); yy++) {
      for (let xx = Math.max(x, 0); xx < Math.min(x + w, W); xx++) vscreen[yy * W + xx] = 0;
    }
    if (!text || this.font === null) return;
    for (const [code, gx, gy] of layoutText(this.font, text, w, h)) {
      const glyph = this.font.glyphs.get(code);
      for (let yy = 0; yy < glyph.h; yy++) {
        const sy = y + gy + yy;
        if (sy < 0 || sy >= H) continue;
        for (let xx = 0; xx < glyph.w; xx++) {
          const sx = x + gx + xx;
          if (sx >= 0 && sx < W) vscreen[sy * W + sx] = glyph.data[yy * glyph.w + xx];
        }
      }
    }
  }

  // The window copy: right of the table region as is; the table region
  // moved by the nudge offset; uncovered pixels keep what they showed.
  _present(vscreen) {
    const W = this.width;
    const H = this.height;
    const tw = this.table_w;
    for (let y = 0; y < H; y++) this.screen.set(vscreen.subarray(y * W + tw, (y + 1) * W), y * W + tw);
    const [dx, dy] = this.shift;
    const region = clip(dx, dy, H, tw, H, W);
    if (region !== null) {
      const [x0, y0, x1, y1] = region;
      for (let y = y0; y < y1; y++) {
        this.screen.set(vscreen.subarray((y - dy) * W + (x0 - dx), (y - dy) * W + (x1 - dx)), y * W + x0);
      }
    }
  }
}

export {
  Renderer, FlipperAnimation, BitmapFont, layoutText, nudgeShift, depth16, ballSpriteIndex, entryFrames, Sprite,
};
