// Port of world.py: the physics world (FUN_01014bf9 / FUN_01014a68 /
// FUN_01014956 / FUN_0100b486 / FUN_01017883), in world units.

import * as c from './constants.js';
import { circleHit, lineHit } from './geometry.js';
import { sin, cos, f32 } from './pymath.js';
import { rng } from './rng.js';
import { Vec2 } from './vec2.js';

const MAX_TOI_STEPS = 10;
const TOI_TOLERANCE = 0.002;

function gravityFromTriple(magnitude, a1, a2) {
  return new Vec2(cos(a2) * sin(a1) * magnitude, sin(a2) * sin(a1) * magnitude);
}

// FUN_01017883: returns [new velocity, impact speed].
function bounce(velocity, normal, restitution, tangentRetention, kickThreshold = c.NO_KICK_THRESHOLD, kick = 0.0,
  separating = false) {
  const speed = velocity.length();
  const d = speed > 1e-12 ? velocity.mul(1.0 / speed) : normal.neg();
  let closing = -normal.dot(d);
  let newDir;
  if (closing > 0) {
    newDir = d.add(normal.mul(closing)).mul(tangentRetention).add(normal.mul(closing * restitution)).normalized();
  } else if (separating) {
    closing = -closing;
    newDir = d;
  } else {
    return [velocity, 0.0];
  }
  const impact = closing * speed;
  let newVelocity = newDir.mul(speed - (1.0 - restitution) * impact);
  if (impact >= kickThreshold) newVelocity = normal.mul(kick).add(newVelocity);
  return [newVelocity, impact];
}

class World {
  constructor() {
    this.segments = [];
    this.circles = [];
    this.flippers = [];
    this.balls = [];
    this.fields = [];
    this.ramps = [];
    this.trip_lines = [];
    this._trip_edges = new Map();
    this.gravity = gravityFromTriple(...c.GRAVITY_TRIPLE);
    this.friction = c.FRICTION;
    this.max_ball_speed = c.MAX_BALL_SPEED;
    this.jitter = true;
    this.tilted = false;
    this.on_ball_drained = null;
    this.drain_y = Infinity;
    this.frame_bounds = null;
    this.time = 0.0;
    this.grid = null;
  }

  step(dt) {
    const start = this.time;
    for (const circle of this.circles) {
      if (circle._cooldown_remaining > 0) circle._cooldown_remaining -= dt;
    }
    for (const ball of this.balls) {
      if (ball.alive && !ball.held) {
        this._integrate(ball, dt);
        this._move(ball, start, dt);
      }
    }
    this.time = f32(start + dt);
  }

  _integrate(ball, dt) {
    const speed = ball.speed();
    const jitterX = this.jitter ? this.friction * speed * (rng.random() - 0.5) : 0.0;
    let accel = new Vec2(this.gravity.x + jitterX, this.gravity.y).sub(ball.velocity.mul(this.friction));
    for (const source of [...this.fields, ...this.ramps]) {
      const pull = source.accel(ball);
      if (pull !== null) accel = accel.add(pull);
    }
    ball.velocity = ball.velocity.add(accel.mul(dt));
  }

  _move(ball, time, dt) {
    let remaining = dt;
    let steps = MAX_TOI_STEPS;
    const excluded = [];
    while (remaining > 1e-6 && steps) {
      steps -= 1;
      const used = this._toiStep(ball, time, remaining, excluded);
      remaining -= used;
      time += used;
      if (!ball.alive || ball.held) return;
      this._afterMove(ball);
      if (!ball.alive || ball.held) return;
    }
  }

  _toiStep(ball, time, remaining, excluded) {
    let speed = ball.speed();
    if (speed > this.max_ball_speed) {
      ball.velocity = ball.velocity.mul(this.max_ball_speed / speed);
      speed = this.max_ball_speed;
    }
    const direction = speed > 0.0 ? ball.velocity.mul(1.0 / speed) : new Vec2(0.0, 0.0);
    const skip = excluded.slice();
    excluded.length = 0;
    const hit = this._nearestHit(ball, direction, remaining * speed, skip, time, remaining);
    if (hit === null) {
      ball.position = ball.position.add(ball.velocity.mul(remaining));
      return remaining;
    }
    const [t, kind, edge] = hit;
    if (kind !== 'flipper') ball.position = ball.position.add(direction.mul(t));
    this._hit(ball, kind, edge, excluded);
    if (speed > 1e-9) return Math.abs(t / speed);
    return remaining;
  }

