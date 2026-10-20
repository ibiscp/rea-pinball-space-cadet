// Replays web/test/scenarios.json through the JS port and compares every
// tick with the Python game's trace (web/test/traces/*.json, written by
// trace_python.py): ball state, score, balls, mode, timers, tilt heat,
// every light's state, both text boxes, flippers, plunger, mission state,
// player, and a hash of the composed 600x416 palette-index screen every
// `draw_every` ticks.
//
//   uv run --project python python web/test/trace_python.py && node web/test/parity.mjs [scenario ...]

import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { buildBundle } from '../build.mjs';
import { App } from '../src/app.js';
import { loadGameData, soundSeconds } from '../src/data.js';
import { resetMemoryStore } from '../src/highscores.js';
import { HighScoreDialog } from '../src/menu.js';
import { rng } from '../src/rng.js';
import { Vec2 } from '../src/vec2.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const NAME_KEYS = [[0x52, 'R'], [0x45, 'E'], [0x41, 'A'], [0x0d, '\r']];
const FIELDS = ['tick', 'ball.x', 'ball.y', 'ball.vx', 'ball.vy', 'ball.z', 'ball.mask', 'ball.held', 'ball.alive',
  'score', 'balls', 'mode', 'timers', 'tilt_heat', 'lights', 'info_text', 'mission_text', 'left_flipper.state',
  'right_flipper.state', 'plunger.kick', 'mission', 'player', 'dialog'];
const FLOAT_FIELDS = new Set([1, 2, 3, 4, 5, 13, 19]);
const TOLERANCE = 1e-6;

function lightsDigest(game) {
  let s = '';
  for (const light of game.lights.values()) {
    s += `${light.shown === null ? '-' : light.shown},${light.state},${light.flashing},${light.temp_on},${light.temp_off};`;
  }
  return crypto.createHash('md5').update(s).digest('hex');
}

function run(data, scenario, dtPattern, drawEvery) {
  resetMemoryStore();
  rng.seed(scenario.seed);
  const audio = {
    playFile: (name) => soundSeconds(data.sounds, name),
    playMusic() {}, stopMusic() {}, stopEffects() {}, setEffectsEnabled() {},
  };
  const app = new App(data, audio, { quick: scenario.quick, demo: scenario.demo });
  const game = app.game;
  const events = new Map();
  for (const ev of scenario.events) {
    if (!events.has(ev.tick)) events.set(ev.tick, []);
    events.get(ev.tick).push(ev);
  }
  const typed = new Set();
  const rows = [];
  const draws = {};
  for (let tick = 0; tick < scenario.ticks; tick++) {
    const keys = [];
    const dialog = app.dialog;
    if (dialog instanceof HighScoreDialog && dialog.entering && !typed.has(dialog)) {
      typed.add(dialog);
      for (const [vk, ch] of NAME_KEYS) keys.push([vk, true, ch]);
    }
    for (const ev of events.get(tick) || []) {
      if (ev.type === 'key') keys.push([ev.vk, ev.down, ev.char || '']);
      else if (ev.type === 'set_ball') {
        app.ball.position = new Vec2(...ev.pos);
        app.ball.velocity = new Vec2(...ev.vel);
      } else if (ev.type === 'notify') game.bus.notify(ev.code, game.objects.get(ev.name));
      else if (ev.type === 'msg') game.msg(ev.name, ev.code, ev.value);
    }
    for (const [vk, down, ch] of keys) {
      if (down) app.keyDown({ vk, char: ch });
      else app.keyUp({ vk });
    }
    app.nextHighScoreEntry();
    if (app._first_game_ms > 0 || (app.focused && !app.modal())) app.update(dtPattern[tick % dtPattern.length] / 1000.0);
    const b = app.ball;
    rows.push([
      tick, b.position.x, b.position.y, b.velocity.x, b.velocity.y, b.z, b.mask, b.held ? 1 : 0, b.alive ? 1 : 0,
      game.score, game.balls, game.mode, game.timers.count, app.tilt_heat, lightsDigest(game),
      game.info_text, game.mission_text, app.left_flipper.state, app.right_flipper.state, app.plunger.kick,
      game.data('lite198'), game.player_number, app.dialog !== null ? 1 : 0,
    ]);
    if (tick % drawEvery === 0) {
      const screen = app.draw();
      draws[tick] = crypto.createHash('sha1').update(screen).digest('hex');
    }
  }
  return { rows, draws, high_scores: game.high_scores.entries.map((e) => [e.name, e.score]) };
}

