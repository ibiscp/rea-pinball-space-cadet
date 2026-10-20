// Port of logic.py: the original's timers (FUN_010074b7 / FUN_01007659 /
// FUN_0100758d), the notification bus (FUN_01011ec9), lights
// (FUN_01009ae3) and light groups (FUN_0100a166).

import { rng } from './rng.js';

const MAX_TIMERS = 150;

class Timers {
  constructor() {
    this.now_ms = 0;
    this._ms_carry = 0.0;
    this._queue = [];
    this._next = 1;
  }

  get now() {
    return this.now_ms / 1000.0;
  }

  get count() {
    return this._queue.length;
  }

  schedule(delay, callback) {
    if (this._queue.length >= MAX_TIMERS) return 0;
    const expiry = this.now_ms + Math.trunc(delay * 1000.0);
    let k = 0;
    while (k < this._queue.length && this._queue[k][0] <= expiry) k += 1;
    const handle = this._next;
    this._next += 1;
    this._queue.splice(k, 0, [expiry, handle, callback]);
    return handle;
  }

  cancel(handle) {
    for (let k = 0; k < this._queue.length; k++) {
      if (this._queue[k][1] === handle) {
        this._queue.splice(k, 1);
        return;
      }
    }
  }

  advance(ms) {
    this.now_ms += ms;
  }

  update(dt) {
    this._ms_carry += dt * 1000.0;
    const ms = Math.trunc(this._ms_carry);
    this._ms_carry -= ms;
    this.advance(ms);
    this.fire();
  }

  fire() {
    let fired = 0;
    while (this._queue.length && this._queue[0][0] <= this.now_ms && fired < 2) {
      fired += 1;
      this._queue.shift()[2]();
    }
    while (this._queue.length && this._queue[0][0] + 100 <= this.now_ms) {
      fired += 1;
      this._queue.shift()[2]();
    }
    return fired;
  }
}

class Bus {
  constructor() {
    this.listeners = new Map();
    this.mission = null;
  }

  hasListener(name) {
    return this.listeners.has(name);
  }

  notify(code, obj) {
    const handler = this.listeners.get(obj && obj.name !== undefined ? obj.name : '');
    if (handler !== undefined) handler(code, obj);
    if (this.mission !== null) this.mission(code, obj);
  }
}

class Light {
  constructor(name, timers, bus, o = {}) {
    this.name = name;
    this.timers = timers;
    this.bus = bus;
    this.frames = o.frames ?? 1;
    this.base_times = o.base_times ?? [0.1, 0.1];
    this.state = 0;
    this.flashing = 0;
    this.temp_off = 0;
    this.temp_on = 0;
    this.off_after = 0;
    this.frame = 0;
    this.data = 0;
    this.shown = null;
    this.flash_times = [...this.base_times];
    this._timer = 0;
    this._timer2 = 0;
    this._blink_timer = 0;
    this._phase = 0;
    this._on_frame = 0;
  }

  _bitmap(index) {
    return index === 1 ? this._on_frame : null;
  }

  _show(index) {
    this.shown = this._bitmap(index);
  }

  _blinkToggle() {
    this._phase = 1 - this._phase;
    this._show(this._phase);
    this._blink_timer = this.timers.schedule(this.flash_times[this._phase], () => this._blinkToggle());
  }

  _startBlink(phase) {
    this._phase = phase;
    this._blinkToggle();
  }

  _stopBlink(phase) {
    if (this._blink_timer) this.timers.cancel(this._blink_timer);
    this._blink_timer = 0;
    if (phase >= 0) {
      this._phase = phase;
      this._show(phase);
    }
  }

  _setTimed(seconds) {
    this.flash_times = [...this.base_times];
    if (this._timer) this.timers.cancel(this._timer);
    this._timer = 0;
    if (seconds > 0) this._timer = this.timers.schedule(seconds, () => this._timedEnd());
  }

  _timedEnd() {
    if (this.flashing) this._stopBlink(-1);
    this._show(this.state);
    this.temp_off = 0;
    this.temp_on = 0;
    this.flashing = 0;
    this._timer = 0;
    if (this.off_after) {
      this.off_after = 0;
      this.message(0x14);
    }
    if (this.bus.hasListener(this.name)) this.bus.notify(0x3c, this);
  }

