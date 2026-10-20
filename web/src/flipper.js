// Port of flipper.py: the flipper's collision edge (FUN_0101c2ba,
// FUN_0101bf98, FUN_0101b1f7, FUN_0101b327/FUN_0101b281, FUN_0101b825,
// FUN_0101b5a8, FUN_0101b43a, FUN_0101be06).

import { line, circleHit, lineHit } from './geometry.js';
import { sin, cos, acos } from './pymath.js';
import { Vec2 } from './vec2.js';

const NO_KICK = 1e9;

function rotate(p, pivot, s, c) {
  const dx = p.x - pivot.x;
  const dy = p.y - pivot.y;
  return new Vec2(dx * c - dy * s + pivot.x, dy * c + dx * s + pivot.y);
}

class Flipper {
  constructor(o) {
    this.pivot = o.pivot;
    this.radius = o.radius;
    this.rest_tip = o.rest_tip;
    this.tip_radius = o.tip_radius;
    this.extended_tip = o.extended_tip;
    this.up_time = o.up_time;
    this.down_time = o.down_time;
    this.ball_radius = o.ball_radius;
    this.kick_factor = o.kick_factor ?? 0.9;
    this.restitution = o.restitution ?? 0.75;
    this.tangent_retention = o.tangent_retention ?? 0.5;
    this.mask = o.mask ?? 1;
    this.is_left = o.is_left ?? true;
    this.pressed = false;
    this.cells = new Set();
    this.state = 0;
    this.start_angle = 0.0;
    this.target_angle = 0.0;
    this.start_time = 0.0;
    this.end_time = 0.0;
    this.duration = 0.0;
    this.skip_next = false;
    this.leading = false;
    this.trailing = false;
    this.face_normal = new Vec2();
    this.contact = new Vec2();
    this.normal = new Vec2();

    const r1 = this.radius + this.ball_radius;
    const r2 = this.tip_radius + this.ball_radius;
    this._r1 = r1;
    this._r2 = r2;
    this._r1_sq = r1 * r1;
    this._r2_sq = r2 * r2;
    this._inner1_sq = (r1 * 1.01) * (r1 * 1.01);
    this._inner2_sq = (r2 * 1.01) * (r2 * 1.01);
    const u = this.rest_tip.sub(this.pivot).normalized();
    const e = this.extended_tip.sub(this.pivot).normalized();
    const swing = acos(Math.max(-1.0, Math.min(1.0, u.dot(e))));
    this.swing = u.x * e.y - e.x * u.y < 0.0 ? -swing : swing;
    const n = new Vec2(-u.y, u.x);
    let p65 = this.rest_tip.add(n.mul(r2));
    let p71 = this.pivot.add(n.mul(r1));
    let p7d = this.pivot.sub(n.mul(r1));
    let p89 = this.rest_tip.sub(n.mul(r2));
    if (this.swing < 0.0) {
      [p65, p7d] = [p7d, p65];
      [p71, p89] = [p89, p71];
    }
    this._rest_points = [p65, p71, p7d, p89];
    const reach = this.rest_tip.sub(this.pivot).length() + r2;
    this._reach_sq = reach * reach;
    const sweep = this.rest_tip.sub(this.extended_tip).length() / r2;
    this.step = Math.min(this.up_time, this.down_time) / (sweep + sweep);
    this.length = this.rest_tip.sub(this.pivot).length();
    this._pose(0.0);
  }

  boundingBox() {
    const r1 = this._r1;
    const r2 = this._r2;
    const xs = [this.pivot.x - r1, this.pivot.x + r1, this.rest_tip.x - r2, this.rest_tip.x + r2,
      this.extended_tip.x - r2, this.extended_tip.x + r2];
    const ys = [this.pivot.y - r1, this.pivot.y + r1, this.rest_tip.y - r2, this.rest_tip.y + r2,
      this.extended_tip.y - r2, this.extended_tip.y + r2];
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }

