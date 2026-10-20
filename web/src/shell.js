// The browser shell: loads the bundled data, runs the App with real
// elapsed time (WinMain's loop: a tick only while the page has focus and no
// menu or dialog is open), maps palette indices to RGB, draws the menu bar
// and dialogs, scales the 600 x (416 + menu) screen into the canvas with the
// aspect kept (mouse mapped back), and plays sounds with Web Audio.
//
// Embedded in the presentation (an iframe), it talks to the parent with
// postMessage: navigation keys the game doesn't use are passed up
// ({ source: 'space-cadet', type: 'key', key, code }), and Esc hands the
// keyboard back ({ source: 'space-cadet', type: 'release' }).

import { App } from './app.js';
import { loadGameData, soundSeconds, unpack } from './data.js';
import { vkOfCode } from './controls.js';
import { MENU_HEIGHT, drawAbout } from './menu.js';
import { rng } from './rng.js';

const CHANNELS = 8;
// Keys the presentation navigates with; passed up when the game has no use for them.
const NAV_CODES = new Set(['ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown', 'Home', 'End', 'KeyN', 'KeyF']);
const SLIDE_CODES = new Set(['ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown', 'Home', 'End']);
const EMBEDDED = window.parent !== window;

function toParent(message) {
  if (EMBEDDED) window.parent.postMessage({ source: 'space-cadet', ...message }, '*');
}

async function inflate(base64) {
  const text = atob(base64.trim());
  const bytes = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) bytes[i] = text.charCodeAt(i);
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

// Effects on 8 channels, the one that started longest ago taking the next
// sound (audio.py / FUN_01006c26); the theme loops on its own.
class WebAudio {
  constructor(data) {
    this.sounds = data.sounds;
    this.musicBytes = data.music;
    this.ctx = null;
    this.buffers = new Map();
    this.music = null;
    this.musicSource = null;
    this.wantMusic = false;
    this.effectsEnabled = true;
    this.channels = new Array(CHANNELS).fill(null);
    this.started = new Array(CHANNELS).fill(0.0);
  }

  // Browsers only allow audio after a user gesture.
  unlock() {
    if (this.ctx !== null) {
      if (this.ctx.state === 'suspended') this.ctx.resume();
      return;
    }
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    this.ctx = new Ctx();
    for (const [name, bytes] of this.sounds) {
      this.ctx.decodeAudioData(bytes.slice().buffer).then((buffer) => this.buffers.set(name, buffer), () => {});
    }
    if (this.musicBytes) {
      this.ctx.decodeAudioData(this.musicBytes.slice().buffer).then((buffer) => {
        this.music = buffer;
        if (this.wantMusic) this.playMusic();
      }, () => {});
    }
  }

  setEffectsEnabled(on) {
    this.effectsEnabled = on;
    if (!on) this.stopEffects();
  }

  playFile(name) {
    const seconds = soundSeconds(this.sounds, name);
    if (this.ctx === null || !this.effectsEnabled) return seconds;
    const buffer = this.buffers.get(name.toLowerCase());
    if (!buffer) return seconds;
    let best = 0;
    for (let k = 1; k < CHANNELS; k++) if (this.started[k] < this.started[best]) best = k;
    if (this.channels[best]) {
      try {
        this.channels[best].stop();
      } catch (err) {
        // already ended
      }
    }
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);
    source.start();
    this.channels[best] = source;
    this.started[best] = this.ctx.currentTime + 1e-6 * best;
    return seconds;
  }

  stopEffects() {
    for (let k = 0; k < CHANNELS; k++) {
      if (this.channels[k]) {
        try {
          this.channels[k].stop();
        } catch (err) {
          // already ended
        }
      }
      this.channels[k] = null;
      this.started[k] = 0.0;
    }
  }

  playMusic() {
    this.wantMusic = true;
    if (this.ctx === null || this.music === null) return;
    this.stopMusic();
    this.wantMusic = true;
    const source = this.ctx.createBufferSource();
    source.buffer = this.music;
    source.loop = true;
    source.connect(this.ctx.destination);
    source.start();
    this.musicSource = source;
  }

  stopMusic() {
    this.wantMusic = false;
    if (this.musicSource) {
      try {
        this.musicSource.stop();
      } catch (err) {
        // already stopped
      }
    }
    this.musicSource = null;
  }
}

