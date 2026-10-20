// Runs the built page's own script (web/dist/space-cadet.html) in node
// under a minimal DOM shim, for environments without a browser: it inflates
// the embedded data, starts the game, takes focus with a click, plays a few
// seconds through real key events, and checks the iframe protocol
// (navigation keys and Esc posted to the parent).
//
//   node web/build.mjs && node web/test/page_smoke.mjs

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(HERE, '..', 'dist', 'space-cadet.html'), 'utf8');
const dataText = html.match(/<script type="application\/octet-stream" id="pinball-data">([^<]*)<\/script>/)[1];
const scripts = [...html.matchAll(/<script>\n([\s\S]*?)\n<\/script>/g)];
const code = scripts[scripts.length - 1][1];

class Emitter {
  constructor() {
    this.listeners = {};
  }

  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }

  removeEventListener() {}

  emit(type, ev = {}) {
    for (const fn of this.listeners[type] || []) fn({ preventDefault() {}, ...ev });
  }
}

const calls = {};
function ctx2d() {
  return new Proxy({}, {
    get(target, prop) {
      if (prop in target) return target[prop];
      if (prop === 'measureText') return (t) => ({ width: String(t).length * 6 });
      return (...args) => {
        calls[prop] = (calls[prop] || 0) + 1;
        return args.length ? undefined : undefined;
      };
    },
    set(target, prop, value) {
      target[prop] = value;
      return true;
    },
  });
}

function makeCanvas() {
  const c = new Emitter();
  Object.assign(c, {
    width: 300, height: 150, clientWidth: 1486, clientHeight: 1080,
    getContext: () => ctx2d(),
    focus() {}, blur() {}, requestPointerLock() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1486, height: 1080 }),
  });
  return c;
}

const screenCanvas = makeCanvas();
const status = { textContent: 'Loading...', remove() { this.removed = true; } };
const posted = [];
const win = new Emitter();
let now = 1000.0;
const frames = [];
let hasFocus = false;

Object.assign(globalThis, {
  window: globalThis,
  parent: { postMessage: (m) => posted.push(m) },
  addEventListener: win.addEventListener.bind(win),
  removeEventListener() {},
  focus() {},
  blur() {},
  location: { search: '' },
  devicePixelRatio: 1,
  requestAnimationFrame: (fn) => frames.push(fn),
  createImageBitmap: async () => ({ width: 320, height: 222 }),
  ImageData: class {
    constructor(w, h) {
      this.width = w;
      this.height = h;
      this.data = new Uint8ClampedArray(w * h * 4);
    }
  },
  AudioContext: class {
    constructor() {
      this.state = 'running';
      this.currentTime = 0;
      this.destination = {};
    }

    decodeAudioData(buf) {
      return Promise.resolve({ duration: buf.byteLength / 22050 });
    }

    createBufferSource() {
      return { connect: (x) => x, start() { calls.soundStart = (calls.soundStart || 0) + 1; }, stop() {} };
    }

    createGain() {
      return { gain: { value: 1 }, connect: (x) => x };
    }

    resume() {}
  },
  document: Object.assign(new Emitter(), {
    getElementById: (id) => (id === 'screen' ? screenCanvas : id === 'status' ? status : { textContent: dataText }),
    createElement: () => makeCanvas(),
    hasFocus: () => hasFocus,
    fullscreenElement: null,
    visibilityState: 'visible',
    documentElement: { requestFullscreen: () => Promise.resolve() },
  }),
});
Object.defineProperty(globalThis, 'performance', { value: { now: () => now }, configurable: true });

function step(n) {
  for (let i = 0; i < n; i++) {
    now += 16.7;
    const queue = frames.splice(0);
    for (const fn of queue) fn(now);
  }
}

function key(type, code, keyName = '') {
  win.emit(type, { code, key: keyName || code, repeat: false, getModifierState: () => false });
}

const results = [];
function check(label, ok, detail = '') {
  results.push(ok);
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` -- ${detail}` : ''}`);
}

new Function(code)();
for (let i = 0; i < 300 && !globalThis.spaceCadet; i++) {
  step(1);
  await new Promise((r) => setTimeout(r, 10));
}
const shell = globalThis.spaceCadet;
check('page script starts the game', Boolean(shell), status.textContent);
const app = shell.app;
check('unfocused at start (a presentation slide is not playing by itself)', app.focused === false);
step(150);
check('startup wait runs without focus, then the game is set up', app.game.mode === 1, `mode ${app.game.mode}`);
const t0 = app.game.timers.now_ms;
step(60);
check('no ticks while unfocused', app.game.timers.now_ms === t0);
screenCanvas.emit('pointerdown', { button: 0, clientX: 700, clientY: 600 });
check('clicking the game focuses it', app.focused === true);
await new Promise((r) => setTimeout(r, 50)); // let Web Audio decode the sounds
step(600);
check('ball served after the start sound', app.ball.alive === true, `ball at (${app.ball.position.x.toFixed(2)}, ${app.ball.position.y.toFixed(2)})`);
key('keydown', 'Space', ' ');
step(60);
key('keyup', 'Space', ' ');
step(120);
check('space launches the ball', app.ball.position.y < 9.0, `ball y ${app.ball.position.y.toFixed(2)}`);
key('keydown', 'KeyZ', 'z');
step(3);
check('Z raises the left flipper', app.left_flipper.pressed === true);
key('keyup', 'KeyZ', 'z');
step(240);
check('sounds play through Web Audio after the first gesture', (calls.soundStart || 0) > 0, `${calls.soundStart || 0} starts`);
check('frames are drawn (putImageData + drawImage)', (calls.putImageData || 0) > 100 && (calls.drawImage || 0) > 100);
posted.length = 0;
key('keydown', 'ArrowRight', 'ArrowRight');
check('ArrowRight goes to the presentation', posted.some((m) => m.type === 'key' && m.key === 'ArrowRight')
  && posted.some((m) => m.type === 'release'), JSON.stringify(posted));
check('and the game stops ticking', app.focused === false);
screenCanvas.emit('pointerdown', { button: 0, clientX: 700, clientY: 600 });
posted.length = 0;
key('keydown', 'Escape', 'Escape');
check('Esc hands the keyboard back', posted.some((m) => m.type === 'release') && app.focused === false);
screenCanvas.emit('pointerdown', { button: 0, clientX: 30, clientY: 10 });
step(2);
check('clicking "Game" opens the menu bar', app.menu.is_open === true, `open ${app.menu.open_index}`);
key('keydown', 'Escape', 'Escape');
check('Esc closes the menu', app.menu.is_open === false);
console.log(`score ${app.score}, balls ${app.balls_left}, info "${app.game.info_text}"`);
process.exitCode = results.every(Boolean) ? 0 : 1;