  reset() {
    if (this._timer) this.timers.cancel(this._timer);
    if (this._timer2) this.timers.cancel(this._timer2);
    if (this.flashing) this._stopBlink(-1);
    this._timer = 0;
    this._timer2 = 0;
    this.state = 0;
    this.frame = 0;
    this.temp_off = 0;
    this.temp_on = 0;
    this.flashing = 0;
    this.off_after = 0;
    this.shown = null;
    this._on_frame = 0;
    this.data = 0;
  }

  lit() {
    return Boolean(this.state || this.temp_on || this.flashing);
  }

  message(code, value = 0.0) {
    if (code > 0x3fc) {
      if (code === 0x400) this.reset();
      return 0;
    }
    if (code === 0x3fc) return 0;
    if (code === 0 || code === 1) {
      this.state = code;
      if (!(this.flashing || this.temp_off || this.temp_on)) this._show(code);
    } else if (code === 2) {
      return this.state;
    } else if (code === 3) {
      return this.flashing;
    } else if (code === 4) {
      this._setTimed(0.0);
      if (!this.flashing || !this._blink_timer) {
        this.flashing = 1;
        this.temp_on = 0;
        this.temp_off = 0;
        this.off_after = 0;
        this._startBlink(this.state);
      }
    } else if (code === 5) {
      this.flash_times = [value * this.base_times[0], value * this.base_times[1]];
    } else if (code === 6) {
      this.flash_times = [...this.base_times];
    } else if (code === 7) {
      if (!this.flashing) this._startBlink(this.state);
      this.flashing = 1;
      this.temp_on = 0;
      this.off_after = 0;
      this.temp_off = 0;
      this._setTimed(value);
    } else if (code === 8) {
      if (!this.temp_off) {
        if (!this.flashing) {
          this._show(0);
        } else {
          this._stopBlink(0);
          this.flashing = 0;
        }
        this.temp_off = 1;
        this.temp_on = 0;
      }
      this._setTimed(value);
    } else if (code === 9) {
      if (!this.temp_on) {
        if (!this.flashing) {
          this._show(1);
        } else {
          this._stopBlink(1);
          this.flashing = 0;
        }
        this.temp_on = 1;
        this.temp_off = 0;
      }
      this._setTimed(value);
    } else if (code === 0xb) {
      this.frame = Math.max(0, Math.min(Math.trunc(value), this.frames - 1));
      this._on_frame = this.frame;
      let index;
      if (this.flashing) index = this._phase;
      else if (this.temp_off) index = 0;
      else if (this.temp_on) index = 1;
      else index = this.state;
      this._show(index);
    } else if (code === 0xc) {
      this.message(0xb, Math.min(this.frame + 1, this.frames - 1));
    } else if (code === 0xd) {
      this.message(0xb, Math.max(this.frame - 1, 0));
    } else if (code === 0xe) {
      if (this._timer) this.timers.cancel(this._timer);
      this._timer = 0;
      if (this.flashing) this._stopBlink(-1);
      this.flashing = 0;
      this.temp_off = 0;
      this.temp_on = 0;
      this._show(this.state);
    } else if (code === 0xf) {
      this.off_after = 0;
      if (this._timer2) this.timers.cancel(this._timer2);
      this._timer2 = 0;
      this.message(1);
      this.message(7, value);
    } else if (code === 0x10) {
      if (this._timer2) this.timers.cancel(this._timer2);
      this._timer2 = 0;
      this.message(7, value);
      this.off_after = 1;
    } else if (code === 0x11) {
      this.message(Math.trunc(value) !== 0 ? 1 : 0);
      return this.state;
    } else if (code === 0x12) {
      this.message(0x11, value);
      this.message(0xe);
      return this.state;
    } else if (code === 0x13) {
      this.message(1);
      this.message(0xe);
    } else if (code === 0x14) {
      this.message(0);
      this.message(0xe);
    } else if (code === 0x15) {
      this.message(0x11, this.state === 0 ? 1.0 : 0.0);
      return this.state;
    } else if (code === 0x16) {
      this.message(0x12, this.state === 0 ? 1.0 : 0.0);
      return this.state;
    } else if (code === 0x17) {
      this.data = Math.trunc(value);
    }
    return 0;
  }
}

