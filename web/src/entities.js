// Port of entities.py: the table's feature objects (see each Python class
// for the decompiled source it follows).

import { sin, cos } from './pymath.js';
import { rng } from './rng.js';
import { Vec2 } from './vec2.js';

// FUN_0101ccf3, with its quirk: y' uses the already-rotated x.
function rotateLikeOriginal(v, angle) {
  const s = sin(angle);
  const co = cos(angle);
  const x = co * v.x - s * v.y;
  return new Vec2(x, s * x + co * v.y);
}

// FUN_01015935.
function launchBall(ball, direction, spread, speed, variation) {
  const turned = rotateLikeOriginal(direction, (1.0 - 2.0 * rng.random()) * spread);
  ball.velocity = turned.mul(speed + (1.0 - 2.0 * rng.random()) * speed * variation);
}

class Sink {
  constructor(name, o) {
    this.name = name;
    this.exit_position = o.exit_position;
    this.direction = o.direction;
    this.spread = o.spread;
    this.speed = o.speed;
    this.variation = o.variation;
    this.eject_delay = o.eject_delay;
    this.held_ball = null;
    this.timer = null;
    this.data = 0;
    this.notify = null;
    this.sound = null;
    this.ball_source = null;
    this.on_eject = null;
  }

  capture(ball, tilted) {
    if (tilted) return false;
    ball.held = true;
    ball.velocity = new Vec2(0.0, 0.0);
    this.held_ball = ball;
    if (this.sound) this.sound();
    if (this.notify) this.notify(0x3f, this);
    return true;
  }

  message(code, value = 0.0) {
    if (code === 0x38) {
      this.timer = value < 0 ? this.eject_delay : value;
    } else if (code === 0x400) {
      this.timer = null;
      this.data = 0;
    }
    return 0;
  }

  kickForContact(tilted) {
    return [1.0e9, 0.0];
  }

  afterBounce(impact, threshold, tilted) {}

  update(dt) {
    if (this.timer === null) return;
    this.timer -= dt;
    if (this.timer > 0) return;
    this.timer = null;
    this.held_ball = null;
    const ball = this.ball_source ? this.ball_source() : null;
    if (ball === null || !ball.alive) return;
    ball.held = false;
    ball.position = this.exit_position.copy();
    launchBall(ball, this.direction, this.spread, this.speed, this.variation);
    if (this.on_eject) this.on_eject(this);
  }
}

class WallTarget {
  constructor(name, o) {
    this.name = name;
    this.kick_threshold = o.kick_threshold;
    this.kick = o.kick;
    this.segments = [];
    this.drop_time = o.drop_time ?? 0.0;
    this.reset_delay = o.reset_delay ?? 0.25;
    this.up = true;
    this.data = 0;
    this._down_timer = 0.0;
    this._raise_timer = 0.0;
    this.notify = null;
    this.sound = null;
  }

  capture(ball, tilted) {
    return false;
  }

  kickForContact(tilted) {
    return tilted ? [1.0e9, 0.0] : [this.kick_threshold, this.kick];
  }

  afterBounce(impact, threshold, tilted) {
    if (tilted || impact <= threshold) return;
    if (this.sound) this.sound();
    this.message(0x31);
    if (this.drop_time > 0) this._down_timer = this.drop_time;
    if (this.notify) this.notify(0x3f, this);
  }

  message(code, value = 0.0) {
    if (code === 0x31) {
      this._setUp(false);
    } else if (code === 0x32) {
      if (this.drop_time > 0) this._setUp(true);
      else this._raise_timer = this.reset_delay;
    } else if (code === 0x400) {
      this.data = 0;
      this._down_timer = 0.0;
      this._raise_timer = 0.0;
      this._setUp(true);
    }
    return 0;
  }

  update(dt) {
    if (this._down_timer > 0) {
      this._down_timer -= dt;
      if (this._down_timer <= 0) this.message(0x32);
    }
    if (this._raise_timer > 0) {
      this._raise_timer -= dt;
      if (this._raise_timer <= 0) this._setUp(true);
    }
  }

  _setUp(up) {
    this.up = up;
    for (const segment of this.segments) segment.active = up;
  }
}