  _nearestHit(ball, direction, length, excluded, time = 0.0, window = 0.0) {
    const origin = ball.position;
    const radius = ball.radius;
    let best = null;
    for (const seg of this.segments) {
      if (!seg.active || !(seg.mask & ball.mask) || excluded.includes(seg)) continue;
      const t = lineHit(origin, direction, length, TOI_TOLERANCE, seg.edge(radius));
      if (t !== null && (best === null || t < best[0])) best = [t, 'segment', seg];
    }
    for (const circle of this.circles) {
      if (!(circle.mask & ball.mask) || excluded.includes(circle)) continue;
      if (circle.wall !== null && !circle.wall.active) continue;
      const edgeRadius = circle.radius + radius;
      const t = circleHit(origin, direction, length, circle.center, edgeRadius * edgeRadius);
      if (t !== null && (best === null || t < best[0])) best = [t, 'circle', circle];
    }
    for (const ln of this.trip_lines) {
      if (!(ln.mask & ball.mask) || excluded.includes(ln)) continue;
      if (ln.active !== null && !ln.active()) continue;
      let edge = this._trip_edges.get(ln);
      if (edge === undefined) {
        edge = ln.edge();
        this._trip_edges.set(ln, edge);
      }
      const t = lineHit(origin, direction, length, TOI_TOLERANCE, edge);
      if (t !== null && (best === null || t < best[0])) best = [t, 'trip', ln];
    }
    for (const hole of this.fields) {
      const capture = hole.capture_radius;
      if (!hole.canCapture(ball)) continue;
      const t = circleHit(origin, direction, length, hole.center, capture * capture);
      if (t !== null && (best === null || t < best[0])) best = [t, 'capture', hole];
    }
    if (this.flippers.length) {
      const walked = this.grid !== null ? new Set(this.grid.walk(origin, direction, length)) : null;
      for (const flipper of this.flippers) {
        if (!(flipper.mask & ball.mask) || excluded.includes(flipper)) continue;
        if (walked !== null) {
          let meets = false;
          for (const cell of flipper.cells) {
            if (walked.has(cell)) {
              meets = true;
              break;
            }
          }
          if (!meets) continue;
        }
        const t = flipper.sweep(origin, direction, length, TOI_TOLERANCE, time, window);
        if (t !== null && (best === null || t < best[0])) best = [t, 'flipper', flipper];
      }
    }
    return best;
  }

  _hit(ball, kind, edge, excluded) {
    if (kind === 'trip') {
      excluded.push(edge);
      edge.on_cross(ball);
    } else if (kind === 'capture') {
      edge.tryCapture(ball, this.tilted, true);
    } else if (kind === 'flipper') {
      const [restitution, tangentRetention, threshold, kick] = edge.collide();
      ball.position = edge.contact.copy();
      [ball.velocity] = bounce(ball.velocity, edge.normal, restitution, tangentRetention, threshold, kick, true);
    } else if (kind === 'segment') {
      this._bounceOff(ball, edge, edge.edge(ball.radius)[0], edge.behavior);
    } else {
      const normal = ball.position.sub(edge.center).normalized();
      if (edge.wall !== null) this._bounceOff(ball, edge.wall, normal, edge.wall.behavior);
      else if (edge.on_hit !== null) this._bounceCircle(ball, edge, normal);
      else this._bounceOff(ball, edge, normal, edge.behavior);
    }
  }

  _bounceOff(ball, wall, normal, behavior) {
    if (behavior !== null && behavior.capture(ball, this.tilted)) return;
    let threshold;
    let kick;
    if (behavior !== null) [threshold, kick] = behavior.kickForContact(this.tilted);
    else if (this.tilted) [threshold, kick] = [c.NO_KICK_THRESHOLD, 0.0];
    else [threshold, kick] = [wall.kick_threshold, wall.kick];
    const [velocity, impact] = bounce(ball.velocity, normal, wall.restitution, wall.tangent_retention, threshold,
      kick, true);
    ball.velocity = velocity;
    if (behavior !== null) behavior.afterBounce(impact, threshold, this.tilted);
  }

  _bounceCircle(ball, circle, normal) {
    const armed = circle._cooldown_remaining <= 0;
    let threshold = armed ? circle.kick_threshold : c.NO_KICK_THRESHOLD;
    if (this.tilted) threshold = c.NO_KICK_THRESHOLD;
    const [velocity, impact] = bounce(ball.velocity, normal, circle.restitution, circle.tangent_retention, threshold,
      circle.kick, true);
    ball.velocity = velocity;
    if (armed && !this.tilted && impact > circle.kick_threshold) {
      circle._cooldown_remaining = circle.cooldown;
      if (circle.on_hit) circle.on_hit(circle);
    }
  }

  _afterMove(ball) {
    this._collideFrameBounds(ball);
    if (ball.position.y + ball.radius >= this.drain_y) {
      ball.alive = false;
      if (this.on_ball_drained) this.on_ball_drained(ball);
    }
  }

  _collideFrameBounds(ball) {
    if (this.frame_bounds === null) return;
    const [minX, minY, maxX] = this.frame_bounds;
    if (ball.position.x - ball.radius < minX) {
      ball.position.x = minX + ball.radius;
      ball.velocity.x = Math.abs(ball.velocity.x) * c.WALL_RESTITUTION;
    } else if (ball.position.x + ball.radius > maxX) {
      ball.position.x = maxX - ball.radius;
      ball.velocity.x = -Math.abs(ball.velocity.x) * c.WALL_RESTITUTION;
    }
    if (ball.position.y - ball.radius < minY) {
      ball.position.y = minY + ball.radius;
      ball.velocity.y = Math.abs(ball.velocity.y) * c.WALL_RESTITUTION;
    }
  }
}

export { World, bounce, gravityFromTriple, MAX_TOI_STEPS, TOI_TOLERANCE };
