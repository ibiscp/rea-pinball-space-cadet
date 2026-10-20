// Renders the JS port's composed screen to PNG at chosen ticks of a
// scenario (for a visual check next to the Python game's own frames).
//
//   node web/test/render_png.mjs <scenario> <tick> [tick ...] [--out dir]

import fs from 'fs';
import path from 'path';
import zlib from 'zlib';
import { fileURLToPath } from 'url';
import { buildBundle } from '../build.mjs';
import { App } from '../src/app.js';
import { loadGameData, soundSeconds } from '../src/data.js';
import { resetMemoryStore } from '../src/highscores.js';
import { rng } from '../src/rng.js';
import { Vec2 } from '../src/vec2.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function crc32(buf) {
  let c;
  let crc = 0xffffffff;
  for (let n = 0; n < buf.length; n++) {
    c = (crc ^ buf[n]) & 0xff;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    crc = (crc >>> 8) ^ c;
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'latin1'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}

function writePng(file, width, height, pixels, palette) {
  const rows = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    rows[y * (width * 3 + 1)] = 0;
    for (let x = 0; x < width; x++) {
      const [r, g, b] = palette[pixels[y * width + x]];
      const o = y * (width * 3 + 1) + 1 + x * 3;
      rows[o] = r;
      rows[o + 1] = g;
      rows[o + 2] = b;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  fs.writeFileSync(file, Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(rows)), chunk('IEND', Buffer.alloc(0)),
  ]));
}

function main() {
  const args = process.argv.slice(2);
  const outAt = args.indexOf('--out');
  const outDir = outAt >= 0 ? args.splice(outAt, 2)[1] : path.join(HERE, 'frames');
  const [name, ...tickArgs] = args;
  const ticks = new Set(tickArgs.map(Number));
  const spec = JSON.parse(fs.readFileSync(path.join(HERE, 'scenarios.json'), 'utf8'));
  const scenario = spec.scenarios.find((s) => s.name === name);
  const data = loadGameData(buildBundle());
  resetMemoryStore();
  rng.seed(scenario.seed);
  const audio = { playFile: (n) => soundSeconds(data.sounds, n), playMusic() {}, stopMusic() {}, stopEffects() {},
    setEffectsEnabled() {} };
  const app = new App(data, audio, { quick: scenario.quick, demo: scenario.demo });
  fs.mkdirSync(outDir, { recursive: true });
  const last = Math.max(...ticks);
  for (let tick = 0; tick <= last; tick++) {
    for (const ev of scenario.events.filter((e) => e.tick === tick)) {
      if (ev.type === 'key') {
        if (ev.down) app.keyDown({ vk: ev.vk, char: '' });
        else app.keyUp({ vk: ev.vk });
      } else if (ev.type === 'set_ball') {
        app.ball.position = new Vec2(...ev.pos);
        app.ball.velocity = new Vec2(...ev.vel);
      } else if (ev.type === 'notify') app.game.bus.notify(ev.code, app.game.objects.get(ev.name));
      else if (ev.type === 'msg') app.game.msg(ev.name, ev.code, ev.value);
    }
    app.nextHighScoreEntry();
    if (app._first_game_ms > 0 || (app.focused && !app.modal())) app.update(spec.dt_ms[tick % spec.dt_ms.length] / 1000.0);
    if (ticks.has(tick)) {
      const screen = app.draw();
      const file = path.join(outDir, `${name}_${tick}.png`);
      writePng(file, app.renderer.width, app.renderer.height, screen, app.renderer.palette);
      console.log(`wrote ${file}`);
    }
  }
}

main();