class Rollover {
  constructor(name, o = {}) {
    this.name = name;
    this.mask = o.mask ?? 1;
    this.armed = true;
    this.inside = false;
    this.lights_on_entry = o.lights_on_entry ?? false;
    this.light_time = o.light_time ?? 0.0;
    this.shown = !this.lights_on_entry;
    this.data = 0;
    this._rearm = 0.0;
    this._hide = null;
    this.notify = null;
    this.sound = null;
    this.tilted = () => false;
  }

  cross(ball) {
    if (this.tilted()) return;
    if (!this.inside) {
      if (this.sound) this.sound();
      if (this.notify) this.notify(0x3f, this);
      this.shown = this.lights_on_entry;
    } else {
      this._rearm = 0.1;
      this.armed = false;
      if (!this.lights_on_entry) this.shown = true;
      else if (this._hide === null) this._hide = this.light_time;
    }
    this.inside = !this.inside;
  }

  message(code, value = 0.0) {
    if (code === 0x400) {
      this.armed = true;
      this.inside = false;
      this._rearm = 0.0;
      this._hide = null;
      this.shown = !this.lights_on_entry;
    }
    return 0;
  }

  update(dt) {
    if (this._rearm > 0) {
      this._rearm -= dt;
      if (this._rearm <= 0) this.armed = true;
    }
    if (this._hide !== null) {
      this._hide -= dt;
      if (this._hide <= 0) {
        this._hide = null;
        this.shown = false;
      }
    }
  }
}

class Flag {
  constructor(name, o) {
    this.name = name;
    this.frames = o.frames;
    this.max_rate = o.max_rate;
    this.min_rate = o.min_rate;
    this.decay = o.decay;
    this.schedule = null;
    this.frame = 0;
    this.direction = 1;
    this.rate = 0.0;
    this.data = 0;
    this.notify = null;
    this.sound = null;
    this.tilted = () => false;
  }

  cross(ball, reverse) {
    this.direction = reverse ? -1 : 1;
    const speed = ball.speed();
    this.rate = speed !== 0.0 ? speed * 20.0 : this.min_rate;
    this.rate = Math.min(Math.max(this.rate, this.min_rate), this.max_rate);
    this.step();
  }

  step() {
    this.frame += this.direction;
    if (this.frame >= this.frames) this.frame = 0;
    else if (this.frame < 0) this.frame = this.frames - 1;
    if (!this.tilted()) {
      if (this.notify) this.notify(0x3f, this);
      if (this.sound) this.sound();
      if (this.frame === 0 && this.notify) this.notify(0x3e, this);
    }
    this.rate *= this.decay;
    if (this.min_rate <= this.rate && this.schedule !== null) this.schedule(1.0 / this.rate, () => this.step());
  }

  message(code, value = 0.0) {
    if (code === 0x400) this.frame = 0;
    return 0;
  }
}

class PassLine {
  constructor(name) {
    this.name = name;
    this.data = 0;
    this.notify = null;
    this.sound = null;
    this.tilted = () => false;
  }

  cross(ball) {
    if (this.tilted()) return;
    if (this.sound) this.sound();
    if (this.notify) this.notify(0x3f, this);
  }

  message(code, value = 0.0) {
    return 0;
  }
}

class WallSwitch {
  constructor(name, o) {
    this.name = name;
    this.kick_threshold = o.kick_threshold;
    this.kick = o.kick;
    this.lit = false;
    this._hide_timers = [];
    this.data = 0;
    this.notify = null;
    this.sound = null;
    this.soft_sound = null;
  }

  capture(ball, tilted) {
    return false;
  }

  kickForContact(tilted) {
    return tilted ? [1.0e9, 0.0] : [this.kick_threshold, this.kick];
  }

  afterBounce(impact, threshold, tilted) {
    if (tilted) return;
    if (impact > threshold) {
      if (this.sound) this.sound();
      this.lit = true;
      this._hide_timers.push(0.1);
      if (this.notify) this.notify(0x3f, this);
    } else if (impact > 0.2 && this.soft_sound) {
      this.soft_sound();
    }
  }