class Shell {
  constructor(canvas, data) {
    this.canvas = canvas;
    this.data = data;
    this.audio = new WebAudio(data);
    const params = new URLSearchParams(location.search);
    rng.seed(Date.now());
    this.app = new App(data, this.audio, { quick: params.has('quick'), demo: params.has('demo') }, {
      setTitle: (text) => {
        document.title = text;
      },
      fullScreen: (on) => this._fullScreen(on),
      minimize: () => this.release(),
      quit: () => this.release(),
    });
    this.app.focused = document.hasFocus();
    this.surface = document.createElement('canvas');
    this.ctx = this.surface.getContext('2d');
    this.image = null;
    this.lut = null;
    this.lutPalette = null;
    this.last = Math.floor(performance.now());
    this.drag = [0, 0];
    this._bind();
  }

  // Hand the keyboard back to the presentation (the original's Esc minimizes).
  release() {
    this._setFocus(false);
    toParent({ type: 'release' });
    this.canvas.blur();
    window.blur();
  }

  // WM_SETFOCUS / WM_KILLFOCUS reach the game only on a change.
  _setFocus(on) {
    if (this.app.focused !== on) this.app.focusChanged(on);
  }

  _fullScreen(on) {
    const el = document.documentElement;
    try {
      if (on && !document.fullscreenElement && el.requestFullscreen) el.requestFullscreen().catch(() => {});
      if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
    } catch (err) {
      return false;
    }
    return true;
  }

  _menuShown() {
    return !this.app.full_screen;
  }

  // With the menu shown the surface is as wide as the canvas allows at the
  // game's scale, so the menu bar spans the whole top, like a window's; the
  // 600x416 screen sits centred under it (see _screenX).
  _surfaceSize() {
    const w = this.app.table_width;
    if (!this._menuShown()) return [w, this.app.table_height];
    const h = this.app.table_height + MENU_HEIGHT;
    const scale = Math.min(this.canvas.width / w, this.canvas.height / h);
    return [Math.max(w, Math.floor(this.canvas.width / scale)), h];
  }

  _screenX() {
    return Math.floor((this._surfaceSize()[0] - this.app.table_width) / 2);
  }

  // Where the drawing surface lands in the canvas: as large as fits, aspect kept, centred.
  _viewRect() {
    const [lw, lh] = this._surfaceSize();
    const dw = this.canvas.width;
    const dh = this.canvas.height;
    const scale = Math.min(dw / lw, dh / lh);
    const w = Math.round(lw * scale);
    const h = Math.round(lh * scale);
    return { x: Math.floor((dw - w) / 2), y: Math.floor((dh - h) / 2), w, h, scale };
  }

  _toSurface(ev) {
    const rect = this.canvas.getBoundingClientRect();
    const px = (ev.clientX - rect.left) * (this.canvas.width / rect.width);
    const py = (ev.clientY - rect.top) * (this.canvas.height / rect.height);
    const v = this._viewRect();
    const [lw, lh] = this._surfaceSize();
    return [Math.floor((px - v.x) * lw / v.w), Math.floor((py - v.y) * lh / v.h)];
  }