function compare(name, js, py) {
  let firstBad = null;
  let maxDiff = 0;
  let exactFloats = true;
  const n = Math.min(js.rows.length, py.rows.length);
  for (let t = 0; t < n && firstBad === null; t++) {
    const a = js.rows[t];
    const b = py.rows[t];
    for (let k = 0; k < FIELDS.length; k++) {
      if (FLOAT_FIELDS.has(k)) {
        const d = Math.abs(a[k] - b[k]);
        if (a[k] !== b[k]) exactFloats = false;
        maxDiff = Math.max(maxDiff, d);
        if (!(d <= TOLERANCE)) {
          firstBad = { tick: t, field: FIELDS[k], js: a[k], py: b[k] };
          break;
        }
      } else if (a[k] !== b[k]) {
        firstBad = { tick: t, field: FIELDS[k], js: a[k], py: b[k] };
        break;
      }
    }
  }
  let drawsChecked = 0;
  let drawsBad = 0;
  let firstBadDraw = null;
  for (const [tick, hash] of Object.entries(py.draws)) {
    if (firstBad !== null && Number(tick) >= firstBad.tick) break;
    drawsChecked += 1;
    if (js.draws[tick] !== hash) {
      drawsBad += 1;
      if (firstBadDraw === null) firstBadDraw = Number(tick);
    }
  }
  const scoresOk = JSON.stringify(js.high_scores) === JSON.stringify(py.high_scores);
  const ok = firstBad === null && drawsBad === 0 && js.rows.length === py.rows.length && scoresOk;
  return { name, ok, ticks: n, firstBad, maxDiff, exactFloats, drawsChecked, drawsBad, firstBadDraw, scoresOk };
}

function main() {
  const spec = JSON.parse(fs.readFileSync(path.join(HERE, 'scenarios.json'), 'utf8'));
  const wanted = new Set(process.argv.slice(2));
  const data = loadGameData(buildBundle());
  let failed = 0;
  for (const scenario of spec.scenarios) {
    if (wanted.size && !wanted.has(scenario.name)) continue;
    const tracePath = path.join(HERE, 'traces', `${scenario.name}.json`);
    if (!fs.existsSync(tracePath)) {
      console.log(`${scenario.name}: no Python trace (run trace_python.py)`);
      failed += 1;
      continue;
    }
    const py = JSON.parse(fs.readFileSync(tracePath, 'utf8'));
    const t0 = Date.now();
    const js = run(data, scenario, spec.dt_ms, spec.draw_every);
    const r = compare(scenario.name, js, py);
    const last = js.rows[js.rows.length - 1];
    const floats = r.exactFloats ? 'bit-identical' : `max |diff| ${r.maxDiff.toExponential(2)}`;
    console.log(`${r.ok ? 'PASS' : 'FAIL'} ${scenario.name}: ${r.ticks} ticks (${Date.now() - t0} ms), ball state ${floats}, `
      + `screens ${r.drawsChecked - r.drawsBad}/${r.drawsChecked} identical, high scores ${r.scoresOk ? 'same' : 'DIFFER'}, `
      + `final score ${last[9]} balls ${last[10]} mode ${last[11]}`);
    if (r.firstBad) console.log('   first difference:', JSON.stringify(r.firstBad));
    if (r.firstBadDraw !== null) console.log('   first screen difference at tick', r.firstBadDraw);
    if (!r.ok) failed += 1;
  }
  process.exitCode = failed ? 1 : 0;
}

main();
