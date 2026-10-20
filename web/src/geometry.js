// Port of geometry.py: static collision shapes and the swept tests.

import * as c from './constants.js';
import { Vec2 } from './vec2.js';

// An immovable line-segment wall (see geometry.Segment).
class Segment {
  constructor(a, b, opts = {}) {
    this.a = a;
    this.b = b;
    this.restitution = opts.restitution ?? c.WALL_RESTITUTION;
    this.tangent_retention = opts.tangent_retention ?? c.WALL_TANGENT_RETENTION;
    this.kick_threshold = opts.kick_threshold ?? c.NO_KICK_THRESHOLD;
    this.kick = opts.kick ?? 0.0;
    this.one_sided = opts.one_sided ?? false;
    this.mask = opts.mask ?? 1;
    this.active = opts.active ?? true;
    this.behavior = opts.behavior ?? null;
    this.radius_offset = opts.radius_offset ?? true;
    this._edge = null;
  }

  edge(ballRadius) {
    if (this._edge === null || this._edge[0] !== ballRadius) {
      this._edge = [ballRadius, line(this.a, this.b, this.radius_offset ? ballRadius : 0.0)];
    }
    return this._edge[1];
  }

  closestPoint(p) {
    const ab = this.b.sub(this.a);
    const lengthSq = ab.lengthSq();
    if (lengthSq < 1e-9) return this.a;
    const t = Math.max(0.0, Math.min(1.0, p.sub(this.a).dot(ab) / lengthSq));
    return this.a.add(ab.mul(t));
  }
}

// FUN_01008beb: [normal, c, lo, hi, use_y] for the line a->b moved `offset`
// along its normal (dy, -dx).
function line(a, b, offset) {
  let d = b.sub(a);
  const length = d.length();
  d = length > 0 ? d.mul(1.0 / length) : new Vec2(0.0, 0.0);
  const normal = new Vec2(d.y, -d.x);
  a = a.add(normal.mul(offset));
  b = b.add(normal.mul(offset));
  let useY;
  let lo;
  let hi;
  if (Math.abs(d.x) >= 1e-9) {
    useY = false;
    lo = Math.min(a.x, b.x);
    hi = Math.max(a.x, b.x);
  } else {
    useY = true;
    lo = Math.min(a.y, b.y);
    hi = Math.max(a.y, b.y);
  }
  return [normal, -normal.dot(a), lo, hi, useY];
}

// FUN_01008c8f: distance along the ray to the line, or null.
function lineHit(origin, direction, length, tolerance, ln) {
  const [normal, cc, lo, hi, useY] = ln;
  const denom = direction.dot(normal);
  if (denom >= 0.0) return null;
  const t = -(origin.dot(normal) + cc) / denom;
  if (t < -tolerance || t > length) return null;
  const contact = useY ? origin.y + direction.y * t : origin.x + direction.x * t;
  if (contact < lo || contact > hi) return null;
  return t;
}

// FUN_01008b34: distance along the ray to the circle, or null.
function circleHit(origin, direction, length, center, radiusSq) {
  const toCenter = center.sub(origin);
  const along = toCenter.dot(direction);
  if (along < 0.0) return null;
  const distSq = toCenter.lengthSq();
  if (distSq < radiusSq) return along - Math.sqrt(along * along + (radiusSq - distSq));
  const disc = along * along + (radiusSq - distSq);
  if (disc < 0.0) return null;
  const t = along - Math.sqrt(disc);
  if (t < 0.0 || t > length) return null;
  return t;
}

// A bare line whose crossing only changes state (geometry.TripLine).
class TripLine {
  constructor(a, b, mask, onCross, active = null) {
    this.a = a;
    this.b = b;
    this.mask = mask;
    this.on_cross = onCross;
    this.active = active;
    this._edgeCache = null;
  }

  edge() {
    return line(this.a, this.b, 0.0);
  }

  offset(distance) {
    const d = this.b.sub(this.a).normalized();
    const shift = new Vec2(d.y, -d.x).mul(distance);
    return new TripLine(this.a.add(shift), this.b.add(shift), this.mask, this.on_cross, this.active);
  }
}

// An immovable circular obstacle (geometry.Circle).
class Circle {
  constructor(center, radius, opts = {}) {
    this.center = center;
    this.radius = radius;
    this.restitution = opts.restitution ?? c.WALL_RESTITUTION;
    this.tangent_retention = opts.tangent_retention ?? c.WALL_TANGENT_RETENTION;
    this.kick_threshold = opts.kick_threshold ?? c.NO_KICK_THRESHOLD;
    this.kick = opts.kick ?? 0.0;
    this.mask = opts.mask ?? 1;
    this.behavior = opts.behavior ?? null;
    this.wall = opts.wall ?? null;
    this.on_hit = opts.on_hit ?? null;
    this.cooldown = opts.cooldown ?? 0.0;
    this._cooldown_remaining = 0.0;
    this.name = opts.name ?? '';
  }
}

export { Segment, TripLine, Circle, line, lineHit, circleHit };
