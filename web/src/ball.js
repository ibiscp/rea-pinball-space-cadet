// Port of ball.py.

import { Vec2 } from './vec2.js';

class Ball {
  constructor(position, opts = {}) {
    this.position = position;
    this.velocity = opts.velocity ?? new Vec2(0.0, 0.0);
    this.radius = opts.radius ?? 12.0;
    this.alive = opts.alive ?? true;
    this.mask = 1;
    this.held = false;
    this.z = 0.0;
    this.z_velocity = 0.0;
    this.ramp_gravity = new Vec2(0.0, 0.0);
    if (this.z === 0.0) this.z = this.radius;
  }

  speed() {
    return this.velocity.length();
  }
}

export { Ball };
