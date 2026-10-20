// Writes web/test/scenarios.json: the scripted runs trace_python.py and
// parity.mjs both replay. Events are fixed lists (no runtime randomness in
// the script itself); the game's own randomness comes from the seed.
//
// Event types (applied at the start of their tick, before the input pass):
//   key       { vk, down, char? }      a key press / release (Windows VK)
//   set_ball  { pos: [x, y], vel: [x, y] }
//   notify    { code, name }           game.bus.notify(code, objects[name])
//   msg       { name, code, value }    game.msg(name, code, value)

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SPACE = 0x20;
const Z = 0x5a;
const SLASH = 0xbf;
const X = 0x58;
const PERIOD = 0xbe;
const UP = 0x26;
const F3 = 0x72;

function press(events, tick, vk, hold) {
  events.push({ tick, type: 'key', vk, down: true });
  events.push({ tick: tick + hold, type: 'key', vk, down: false });
}

function plunger(events, first, every, until, hold = 60) {
  for (let t = first; t < until; t += every) press(events, t, SPACE, hold);
}

// A tiny LCG for building fixed flipper schedules.
function lcg(seed) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function flips(events, seed, from, until) {
  const r = lcg(seed);
  let t = from;
  while (t < until) {
    const vk = r() < 0.5 ? Z : SLASH;
    const hold = 4 + Math.floor(r() * 20);
    press(events, t, vk, hold);
    t += hold + 2 + Math.floor(r() * 30);
  }
}

const scenarios = [];

{
  const events = [];
  plunger(events, 540, 600, 7200);
  scenarios.push({ name: 'drain_noflip', seed: 1, quick: true, demo: false, ticks: 7200, events });
}
{
  const events = [];
  plunger(events, 540, 600, 5400);
  flips(events, 99, 600, 5400);
  press(events, 3000, F3, 2);
  press(events, 3100, F3, 2);
  scenarios.push({ name: 'random_flip', seed: 2, quick: true, demo: false, ticks: 5400, events });
}
{
  const events = [];
  events.push({ tick: 600, type: 'set_ball', pos: [2.6, 2.2], vel: [-1.0, -30.0] });
  events.push({ tick: 1100, type: 'set_ball', pos: [-5.9, 0.2], vel: [1.5, -40.0] });
  events.push({ tick: 1700, type: 'set_ball', pos: [2.6, 2.2], vel: [-1.0, -12.0] });
  scenarios.push({ name: 'ramp_shot', seed: 3, quick: true, demo: false, ticks: 2400, events });
}
{
  const events = [];
  events.push({ tick: 600, type: 'notify', code: 0x3f, name: 's_onewy10' });
  events.push({ tick: 610, type: 'msg', name: 'fuel_bargraph', code: 0x2d, value: 11.0 });
  events.push({ tick: 620, type: 'notify', code: 0x3f, name: 'a_targ13' });
  events.push({ tick: 640, type: 'notify', code: 0x3f, name: 'ramp' });
  for (const t of [760, 880, 1000]) events.push({ tick: t, type: 'notify', code: 0x3f, name: 'ramp' });
  plunger(events, 1100, 600, 1800);
  scenarios.push({ name: 'mission_accept', seed: 4, quick: true, demo: false, ticks: 1800, events });
}
{
  const events = [];
  plunger(events, 540, 600, 4200);
  press(events, 900, X, 6);
  press(events, 960, PERIOD, 6);
  press(events, 1020, UP, 6);
  press(events, 1200, X, 40);
  press(events, 1300, PERIOD, 10);
  flips(events, 7, 1400, 2000);
  scenarios.push({ name: 'tilt', seed: 5, quick: true, demo: false, ticks: 4200, events });
}
{
  const events = [];
  plunger(events, 540, 600, 21000);
  scenarios.push({ name: 'game_over_high_score', seed: 6, quick: true, demo: false, ticks: 21000, events });
}
{
  scenarios.push({ name: 'demo', seed: 7, quick: true, demo: true, ticks: 7200, events: [] });
}

for (const s of scenarios) s.events.sort((a, b) => a.tick - b.tick);
fs.writeFileSync(path.join(HERE, 'scenarios.json'), `${JSON.stringify({ dt_ms: [17, 16, 17], draw_every: 30, scenarios }, null, 1)}\n`);
console.log(scenarios.map((s) => `${s.name}: ${s.ticks} ticks, ${s.events.length} events`).join('\n'));