  update(dt) {
    const remaining = this._hide_timers.map((t) => t - dt);
    if (remaining.some((t) => t <= 0)) this.lit = false;
    this._hide_timers = remaining.filter((t) => t > 0);
  }

  message(code, value = 0.0) {
    if (code === 0x400 && this._hide_timers.length) {
      this._hide_timers.pop();
      this.lit = false;
    }
    return 0;
  }
}

class CenterPost {
  constructor(name, segments) {
    this.name = name;
    this.segments = segments;
    this.up_time = 55.0;
    this.warn_time = 5.0;
    this.up = false;
    this.data = 0;
    this._timer = null;
    this.notify = null;
  }

  message(code, value = 0.0) {
    if (code === 0x33 || code === 0x3f3 || code === 0x3fc || code === 0x400) {
      this._timer = null;
      this.data = 0;
      this._setUp(false);
    } else if (code === 0x34 || code === 0x3b) {
      if (code === 0x34) this._setUp(true);
      this._timer = Math.max(value, 0.0);
    }
    return 0;
  }

  _setUp(up) {
    this.up = up;
    for (const segment of this.segments) segment.active = up;
  }

  update(dt) {
    if (this._timer === null) return;
    this._timer -= dt;
    if (this._timer <= 0) {
      this._timer = null;
      if (this.notify) this.notify(0x3c, this);
    }
  }
}

class Kickout {
  constructor(name, o) {
    this.name = name;
    this.center = o.center;
    this.field_radius = o.field_radius;
    this.capture_radius = o.capture_radius;
    this.strength = o.strength;
    this.direction = o.direction;
    this.spread = o.spread;
    this.speed = o.speed;
    this.variation = o.variation;
    this.eject_delay = o.eject_delay ?? 1.5;
    this.rearm_delay = o.rearm_delay ?? 0.05;
    this.active = o.active ?? true;
    this.mask = o.mask ?? 1;
    this.stays_off = o.stays_off ?? false;
    this.hold_z = null;
    this.held_ball = null;
    this.data = 0;
    this._eject_timer = null;
    this._rearm_timer = null;
    this.notify = null;
    this.sound = null;
  }

  accel(ball) {
    if (!this.active || this.held_ball !== null || !(this.mask & ball.mask)) return null;
    const toCenter = this.center.sub(ball.position);
    if (toCenter.lengthSq() >= this.field_radius * this.field_radius) return null;
    return toCenter.normalized().mul(this.strength).sub(ball.velocity);
  }

  canCapture(ball) {
    return this.active && this.held_ball === null && Boolean(this.mask & ball.mask);
  }

  tryCapture(ball, tilted, force = false) {
    if (!this.canCapture(ball)) return false;
    if (!force && ball.position.sub(this.center).length() >= this.capture_radius) return false;
    ball.held = true;
    ball.velocity = new Vec2(0.0, 0.0);
    ball.position = this.center.copy();
    if (this.hold_z !== null) ball.z = this.hold_z;
    this.held_ball = ball;
    if (tilted) {
      this.message(0x37, 0.1);
    } else {
      if (this.sound) this.sound();
      if (this.notify) this.notify(0x3f, this);
    }
    return true;
  }

  message(code, value = 0.0) {
    if (code === 0x37) {
      if (this.held_ball !== null) this._eject_timer = value < 0 ? this.eject_delay : value;
    } else if (code === 0x3f3 || code === 0x400) {
      if (code === 0x400 && this.held_ball !== null) {
        this._eject_timer = 0.0;
        this.update(0.0);
      }
      if (this.stays_off) this.active = false;
    }
    return 0;
  }

  update(dt) {
    if (this._rearm_timer !== null) {
      this._rearm_timer -= dt;
      if (this._rearm_timer <= 0) {
        this._rearm_timer = null;
        if (!this.stays_off) this.active = true;
      }
    }
    if (this._eject_timer === null) return;
    this._eject_timer -= dt;
    if (this._eject_timer > 0) return;
    this._eject_timer = null;
    const ball = this.held_ball;
    this.held_ball = null;
    if (ball === null || !ball.alive) return;
    ball.held = false;
    ball.z = ball.radius;
    launchBall(ball, this.direction, this.spread, this.speed, this.variation);
    this.active = false;
    if (!this.stays_off) this._rearm_timer = this.rearm_delay;
  }
}