class LightGroup {
  constructor(name, timers, bus, lights, o = {}) {
    this.name = name;
    this.timers = timers;
    this.bus = bus;
    this.lights = lights;
    this.interval = o.interval ?? 0.1;
    this.data = 0;
    this.animation = 0;
    this.rotating = 0;
    this._step = 0.0;
    this._timer = 0;
    this._timer2 = 0;
  }

  reset() {
    for (const handle of [this._timer, this._timer2]) {
      if (handle) this.timers.cancel(handle);
    }
    this._timer = 0;
    this._timer2 = 0;
    this.animation = 0;
    this.rotating = 0;
    this._step = this.interval;
  }

  lit() {
    return this.lights.some((light) => light.lit());
  }

  _scheduleStep(value) {
    if (this._timer) this.timers.cancel(this._timer);
    this._timer = 0;
    if (value <= 0.0) {
      if (value === 0.0) {
        this.animation = 0;
        this.rotating = 0;
        return;
      }
      this._step = this.interval;
    } else {
      this._step = value;
    }
    this._timer = this.timers.schedule(this._step, () => this._animate());
  }

  _animate() {
    this._timer = 0;
    this.message(this.animation, this._step);
  }

  _holdStates() {
    for (let i = this.lights.length - 1; i >= 0; i--) {
      const light = this.lights[i];
      light.message(light.state ? 9 : 8);
    }
  }

  _firstOff() {
    return this.lights.findIndex((light) => !light.state);
  }

  _lastOn() {
    for (let i = this.lights.length - 1; i >= 0; i--) if (this.lights[i].state) return i;
    return -1;
  }

  _busy(light) {
    return Boolean(light.flashing || light.temp_on || light.temp_off);
  }