  message(code, time) {
    if (code === 1) {
      this.start_angle = this.angleAt(time);
      this.target_angle = this.swing;
      this.duration = this.up_time;
    } else if (code === 2) {
      this.start_angle = this.angleAt(time);
      this.target_angle = 0.0;
      this.duration = this.down_time;
    } else if (code === 0x400) {
      this.state = 0;
      this.target_angle = 0.0;
      return;
    }
    if (this.state === 0) this.start_time = time;
    this.state = code;
    this.end_time = this.duration + this.start_time;
  }

  angleAt(time) {
    if (this.state === 0) return this.target_angle;
    const span = Math.abs((this.target_angle - this.start_angle) / this.swing * this.duration);
    let frac = span >= 1e-7 ? (time - this.start_time) / span : 1.0;
    frac = Math.min(1.0, Math.max(0.0, frac));
    if (this.state === 2) frac = 1.0 - frac;
    return frac * this.swing;
  }

  _pose(angle) {
    const s = sin(angle);
    const c = cos(angle);
    const [p65, p71, p7d, p89] = this._rest_points.map((p) => rotate(p, this.pivot, s, c));
    this._p65 = p65;
    this._p71 = p71;
    this._p7d = p7d;
    this._p89 = p89;
    this._tip = rotate(this.rest_tip, this.pivot, s, c);
    this._line1 = line(p65, p71, 0.0);
    this._line2 = line(p7d, p89, 0.0);
  }

  tip() {
    return this._tip;
  }

  _inside(x, y) {
    const a = this._p65;
    const b = this._p71;
    const c = this._p7d;
    const d = this._p89;
    const outsideQuad = (
      (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x) < 0.0
      || (y - b.y) * (c.x - b.x) - (x - b.x) * (c.y - b.y) < 0.0
      || (y - c.y) * (d.x - c.x) - (x - c.x) * (d.y - c.y) < 0.0
      || (y - d.y) * (a.x - d.x) - (x - d.x) * (a.y - d.y) < 0.0
    );
    const px = this.pivot.x;
    const py = this.pivot.y;
    const tip = this._tip;
    if (
      outsideQuad
      && (px - x) * (px - x) + (py - y) * (py - y) > this._r1_sq
      && this._r2_sq <= (tip.y - y) * (tip.y - y) + (tip.x - x) * (tip.x - x)
    ) return 0;
    const st = this.state;
    if (this.swing < 0.0) {
      const ref = st === 1 ? c : st === 2 ? b : tip;
      const v = (y - ref.y) * (px - ref.x) - (x - ref.x) * (py - ref.y);
      return v >= 0.0 ? 4 : 5;
    }
    let v;
    if (st === 2) {
      v = (px - a.x) * (y - a.y) - (py - a.y) * (x - a.x);
    } else {
      const ref = st === 1 ? d : tip;
      v = (y - ref.y) * (px - ref.x) - (x - ref.x) * (py - ref.y);
    }
    return v < 0.0 ? 4 : 5;
  }

  // FUN_0101b43a: [t, contact, normal] or null.
  _nearest(origin, direction, length, tolerance) {
    let best = null;
    let kind = -1;
    const tests = [
      [0, lineHit(origin, direction, length, tolerance, this._line1)],
      [2, circleHit(origin, direction, length, this.pivot, this._r1_sq)],
      [3, circleHit(origin, direction, length, this._tip, this._r2_sq)],
      [1, lineHit(origin, direction, length, tolerance, this._line2)],
    ];
    for (const [k, t] of tests) {
      if (t !== null && (best === null || t < best)) {
        best = t;
        kind = k;
      }
    }
    if (best === null) return null;
    const contact = origin.add(direction.mul(best));
    let normal;
    if (kind === 0) normal = this._line1[0];
    else if (kind === 1) normal = this._line2[0];
    else normal = contact.sub(kind === 2 ? this.pivot : this._tip).normalized();
    return [best, contact, normal];
  }