class RampTriangle {
  constructor(plane, vertices, gravity) {
    this.plane = plane;
    this.vertices = vertices;
    this.gravity = gravity;
  }
}

class Ramp {
  constructor(name, o) {
    this.name = name;
    this.mask = o.mask;
    this.friction = o.friction;
    this.bounds = o.bounds;
    this.triangles = o.triangles ?? [];
    this.set_height_on_exit = o.set_height_on_exit ?? false;
    this.grid = o.grid ?? null;
    this.cells = o.cells ?? new Set();
    this.data = 0;
    this.notify = null;
    this.tilted = () => false;
  }

  accel(ball) {
    if (!(this.mask & ball.mask)) return null;
    if (this.grid !== null) {
      if (!this.cells.has(this.grid.cellOf(ball.position))) return null;
    } else {
      const [minX, minY, maxX, maxY] = this.bounds;
      if (!(minX <= ball.position.x && ball.position.x <= maxX && minY <= ball.position.y && ball.position.y <= maxY)) {
        return null;
      }
    }
    return ball.ramp_gravity.sub(ball.velocity.mul(this.friction));
  }

  enter(ball, triangle) {
    const [a, b, cc] = triangle.plane;
    ball.ramp_gravity = triangle.gravity.copy();
    ball.z = a * ball.position.x + b * ball.position.y + cc + ball.radius;
    ball.mask = this.mask;
  }

  leave(ball, layerMask, height) {
    ball.mask = layerMask;
    if (this.set_height_on_exit) ball.z = ball.radius + height;
  }

  scoreLine(ball) {
    if (!this.tilted() && this.notify) this.notify(0x3f, this);
  }
}

class RampHole {
  constructor(name, o) {
    this.name = name;
    this.center = o.center;
    this.field_radius = o.field_radius;
    this.capture_radius = o.capture_radius;
    this.strength = o.strength;
    this.mask = o.mask;
    this.drop_friction = o.drop_friction;
    this.floor_z = o.floor_z;
    this.exit_mask = o.exit_mask;
    this.gravity_magnitude = o.gravity_magnitude;
    this.drop_delay = 0.5;
    this.held_ball = null;
    this.dropping = false;
    this.data = 0;
    this._timer = null;
    this.notify = null;
  }

  accel(ball) {
    if (this.held_ball !== null || !(this.mask & ball.mask)) return null;
    const toCenter = this.center.sub(ball.position);
    if (toCenter.lengthSq() > this.field_radius * this.field_radius) return null;
    return toCenter.normalized().mul(this.strength).sub(ball.velocity);
  }

  canCapture(ball) {
    return this.held_ball === null && Boolean(this.mask & ball.mask);
  }

  tryCapture(ball, tilted, force = false) {
    if (!this.canCapture(ball)) return false;
    if (!force && ball.position.sub(this.center).length() >= this.capture_radius) return false;
    ball.held = true;
    ball.velocity = new Vec2(0.0, 0.0);
    ball.position = this.center.copy();
    ball.z_velocity = 0.0;
    this.held_ball = ball;
    this.dropping = false;
    this._timer = this.drop_delay;
    if (this.notify && !tilted) this.notify(0x39, this);
    return true;
  }

  update(dt) {
    const ball = this.held_ball;
    if (ball === null) return;
    if (this._timer !== null) {
      this._timer -= dt;
      if (this._timer <= 0) {
        this._timer = null;
        this.dropping = true;
      }
    }
    if (!this.dropping) return;
    ball.z_velocity -= this.gravity_magnitude * dt * this.drop_friction;
    ball.z += ball.z_velocity;
    if (ball.z > this.floor_z) return;
    ball.z = this.floor_z;
    ball.z_velocity = 0.0;
    ball.mask = this.exit_mask;
    ball.velocity = new Vec2(0.0, 0.0);
    ball.held = false;
    this.held_ball = null;
    this.dropping = false;
    if (this.notify) this.notify(0x3a, this);
  }
}