  message(code, value = 0.0) {
    const lights = this.lights;
    const n = lights.length;
    if (code > 0x3f1) {
      if (code === 0x3f3 || code === 0x3fc || code === 0x3fe) return 0;
      if (code === 0x400) {
        this.reset();
        return 0;
      }
      return this._broadcast(code, value);
    }
    if (code === 0x3f0 || code === 0x3f1) return 0;
    if (code === 0x18 || code === 0x19) {
      if (this._busy(lights[n - 1])) return 0;
      if (this.animation) this.message(0x22);
      this.rotating = 1;
      this.animation = code;
      const source = code === 0x18 ? lights[n - 1] : lights[0];
      const carriedState = source.state;
      const carriedData = source.data;
      if (code === 0x18) {
        for (let i = n - 1; i > 0; i--) {
          const src = lights[i - 1];
          lights[i].message(src.state !== 0 ? 1 : 0);
          lights[i].data = src.data;
        }
      } else {
        for (let i = 0; i < n - 1; i++) {
          const src = lights[i + 1];
          lights[i].message(src.state !== 0 ? 1 : 0);
          lights[i].data = src.data;
        }
      }
      const target = code === 0x18 ? lights[0] : lights[n - 1];
      target.message(carriedState !== 0 ? 1 : 0);
      target.data = carriedData;
      this._scheduleStep(value);
    } else if (code === 0x1a || code === 0x1b) {
      if (this.rotating || !this.animation) this._holdStates();
      this.animation = code;
      this.rotating = 0;
      const carried = code === 0x1a ? lights[n - 1].temp_on : lights[0].temp_on;
      if (code === 0x1a) {
        for (let i = n - 1; i > 0; i--) lights[i].message(8 + (lights[i - 1].temp_on !== 0 ? 1 : 0));
      } else {
        for (let i = 0; i < n - 1; i++) lights[i].message(8 + (lights[i + 1].temp_on !== 0 ? 1 : 0));
      }
      const target = code === 0x1a ? lights[0] : lights[n - 1];
      target.message(8 + (carried !== 0 ? 1 : 0));
      this._scheduleStep(value);
    } else if (code === 0x1c) {
      if (this.rotating || !this.animation) this._holdStates();
      this.animation = code;
      this.rotating = 0;
      for (const light of lights.slice(0, -1)) {
        if (rng.randrange(32768) % 100 > 0x46) {
          light.message(9, rng.randrange(32768) * 3.0518509476e-5 * value * 3.0 + 0.1);
        }
      }
      this._scheduleStep(value);
    } else if (code === 0x1d) {
      if (this.rotating || !this.animation) this._holdStates();
      this.animation = code;
      this.rotating = 0;
      for (const light of lights.slice(0, -1)) {
        light.message(0x12, rng.randrange(32768) % 100 > 0x46 ? 1.0 : 0.0);
      }
      this._scheduleStep(value);
    } else if (code === 0x1e || code === 0x1f) {
      const wantOn = code === 0x1f;
      const candidates = [];
      lights.forEach((light, i) => {
        if (Boolean(light.state) === wantOn) candidates.push(i);
      });
      if (!candidates.length) return 0;
      const pick = rng.randrange(32768) % candidates.length;
      const index = candidates.slice().sort((a, b) => b - a)[pick];
      lights[index].message(wantOn ? 0 : 1);
      if (this.animation) this._holdStates();
    } else if (code === 0x20 || code === 0x21) {
      const index = code === 0x20 ? this._firstOff() : this._lastOn();
      if (index < 0) return 0;
      lights[index].message(code === 0x20 ? 1 : 0);
      if (this.animation) this._holdStates();
      return 1;
    } else if (code === 0x22) {
      if (this._timer) this.timers.cancel(this._timer);
      this._timer = 0;
      if (this.animation === 0x1a || this.animation === 0x1b || this.animation === 0x1c) this._broadcast(0xe, 0.0);
      this.animation = 0;
      this.rotating = 0;
    } else if (code === 0x23 || code === 0x24) {
      const index = Math.trunc(value);
      if (!(index >= 0 && index < n)) return 0;
      lights[index].message(code === 0x23 ? 1 : 0);
      if (this.animation) this._holdStates();
    } else if (code === 0x25) {
      return lights.filter((light) => light.state).length;
    } else if (code === 0x26) {
      return n;
    } else if (code === 0x27) {
      return this.animation;
    } else if (code === 0x28) {
      return this.rotating;
    } else if (code === 0x29 || code === 0x2a) {
      const index = code === 0x29 ? this._firstOff() : this._lastOn();
      if (index < 0) return 0;
      if (this.animation || this.rotating) this.message(0x22);
      lights[index].message(code === 0x29 ? 0xf : 0x10, value);
      return 1;
    } else if (code === 0x2b) {
      if (this._timer2) this.timers.cancel(this._timer2);
      this._timer2 = 0;
      if (value > 0) this._timer2 = this.timers.schedule(value, () => this._timer2End());
    } else if (code === 0x2c) {
      for (let i = lights.length - 1; i >= 0; i--) {
        const light = lights[i];
        if (light.state) {
          light.message(0);
          light.message(0x10, value);
        }
      }
    } else if (code === 0x2d) {
      this.bus.notify(0x2d, this);
      let last = Math.trunc(value);
      if (last >= 0 && last <= n) {
        last = Math.min(last, n - 1);
        for (let i = n - 1; i >= last + 1; i--) lights[i].message(0x14);
        for (let i = last; i >= 0; i--) lights[i].message(0x13);
      }
    } else if (code === 0x2e) {
      const index = this._lastOn();
      if (index >= 0) lights[index].message(4);
    } else {
      return this._broadcast(code, value);
    }
    return 0;
  }

  _timer2End() {
    this._timer2 = 0;
    this.bus.notify(0x3d, this);
  }

  _broadcast(code, value) {
    for (let i = this.lights.length - 1; i >= 0; i--) this.lights[i].message(code, value);
    return 0;
  }
}

export { Timers, Bus, Light, LightGroup, MAX_TIMERS };
