// Runs presentation/reverse-engineer-anything.html's own slide script in
// node under a DOM shim: every slide reachable with the arrow keys, the
// `play` slide right after `demo` with the game's iframe, a speaker note
// for every slide, and the game's postMessage keys / release handled.
//
//   node web/test/presentation_smoke.mjs

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const file = path.join(HERE, '..', '..', 'presentation', 'reverse-engineer-anything.html');
const html = fs.readFileSync(file, 'utf8');
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const code = inline[inline.length - 1];
const ids = [...html.matchAll(/<section class="slide" id="([^"]+)"/g)].map((m) => m[1]);

const listeners = { doc: {}, win: {} };
const on = (bag) => (type, fn) => (bag[type] ||= []).push(fn);
const fire = (bag, type, ev) => (bag[type] || []).forEach((fn) => fn(ev));
const slides = ids.map((id) => ({ id, active: false, classList: { toggle(name, v) { this.owner.active = v; } } }));
slides.forEach((s) => { s.classList.owner = s; });
const el = () => ({ style: {}, textContent: '', classList: { toggle() {} }, onclick: null });
const nodes = { stage: el(), hud: el(), notes: el(), prev: el(), next: el() };
let blurred = 0;
let focused = 0;
const bodyClasses = new Set();

globalThis.document = {
  querySelectorAll: () => slides,
  getElementById: (id) => nodes[id],
  addEventListener: on(listeners.doc),
  dispatchEvent: (ev) => fire(listeners.doc, ev.type, ev),
  activeElement: { tagName: 'IFRAME', blur() { blurred += 1; } },
  fullscreenElement: null,
  documentElement: { requestFullscreen() {} },
  body: { classList: { toggle(name, v) { if (v) bodyClasses.add(name); else bodyClasses.delete(name); } } },
};
globalThis.window = globalThis;
globalThis.location = { hash: "" };
globalThis.history = { replaceState() {} };
globalThis.innerWidth = 1920;
globalThis.innerHeight = 1080;
globalThis.addEventListener = on(listeners.win);
globalThis.focus = () => { focused += 1; };
globalThis.KeyboardEvent = class {
  constructor(type, init) {
    Object.assign(this, init, { type });
  }

  preventDefault() {}
};

new Function(code)();
const active = () => slides.findIndex((s) => s.active);
const results = [];
const check = (label, ok, detail = '') => {
  results.push(ok);
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` -- ${detail}` : ''}`);
};
const key = (k) => fire(listeners.doc, 'keydown', { key: k, preventDefault() {} });

check('the play slide follows demo', ids[ids.length - 1] === 'play' && ids[ids.length - 2] === 'demo', ids.slice(-3).join(', '));
const notes = (html.match(/^const NOTES=(\[.*\]);$/m) || [])[1];
check('a speaker note per slide', notes !== undefined && JSON.parse(notes).length === ids.length);
check('the play slide holds the game iframe', /<section class="slide" id="play"[^]*?<iframe id="space-cadet" src="\.\.\/web\/dist\/space-cadet\.html"/.test(html));
check('starts on slide 1', active() === 0);
for (let k = 0; k < ids.length + 2; k++) key('ArrowRight');
check('ArrowRight reaches the last slide (play)', ids[active()] === 'play', ids[active()]);
check('the game slide hides the slide number, help and edge buttons', bodyClasses.has('game'));
key('ArrowLeft');
check('ArrowLeft goes back', ids[active()] === 'demo');
check('other slides show them again', !bodyClasses.has('game'));
fire(listeners.win, 'message', { data: { source: 'space-cadet', type: 'key', key: 'ArrowRight', code: 'ArrowRight' } });
check('a key posted by the game moves the slides', ids[active()] === 'play');
check('and gives the keyboard back to the slides', blurred === 1 && focused === 1);
fire(listeners.win, 'message', { data: { source: 'space-cadet', type: 'release' } });
check('Esc in the game gives the keyboard back', blurred === 2 && focused === 2);
fire(listeners.win, 'message', { data: { source: 'elsewhere', type: 'key', key: 'ArrowLeft' } });
check('other messages are ignored', ids[active()] === 'play');
process.exitCode = results.every(Boolean) ? 0 : 1;