  _bind() {
    const app = this.app;
    window.addEventListener('keydown', (ev) => {
      this.audio.unlock();
      const vk = vkOfCode(ev.code, ev.getModifierState && ev.getModifierState('NumLock'));
      const gameKey = app.keys.includes(vk);
      if (NAV_CODES.has(ev.code) && !gameKey && app.dialog === null && !app.menu.is_open) {
        toParent({ type: 'key', key: ev.key, code: ev.code });
        if (SLIDE_CODES.has(ev.code)) {
          ev.preventDefault();
          this.release();
          return;
        }
      }
      if (vk !== 0 || ev.code === 'Tab') ev.preventDefault();
      if (ev.repeat) return;
      app.keyDown({ vk, char: ev.key.length === 1 ? ev.key : '' });
    });
    window.addEventListener('keyup', (ev) => {
      const vk = vkOfCode(ev.code, ev.getModifierState && ev.getModifierState('NumLock'));
      if (vk !== 0) ev.preventDefault();
      app.keyUp({ vk });
    });
    window.addEventListener('focus', () => this._setFocus(true));
    window.addEventListener('blur', () => this._setFocus(false));
    this.canvas.addEventListener('pointerdown', (ev) => {
      this.audio.unlock();
      this.canvas.focus();
      this._setFocus(true);
      if (ev.button !== 0) return;
      app.click(this._toSurface(ev), this._menuShown());
      if (app.dragging && this.canvas.requestPointerLock) {
        this.drag = [0, 0];
        this.canvas.requestPointerLock();
      }
    });
    window.addEventListener('pointerup', () => {
      if (app.dragging) {
        app.mouseUp();
        if (document.pointerLockElement && document.exitPointerLock) document.exitPointerLock();
      }
    });
    window.addEventListener('pointermove', (ev) => {
      if (app.dragging) {
        this.drag[0] += ev.movementX || 0;
        this.drag[1] += ev.movementY || 0;
      } else {
        app.mouseMove(this._toSurface(ev));
      }
    });
    this.canvas.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      app.wheel(ev.deltaY < 0 ? 1 : -1);
    }, { passive: false });
    document.addEventListener('fullscreenchange', () => {
      if (!document.fullscreenElement && app.full_screen) {
        app.full_screen = 0;
        app._updateMenu();
      }
    });
    const save = () => app.saveSettings();
    window.addEventListener('pagehide', save);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') save();
    });
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = Math.max(1, Math.round(this.canvas.clientWidth * dpr));
      this.canvas.height = Math.max(1, Math.round(this.canvas.clientHeight * dpr));
    };
    window.addEventListener('resize', resize);
    resize();
  }

  // One pass of WinMain's loop.
  frame() {
    const app = this.app;
    const now = Math.floor(performance.now());
    app.nextHighScoreEntry();
    if (app.dragging) {
      const scale = this._viewRect().scale;
      app.dragBall(this.drag[0] / scale, this.drag[1] / scale);
      this.drag = [0, 0];
    }
    if (!(app._first_game_ms > 0 || (app.focused && !app.modal()))) {
      this.last = now;
    } else if (now !== this.last) {
      app.update((now - this.last) / 1000.0, false, now);
      this.last = now;
    }
    this.draw();
  }

  _palette() {
    const palette = this.app.renderer.palette;
    if (this.lutPalette !== palette) {
      this.lut = new Uint32Array(256);
      const little = new Uint8Array(new Uint32Array([1]).buffer)[0] === 1;
      palette.forEach(([r, g, b], i) => {
        this.lut[i] = little ? (0xff << 24) | (b << 16) | (g << 8) | r : (r << 24) | (g << 16) | (b << 8) | 0xff;
      });
      this.lutPalette = palette;
    }
    return this.lut;
  }

  draw() {
    const app = this.app;
    const [lw, lh] = this._surfaceSize();
    if (this.surface.width !== lw || this.surface.height !== lh) {
      this.surface.width = lw;
      this.surface.height = lh;
    }
    const ctx = this.ctx;
    const top = this._menuShown() ? MENU_HEIGHT : 0;
    const screen = app.draw();
    const W = app.renderer.width;
    const H = app.renderer.height;
    if (this.image === null) this.image = new ImageData(W, H);
    const lut = this._palette();
    const out = new Uint32Array(this.image.data.buffer);
    for (let i = 0; i < screen.length; i++) out[i] = lut[screen[i]];
    const left = this._screenX();
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, lw, lh);
    ctx.putImageData(this.image, left, top);
    if (app.debug_draw) this._drawDebugOverlay(ctx, left, top);
    if (app.dialog !== null) app.dialog.draw(ctx, lw, lh);
    if (app.about_open) drawAbout(ctx, lw, lh);
    if (this._menuShown()) app.menu.draw(ctx, lw);

    const view = this._viewRect();
    const out2 = this.canvas.getContext('2d');
    out2.fillStyle = '#000';
    out2.fillRect(0, 0, this.canvas.width, this.canvas.height);
    out2.imageSmoothingEnabled = true;
    out2.imageSmoothingQuality = 'high';
    out2.drawImage(this.surface, view.x, view.y, view.w, view.h);
  }

  // The port's collision overlay (D), not in the original.
  _drawDebugOverlay(ctx, left, top) {
    const app = this.app;
    const cam = app.renderer.camera;
    const [sx, sy] = app.table_shift;
    const px = (p) => {
      const s = cam.toScreen(p);
      return [Math.trunc(s.x) + sx + left + 0.5, Math.trunc(s.y) + sy + top + 0.5];
    };
    const line = (color, a, b) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(...px(a));
      ctx.lineTo(...px(b));
      ctx.stroke();
    };
    const circle = (color, center, radius) => {
      const [x, y] = px(center);
      ctx.strokeStyle = color;
      ctx.beginPath();
      ctx.arc(x, y, Math.max(1, Math.round(radius * cam.pxPerUnit(center))), 0, Math.PI * 2);
      ctx.stroke();
    };
    const ballMask = app.ball.mask;
    for (const seg of app.world.segments) {
      if (!(seg.mask & ballMask)) line('#6e6e6e', seg.a, seg.b);
      else if (seg.active) line(seg.one_sided ? '#00dcff' : '#ff2828', seg.a, seg.b);
    }
    for (const ln of app.world.trip_lines) line(ln.mask & ballMask ? '#e6c800' : '#6e6e6e', ln.a, ln.b);
    for (const ci of app.world.circles) circle(ci.mask & ballMask ? '#ff2828' : '#6e6e6e', ci.center, ci.radius);
    for (const f of [app.left_flipper, app.right_flipper]) {
      line('#ff2828', f.pivot, f.tip());
      circle('#ff2828', f.pivot, f.radius);
      circle('#ff2828', f.tip(), f.tip_radius);
    }
    for (const k of app.layout.kickouts) {
      circle(k.active ? '#ff00ff' : '#6e6e6e', k.center, k.field_radius);
      circle(k.active ? '#ff00ff' : '#6e6e6e', k.center, k.capture_radius);
    }
  }
}