  // FUN_0101b825.
  sweep(origin, direction, length, tolerance, time, window) {
    if (this.end_time < time) this.state = 0;
    if (this.skip_next) {
      this.skip_next = false;
      return null;
    }
    if (this.state === 0) {
      this.leading = false;
      this.trailing = false;
      this._pose(this.angleAt(time));
      const inside = this._inside(origin.x, origin.y);
      if (inside === 0) {
        const hit = this._nearest(origin, direction, length, tolerance);
        if (hit === null) return null;
        const [t, contact, normal] = hit;
        this.contact = t === 0.0 ? contact.sub(direction.mul(1e-5)) : contact;
        this.normal = normal;
        return t;
      }
      let push;
      if (this.pivot.sub(origin).lengthSq() < this._inner1_sq) {
        push = this.pivot.sub(origin).normalized();
      } else if (this._tip.sub(origin).lengthSq() < this._inner2_sq) {
        push = this._tip.sub(origin).normalized();
      } else {
        push = (inside === 4 ? this._line1[0] : this._line2[0]).neg();
      }
      let hit = this._nearest(origin.sub(push.mul(5.0)), push, length + 10.0, tolerance);
      if (hit === null) {
        push = this.pivot.sub(origin).normalized();
        hit = this._nearest(origin.sub(push.mul(5.0)), push, length + 10.0, tolerance);
        if (hit === null) return null;
      }
      this.normal = hit[2];
      this.contact = hit[1].sub(push.mul(1e-5));
      return 0.0;
    }

    let position = origin;
    const subLength = this.step * length;
    const advance = direction.mul(this.step);
    let t = time;
    while (t < window + time) {
      this._pose(this.angleAt(t));
      const inside = this._inside(position.x, position.y);
      if (inside !== 0) {
        let face;
        if (this.state === 1 && inside !== 5) {
          face = this._line1[0];
        } else if (this.state !== 2 || inside === 4) {
          const push = this.pivot.sub(position).normalized();
          this.leading = false;
          this.trailing = true;
          const hit = this._nearest(position.sub(push.mul(5.0)), push, length + 10.0, tolerance);
          if (hit !== null) {
            this.normal = hit[2];
            this.contact = hit[1].sub(push.mul(1e-5));
          } else {
            this.contact = position;
            this.normal = push.neg();
          }
          return 0.0;
        } else {
          face = this._line2[0];
        }
        const push = face.neg();
        this.face_normal = face;
        this.leading = true;
        this.trailing = false;
        const hit = this._nearest(origin.sub(push.mul(5.0)), push, length + 10.0, 0.002);
        if (hit !== null) this.normal = hit[2];
        if (hit === null) return null;
        this.contact = hit[1].sub(push.mul(1e-5));
        return 0.0;
      }
      const hit = this._nearest(origin, direction, subLength, tolerance);
      if (hit !== null) {
        const [distance, contact, normal] = hit;
        this.contact = contact.sub(direction.mul(1e-5));
        const tip = this._tip;
        const pivot = this.pivot;
        const cross = (this.contact.y - tip.y) * (pivot.x - tip.x) - (this.contact.x - tip.x) * (pivot.y - tip.y);
        const k = (cross < 0.0) === (this.swing > 0.0);
        if (this.state === 2) {
          this.face_normal = this._line2[0];
          this.leading = !k;
        } else {
          this.leading = k;
          this.face_normal = this._line1[0];
        }
        this.normal = normal;
        return distance;
      }
      t += this.step;
      position = position.add(advance);
    }
    return null;
  }

  // FUN_0101be06: [e_n, e_t, threshold, kick].
  collide() {
    this.skip_next = true;
    let eN = this.restitution;
    const eT = this.tangent_retention;
    if (this.state === 0) return [eN, eT, NO_KICK, 0.0];
    const dSq = this.contact.sub(this.pivot).lengthSq();
    if (!this.leading) {
      if (this.trailing && this._r1_sq * 1.01 < dSq) eN = (1.0 - Math.sqrt(dSq / this._reach_sq)) * eN;
      return [eN, eT, NO_KICK, 0.0];
    }
    let kick;
    if (dSq <= this._r1_sq * 1.01) {
      kick = 0.0;
    } else {
      const k = this.face_normal.dot(this.normal);
      kick = k >= 0.0 ? k * (Math.abs(this.swing) / this.duration) * Math.sqrt(dSq / this._reach_sq) : 0.0;
    }
    kick *= this.kick_factor;
    return [eN, eT, kick > 0.0 ? -1.0 : NO_KICK, kick];
  }
}

export { Flipper };