class Plunger {
  constructor(o) {
    this.step = o.step;
    this.max_kick = o.max_kick ?? 100.0;
    this.tick = o.tick ?? 0.025;
    this.kick = 0.0;
    this.threshold = 1.0e9;
    this.pulling = false;
    this._pull_timer = 0.0;
    this._reset_timer = null;
  }

  capture(ball, tilted) {
    return false;
  }

  kickForContact(tilted) {
    if (tilted) {
      this.threshold = 0.0;
      this.kick = this.max_kick;
      this._reset_timer = 0.2;
    }
    return [this.threshold, this.kick * (1.0 + rng.random() * 0.1)];
  }

  afterBounce(impact, threshold, tilted) {}

  press() {
    if (this.pulling) return;
    this.pulling = true;
    this.threshold = 1.0e9;
    this._reset_timer = null;
    this.kick = Math.min(this.max_kick, this.step);
    this._pull_timer = this.tick;
  }

  release() {
    if (!this.pulling) return;
    this.pulling = false;
    this.threshold = 0.0;
    this._reset_timer = this.tick;
  }

  autoLaunch() {
    this.pulling = false;
    this.threshold = 0.0;
    this.kick = this.max_kick;
    this._reset_timer = 0.2;
  }

  update(dt) {
    if (this.pulling && this.kick < this.max_kick) {
      this._pull_timer -= dt;
      while (this._pull_timer <= 0 && this.kick < this.max_kick) {
        this.kick = Math.min(this.max_kick, this.kick + this.step);
        this._pull_timer += this.tick;
      }
    }
    if (this._reset_timer !== null) {
      this._reset_timer -= dt;
      if (this._reset_timer <= 0) {
        this._reset_timer = null;
        this.threshold = 1.0e9;
        this.kick = 0.0;
      }
    }
  }
}

class Gate {
  constructor(name, segment) {
    this.name = name;
    this.segment = segment;
    this.data = 0;
    this.notify = null;
    this.open_sound = null;
    this.close_sound = null;
  }

  get is_open() {
    return !this.segment.active;
  }

  setOpen(isOpen) {
    this.segment.active = !isOpen;
  }

  message(code, value = 0.0) {
    if (code === 0x3fc) return 0;
    if (code === 0x35) {
      this.setOpen(true);
      if (this.open_sound) this.open_sound();
    } else if (code === 0x36 || code === 0x400) {
      this.setOpen(false);
      if (code === 0x36 && this.close_sound) this.close_sound();
    }
    if (this.notify) this.notify(code, this);
    return 0;
  }
}

class Kickback {
  constructor(name, o) {
    this.name = name;
    this.kick = o.kick;
    this.arm_delay = 0.7;
    this.ready_period = 0.1;
    this.threshold = 1.0e9;
    this.armed = false;
    this.timer = null;
    this.frame = 0;
    this.data = 0;
    this.notify = null;
    this.sound = null;
  }

  capture(ball, tilted) {
    return false;
  }

  kickForContact(tilted) {
    if (tilted) return [0.0, this.kick];
    if (!this.armed) {
      this.threshold = 1.0e9;
      this.armed = true;
      this.timer = this.arm_delay;
    }
    return [this.threshold, this.kick];
  }

  afterBounce(impact, threshold, tilted) {
    if (!tilted && impact > threshold) {
      this.armed = false;
      if (this.sound) this.sound();
    }
  }

  update(dt) {
    if (this.timer === null) return;
    this.timer -= dt;
    if (this.timer > 0) return;
    if (this.armed) {
      this.threshold = 0.0;
      this.timer = this.ready_period;
      this.frame = 1;
    } else {
      this.timer = null;
      this.frame = 0;
      if (this.notify) this.notify(0x3c, this);
    }
  }

  message(code, value = 0.0) {
    if (code === 0x3f3 || code === 0x400) {
      if (this.timer !== null) this.frame = null;
      this.armed = false;
      this.timer = null;
      this.threshold = 1.0e9;
    }
    return 0;
  }
}

export {
  launchBall, Sink, WallTarget, Rollover, Flag, PassLine, WallSwitch, CenterPost, Kickout, RampTriangle, Ramp,
  RampHole, Plunger, Gate, Kickback,
};