async function showSplash(canvas, png) {
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!png) return;
  try {
    const bitmap = await createImageBitmap(new Blob([png], { type: 'image/png' }));
    const scale = Math.min(window.devicePixelRatio || 1, canvas.width / bitmap.width, canvas.height / bitmap.height);
    const w = Math.round(bitmap.width * scale);
    const h = Math.round(bitmap.height * scale);
    ctx.drawImage(bitmap, Math.floor((canvas.width - w) / 2), Math.floor((canvas.height - h) / 2), w, h);
  } catch (err) {
    // no splash, as in the original when the bitmap can't be loaded
  }
}

async function main() {
  const canvas = document.getElementById('screen');
  const status = document.getElementById('status');
  canvas.width = Math.max(1, Math.round(canvas.clientWidth * (window.devicePixelRatio || 1)));
  canvas.height = Math.max(1, Math.round(canvas.clientHeight * (window.devicePixelRatio || 1)));
  try {
    const raw = await inflate(document.getElementById('pinball-data').textContent);
    const data = loadGameData(unpack(raw));
    await showSplash(canvas, data.splash);
    await new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
    const shell = new Shell(canvas, data);
    status.remove();
    const loop = () => {
      shell.frame();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
    window.spaceCadet = shell;
  } catch (err) {
    status.textContent = `Could not start the game: ${err && err.message ? err.message : err}`;
    throw err;
  }
}

main();

export { Shell };
