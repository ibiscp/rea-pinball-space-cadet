// Port of vec2.py: minimal 2D vector math for the physics engine.

import { hypot, sin, cos, pyRound } from './pymath.js';

class Vec2 {
  constructor(x = 0.0, y = 0.0) {
    this.x = x;
    this.y = y;
  }

  add(o) {
    return new Vec2(this.x + o.x, this.y + o.y);
  }

  sub(o) {
    return new Vec2(this.x - o.x, this.y - o.y);
  }

  mul(s) {
    return new Vec2(this.x * s, this.y * s);
  }

  neg() {
    return new Vec2(-this.x, -this.y);
  }

  dot(o) {
    return this.x * o.x + this.y * o.y;
  }

  cross(o) {
    return this.x * o.y - this.y * o.x;
  }

  length() {
    return hypot(this.x, this.y);
  }

  lengthSq() {
    return this.x * this.x + this.y * this.y;
  }

  normalized() {
    const length = this.length();
    if (length < 1e-9) return new Vec2(0.0, 0.0);
    return new Vec2(this.x / length, this.y / length);
  }

  normal() {
    return new Vec2(-this.y, this.x);
  }

  rotated(radians) {
    const c = cos(radians);
    const s = sin(radians);
    return new Vec2(this.x * c - this.y * s, this.x * s + this.y * c);
  }

  asIntTuple() {
    return [pyRound(this.x), pyRound(this.y)];
  }

  copy() {
    return new Vec2(this.x, this.y);
  }

  equals(o) {
    return this.x === o.x && this.y === o.y;
  }
}

export { Vec2 };
