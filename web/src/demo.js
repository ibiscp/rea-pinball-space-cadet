// Port of demo.py: the attract-mode player (FUN_0101a2b5 / FUN_01017074 /
// FUN_01016f21).

import { TripLine } from './geometry.js';
import { taggedFloats } from './partout.js';
import { rng } from './rng.js';
import { Vec2 } from './vec2.js';

const LEFT_ZONE = 1400;
const LEFT_TIP = 1401;
const RIGHT_ZONE = 1402;
const RIGHT_TIP = 1403;
const PLUNGER_LINE = 1404;

function rand01() {
  return rng.randrange(32768) * 3.051851e-5;
}

function around(centre, spread) {
  return (centre + spread) - (spread + spread) * rand01();
}

class DemoPlayer {
  constructor(timers, send, restart, o = {}) {
    this.timers = timers;
    this.send = send;
    this.restart = restart;
    this.flip_delay = o.flip_delay ?? [0.2, 0.1];
    this.hold_time = o.hold_time ?? [0.2, 0.1];
    this.name = 'demo';
    this.active = false;
    this.data = 0;
    this.left_up = 0;
    this.right_up = 0;
    this._left_pending = 0;
    this._right_pending = 0;
    this._plunger = 0;
    this._restart = 0;
    this.lines = [];
  }

  cross(tag) {
    if (tag === LEFT_ZONE) {
      if (!this._left_pending && !this.left_up) {
        this._left_pending = this.timers.schedule(around(...this.flip_delay), () => this._flipLeft());
      }
    } else if (tag === LEFT_TIP) {
      this._flipLeft();
    } else if (tag === RIGHT_ZONE) {
      if (!this._right_pending && !this.right_up) {
        this._right_pending = this.timers.schedule(around(...this.flip_delay), () => this._flipRight());
      }
    } else if (tag === RIGHT_TIP) {
      this._flipRight();
    } else if (tag === PLUNGER_LINE && !this._plunger) {
      this.send(0x3ec);
      this._plunger = this.timers.schedule(rand01() + 2.0, () => this._releasePlunger());
    }
  }

  _flipLeft() {
    if (this.left_up) return;
    if (this._left_pending) {
      this.timers.cancel(this._left_pending);
      this._left_pending = 0;
    }
    this.send(1000);
    this.left_up = 1;
    this.timers.schedule(around(...this.hold_time), () => this._dropLeft());
  }

  _flipRight() {
    if (this.right_up) return;
    if (this._right_pending) {
      this.timers.cancel(this._right_pending);
      this._right_pending = 0;
    }
    this.send(0x3ea);
    this.right_up = 1;
    this.timers.schedule(around(...this.hold_time), () => this._dropRight());
  }

  _dropLeft() {
    if (this.left_up) this.send(0x3e9);
    this.left_up = 0;
  }

  _dropRight() {
    if (this.right_up) this.send(0x3eb);
    this.right_up = 0;
  }

  _releasePlunger() {
    this._plunger = 0;
    this.send(0x3ed);
  }

  _startNext() {
    this._restart = 0;
    this.restart();
  }

  message(code, value = 0.0) {
    if (code === 0x3f6) {
      if (this._restart) this.timers.cancel(this._restart);
      this._restart = 0;
    } else if (code === 0x3fe) {
      if (this._restart) this.timers.cancel(this._restart);
      this._restart = 0;
      if (this.active) this._restart = this.timers.schedule(5.0, () => this._startNext());
    } else if (code === 0x400) {
      for (const handle of [this._left_pending, this._right_pending]) if (handle) this.timers.cancel(handle);
      this._left_pending = 0;
      this._right_pending = 0;
      if (this.left_up) this._dropLeft();
      if (this.right_up) this._dropRight();
      if (this._plunger) this._releasePlunger();
    }
    return 0;
  }
}

function edges(values) {
  const count = Math.trunc(values[0]);
  const points = [];
  for (let i = 0; i < count; i++) points.push(new Vec2(values[1 + 2 * i], values[2 + 2 * i]));
  if (count === 2) return [[points[0], points[1]]];
  const loop = points.slice(0, -1);
  return loop.map((p, i) => [p, loop[(i + 1) % loop.length]]);
}

function buildDemo(entry, timers, send, restart, mask, ballRadius) {
  const t = taggedFloats(entry, 407);
  const times = t && t.length ? t : [0.2, 0.1, 0.2, 0.1];
  const demo = new DemoPlayer(timers, send, restart, { flip_delay: [times[0], times[1]], hold_time: [times[2], times[3]] });
  for (const tag of [LEFT_ZONE, LEFT_TIP, RIGHT_ZONE, RIGHT_TIP, PLUNGER_LINE]) {
    const values = taggedFloats(entry, tag);
    if (!values || !values.length) continue;
    for (const [a, b] of edges(values)) {
      let ln = new TripLine(a, b, mask, () => demo.cross(tag), () => demo.active);
      if (tag === PLUNGER_LINE) ln = ln.offset(ballRadius);
      demo.lines.push(ln);
    }
  }
  return demo;
}

export { DemoPlayer, buildDemo };
