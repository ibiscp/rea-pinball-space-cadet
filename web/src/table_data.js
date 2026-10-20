// Port of table_data.py: builds the playable table (world, objects,
// flippers) from the table data, exactly as the Python port does.

import * as c from './constants.js';
import {
  CenterPost, Flag, Gate, Kickback, Kickout, PassLine, Plunger, Ramp, RampHole, RampTriangle, Rollover, Sink,
  WallSwitch, WallTarget,
} from './entities.js';
import { Flipper } from './flipper.js';
import { Circle, Segment, TripLine } from './geometry.js';
import { Grid } from './grid.js';
import { floatArrays, int16At, tag10, taggedFloats } from './partout.js';
import { loadCamera } from './projection.js';
import { sin, cos } from './pymath.js';
import { loadTableResources } from './resources.js';
import { Vec2 } from './vec2.js';
import { World, gravityFromTriple } from './world.js';

const WALL_TYPES = [0x3e8, 0x3f2];
const ONE_WAY_TYPE = 0x3f8;
const GATE_TYPE = 0x3f5;
const KICKBACK_TYPE = 0x3f6;
const STANDUP_TARGET_TYPE = 0x3ee;
const DROP_TARGET_TYPE = 0x3fb;
const TARGET_TYPES = [STANDUP_TARGET_TYPE, DROP_TARGET_TYPE];
const DROP_TARGET_RAISE_DELAY = 0.1;
const SINK_TYPE = 0x3f9;
const PLUNGER_BOUNCE = 0.5;
const KICKOUT_TYPE = 0x3f4;
const GRAVITY_WELL_KICKOUT_TYPE = 0x405;
const KICKOUT_TYPES = [KICKOUT_TYPE, GRAVITY_WELL_KICKOUT_TYPE];
const ROLLOVER_TYPES = [0x3f7, 0x3fc];
const FLAG_TYPE = 0x3fa;
const TRIP_TYPE = 0x400;
const CENTER_POST_TYPE = 0x3f3;
const ONE_WAY_BACK_OFFSET = 0.8;
const RAMP_TYPE = 0x3fd;
const RAMP_HOLE_TYPE = 0x3fe;

// [points, radius or null] from tag 600, or null.
function shape(entry) {
  const values = taggedFloats(entry, 600);
  if (values === null) return null;
  const count = Math.trunc(values[0]);
  const points = [];
  for (let i = 0; i < count; i++) points.push(new Vec2(values[1 + 2 * i], values[2 + 2 * i]));
  const radius = count === 1 ? values[1 + 2 * count] : null;
  return [points, radius];
}

function presetValues(pf, entry, tag) {
  const stream = tag10(entry);
  for (let i = 0; i < stream.length - 1; i += 2) {
    if (stream[i] !== tag) continue;
    const arrays = floatArrays(pf.entries[stream[i + 1]]);
    if (!arrays.length) return new Map();
    const values = arrays[0];
    const out = new Map();
    let j = 0;
    while (j + 1 < values.length) {
      const key = Math.trunc(values[j]);
      const width = key === 404 ? 3 : 1;
      out.set(key, values.slice(j + 1, j + 1 + width));
      j += 1 + width;
    }
    return out;
  }
  return new Map();
}

function preset(pf, entry, tag) {
  const out = new Map();
  for (const [key, values] of presetValues(pf, entry, tag)) out.set(key, values[0]);
  return out;
}

function get(map, key, fallback) {
  return map.has(key) ? map.get(key) : fallback;
}

// An object's bitmap count: its own entry plus the type-0 = 201 entries after it.
function spriteFrames(pf, entry) {
  const index = pf.entries.indexOf(entry);
  let frames = 1;
  for (const following of pf.entries.slice(index + 1)) {
    const marker = following.variants.find((v) => v.type_tag === 0);
    if (!marker || int16At(marker.raw) !== 201) break;
    frames += 1;
  }
  return frames;
}

function mask(entry) {
  const stream = tag10(entry);
  let m = 0;
  for (let i = 0; i < stream.length - 1; i += 2) {
    if (stream[i] === 602) m |= 1 << stream[i + 1];
  }
  return m || 1;
}

function coefficients(pf, entry) {
  const b = preset(pf, entry, 300);
  const k = preset(pf, entry, 400);
  return {
    restitution: get(b, 302, c.WALL_RESTITUTION),
    tangent_retention: get(b, 301, c.WALL_TANGENT_RETENTION),
    kick_threshold: get(k, 401, c.NO_KICK_THRESHOLD),
    kick: get(k, 402, 0.0),
  };
}

function tableObjects(pf) {
  const manifest = pf.find('table_objects');
  if (manifest === null) throw new Error('PINBALL.DAT has no table_objects entry');
  const stream = tag10(manifest);
  const out = [];
  for (let i = 1; i + 1 < stream.length; i += 2) out.push([stream[i], pf.entries[stream[i + 1]]]);
  return out;
}

// FUN_010179a9.
function wallsFromShape(points, radius, m, coeffs, ballRadius) {
  if (points.length === 1 && radius !== null) return [[], [new Circle(points[0], radius, { mask: m, ...coeffs })]];
  if (points.length === 2) return [[new Segment(points[0], points[1], { one_sided: true, mask: m, ...coeffs })], []];
  const loop = points.slice(0, -1);
  const n = loop.length;
  const segments = [];
  for (let i = 0; i < n; i++) {
    segments.push(new Segment(loop[i], i + 1 < n ? loop[i + 1] : points[points.length - 1], { mask: m, ...coeffs }));
  }
  const corners = [];
  for (let i = 0; i < n; i++) {
    const prev = loop[(i - 1 + n) % n];
    const cur = loop[i];
    const nxt = loop[(i + 1) % n];
    const a = cur.sub(prev);
    const b = nxt.sub(cur);
    if (a.x * b.y - a.y * b.x > 0.0 && ballRadius > 0.0) {
      corners.push(new Circle(cur, ballRadius * 1.001 - ballRadius, { mask: m, wall: segments[i], ...coeffs }));
    }
  }
  return [segments, corners];
}

function polygon(points) {
  const loop = points.slice(0, -1);
  return loop.map((p, i) => [p, loop[(i + 1) % loop.length]]);
}

function buildRollover(entry, points, m, world, lightsOnEntry) {
  const lightTime = lightsOnEntry ? taggedFloats(entry, 407) : null;
  const rollover = new Rollover(entry.name, {
    mask: m, lights_on_entry: lightsOnEntry, light_time: lightTime ? lightTime[0] : 0.0,
  });
  const cross = (ball) => rollover.cross(ball);
  for (const [a, b] of polygon(points)) world.trip_lines.push(new TripLine(a, b, m, cross, () => rollover.armed));
  const exitValues = taggedFloats(entry, 603);
  if (exitValues !== null) {
    const count = Math.trunc(exitValues[0]);
    const exitPoints = [];
    for (let i = 0; i < count; i++) exitPoints.push(new Vec2(exitValues[1 + 2 * i], exitValues[2 + 2 * i]));
    for (const [a, b] of polygon(exitPoints)) world.trip_lines.push(new TripLine(a, b, m, cross, () => rollover.inside));
  }
  return rollover;
}

function buildFlag(pf, entry, points, m, world) {
  const maxRate = taggedFloats(entry, 1200);
  const minRate = taggedFloats(entry, 1201);
  const decay = taggedFloats(entry, 1202);
  const flag = new Flag(entry.name, {
    frames: spriteFrames(pf, entry),
    max_rate: maxRate ? maxRate[0] : 50000.0,
    min_rate: minRate ? minRate[0] : 5.0,
    decay: decay ? decay[0] : 0.65,
  });
  const [p0, p1] = points;
  world.trip_lines.push(new TripLine(p1, p0, m, (ball) => flag.cross(ball, false)));
  world.trip_lines.push(new TripLine(p0, p1, m, (ball) => flag.cross(ball, true)));
  return flag;
}

function buildRamp(entry, gravityMagnitude, world) {
  const mesh = taggedFloats(entry, 1300);
  if (mesh === null) throw new Error(`${entry.name} has no tag-1300 mesh`);
  const friction = taggedFloats(entry, 701);
  const heightFlag = taggedFloats(entry, 1305);
  const m = mask(entry);
  const triangles = [];
  for (let k = 0; k < Math.trunc(mesh[0]); k++) {
    const r = mesh.slice(1 + 13 * k, 14 + 13 * k);
    const slope = r[9];
    const direction = r[10];
    triangles.push(new RampTriangle(
      [r[0], r[1], r[2]],
      [new Vec2(r[3], r[4]), new Vec2(r[5], r[6]), new Vec2(r[7], r[8])],
      new Vec2(cos(direction), sin(direction)).mul(sin(slope) * gravityMagnitude),
    ));
  }
  const xs = [];
  const ys = [];
  for (const t of triangles) for (const v of t.vertices) {
    xs.push(v.x);
    ys.push(v.y);
  }
  const bounds = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  const ramp = new Ramp(entry.name, {
    mask: m,
    friction: friction ? friction[0] : 0.2,
    bounds,
    triangles,
    set_height_on_exit: Boolean(heightFlag && Math.trunc(heightFlag[0])),
    grid: world.grid,
    cells: world.grid !== null ? world.grid.cellsInBox(...bounds) : new Set(),
  });

  const link = (tag) => {
    const v = taggedFloats(entry, tag);
    const a = new Vec2(v[3], v[4]);
    const b = new Vec2(v[5], v[6]);
    let best = null;
    triangles.forEach((tri, k) => {
      for (let i = 0; i < 3; i++) {
        const s = tri.vertices[i];
        const e = tri.vertices[(i + 1) % 3];
        const d = a.sub(s).length() + b.sub(e).length();
        if (best === null || d < best[0]) best = [d, k, i];
      }
    });
    const layerMask = 1 << Math.floor(v[0]);
    return [best[1], best[2], layerMask, Math.floor(v[1]) ? layerMask : 0, v[7]];
  };

  const links = [link(1301), link(1302)];
  triangles.forEach((tri, k) => {
    for (let i = 0; i < 3; i++) {
      const s = tri.vertices[i];
      const e = tri.vertices[(i + 1) % 3];
      let edgeMask = m;
      for (const [lk, li, , entryMask] of links) {
        if (lk === k && li === i) {
          edgeMask = entryMask;
          break;
        }
      }
      if (edgeMask) world.trip_lines.push(new TripLine(s, e, edgeMask, (ball) => ramp.enter(ball, tri)));
    }
  });
  for (const [lk, li, layerMask, , height] of links) {
    const tri = triangles[lk];
    const s = tri.vertices[li];
    const e = tri.vertices[(li + 1) % 3];
    world.trip_lines.push(new TripLine(e, s, m, (ball) => ramp.leave(ball, layerMask, height)));
  }
  const score = taggedFloats(entry, 1303);
  if (score !== null) {
    world.trip_lines.push(new TripLine(
      new Vec2(score[4], score[5]), new Vec2(score[2], score[3]), 1 << Math.floor(score[0]),
      (ball) => ramp.scoreLine(ball),
    ));
  }
  world.ramps.push(ramp);
  return ramp;
}

function buildRampHole(entry, center, radius, m, gravityMagnitude) {
  const capture = taggedFloats(entry, 306);
  const strength = taggedFloats(entry, 305);
  const friction = taggedFloats(entry, 701);
  const floor = taggedFloats(entry, 408);
  const exitLayer = taggedFloats(entry, 1304);
  return new RampHole(entry.name, {
    center,
    field_radius: radius,
    capture_radius: capture ? radius * capture[0] : 0.001,
    strength: strength ? strength[0] : 0.0,
    mask: m,
    drop_friction: friction ? friction[0] : 0.5,
    floor_z: floor ? floor[2] : radius,
    exit_mask: exitLayer ? Math.floor(exitLayer[0]) : 1,
    gravity_magnitude: gravityMagnitude,
  });
}

function buildFlippers(pf, flipSprites, cam, ballRadius) {
  if (flipSprites.length < 2) throw new Error('expected at least 2 flipper sprites');
  const flippers = [];
  for (const sprite of [flipSprites[0], flipSprites[flipSprites.length - 1]]) {
    const entry = pf.find(sprite.name);
    const tags = {};
    for (const tag of [800, 801, 802, 803, 804, 805]) tags[tag] = entry ? taggedFloats(entry, tag) : null;
    if ([800, 801, 802, 804, 805].some((tag) => tags[tag] === null)) throw new Error(`${sprite.name} lacks flipper tags`);
    const pivot = new Vec2(tags[800][0], tags[800][1]);
    const coeffs = coefficients(pf, entry);
    flippers.push(new Flipper({
      pivot,
      radius: tags[800][2],
      rest_tip: new Vec2(tags[801][0], tags[801][1]),
      tip_radius: tags[801][2],
      extended_tip: new Vec2(tags[802][0], tags[802][1]),
      up_time: tags[804][0],
      down_time: tags[805][0],
      ball_radius: ballRadius,
      kick_factor: tags[803] ? tags[803][0] : 0.9,
      restitution: coeffs.restitution,
      tangent_retention: coeffs.tangent_retention,
      mask: mask(entry),
      is_left: cam.toScreen(pivot).x < cam.toScreen(new Vec2(0.0, pivot.y)).x,
    }));
  }
  const sorted = flippers.slice().sort((a, b) => cam.toScreen(a.pivot).x - cam.toScreen(b.pivot).x);
  return [sorted[0], sorted[1]];
}

class TableLayout {
  constructor(o) {
    Object.assign(this, {
      plunger: null, camera: null, screen_size: [c.TABLE_WIDTH, c.TABLE_HEIGHT], ball_radius: c.BALL_RADIUS,
      resources: null, wall_targets: [], rollovers: [], flags: [], passes: [], switches: [], center_post: null,
      gates: [], kickbacks: [], sinks: [], kickouts: [], ramps: [], ramp_holes: [], bumpers: [],
      left_flipper_sprite: null, right_flipper_sprite: null,
    }, o);
  }
}

function buildTable(pf) {
  const res = loadTableResources(pf);
  const cam = loadCamera(pf);
  const world = new World();

  const table = pf.find('table');
  const ballEntry = pf.find('ball');
  const drain = pf.find('drain');
  if (table === null || ballEntry === null || drain === null) throw new Error('missing table/ball/drain');

  const gravity = taggedFloats(table, 305) || c.GRAVITY_TRIPLE;
  world.gravity = gravityFromTriple(gravity[0], gravity[1], gravity[2]);
  const friction = taggedFloats(table, 701);
  world.friction = friction ? friction[0] : c.FRICTION;
  const radius = taggedFloats(ballEntry, 500);
  const ballRadius = radius ? radius[0] : c.BALL_RADIUS;
  world.max_ball_speed = ballRadius * 200.0;

  const tableShape = shape(table);
  if (tableShape === null) throw new Error('table entry has no tag-600 outline');
  const [outline] = tableShape;
  const threshold = get(preset(pf, table, 400), 401, c.NO_KICK_THRESHOLD);
  for (let i = 0; i + 1 < outline.length; i++) {
    const a = outline[i];
    const b = outline[i + 1];
    world.segments.push(new Segment(b, a, {
      kick_threshold: threshold, kick: c.TABLE_WALL_KICK, one_sided: true, radius_offset: false,
    }));
  }
  world.frame_bounds = [
    Math.min(...outline.map((p) => p.x)), Math.min(...outline.map((p) => p.y)), Math.max(...outline.map((p) => p.x)),
  ];
  const corner = outline.slice(0, 3);
  const gx0 = Math.min(...corner.map((p) => p.x));
  const gy0 = Math.min(...corner.map((p) => p.y));
  world.grid = new Grid(gx0, gy0, Math.max(...corner.map((p) => p.x)) - gx0, Math.max(...corner.map((p) => p.y)) - gy0);

  const drainShape = shape(drain);
  world.drain_y = drainShape ? drainShape[0][0].y : Math.max(...outline.map((p) => p.y));

  const gravityMagnitude = gravity[0];
  const objects = tableObjects(pf);
  const ramps = objects.filter(([t]) => t === RAMP_TYPE).map(([, entry]) => buildRamp(entry, gravityMagnitude, world));
  const rampHoles = [];
  const gates = new Map();
  const kickbacks = [];
  const wallTargets = [];
  const sinks = [];
  const kickouts = [];
  const rollovers = [];
  const flags = [];
  const passes = [];
  let centerPost = null;
  const switches = [];
  for (const [typeId, entry] of objects) {
    const sh = shape(entry);
    if (sh === null) continue;
    const [points, rad] = sh;
    const m = mask(entry);
    const coeffs = coefficients(pf, entry);
    if (ROLLOVER_TYPES.includes(typeId)) {
      rollovers.push(buildRollover(entry, points, m, world, typeId === 0x3fc));
      continue;
    }
    if (typeId === FLAG_TYPE) {
      flags.push(buildFlag(pf, entry, points, m, world));
      continue;
    }
    if (typeId === TRIP_TYPE) {
      const trip = new PassLine(entry.name);
      const ln = new TripLine(points[0], points[1], m, (ball) => trip.cross(ball));
      world.trip_lines.push(ln.offset(ballRadius));
      passes.push(trip);
      continue;
    }
    if (typeId === CENTER_POST_TYPE) {
      const [segments, corners] = wallsFromShape(points, rad, m, coeffs, ballRadius);
      for (const s of segments) s.active = false;
      world.segments.push(...segments);
      world.circles.push(...corners);
      centerPost = new CenterPost(entry.name, segments);
      continue;
    }
    if (WALL_TYPES.includes(typeId)) {
      const [segments, circles] = wallsFromShape(points, rad, m, coeffs, ballRadius);
      if (entry.name) {
        const sw = new WallSwitch(entry.name, { kick_threshold: coeffs.kick_threshold, kick: coeffs.kick });
        for (const s of segments) s.behavior = sw;
        for (const ci of circles) ci.behavior = sw;
        switches.push(sw);
      }
      world.segments.push(...segments);
      world.circles.push(...circles);
    } else if (typeId === ONE_WAY_TYPE) {
      world.segments.push(new Segment(points[0], points[1], { one_sided: true, mask: m, ...coeffs }));
      const back = new PassLine(entry.name);
      const ln = new TripLine(points[1], points[0], m, (ball) => back.cross(ball));
      world.trip_lines.push(ln.offset(-ONE_WAY_BACK_OFFSET * ballRadius));
      passes.push(back);
    } else if (typeId === GATE_TYPE) {
      const segment = new Segment(points[0], points[1], { one_sided: true, mask: m, ...coeffs });
      world.segments.push(segment);
      gates.set(entry.name, new Gate(entry.name, segment));
    } else if (TARGET_TYPES.includes(typeId)) {
      const reset = taggedFloats(entry, 407);
      const target = new WallTarget(entry.name, {
        kick_threshold: coeffs.kick_threshold,
        kick: coeffs.kick,
        drop_time: typeId === DROP_TARGET_TYPE ? DROP_TARGET_RAISE_DELAY : 0.0,
        reset_delay: reset ? reset[0] : 0.25,
      });
      const [segments, corners] = wallsFromShape(points, rad, m, coeffs, ballRadius);
      for (const s of segments) s.behavior = target;
      target.segments = segments;
      world.segments.push(...segments);
      world.circles.push(...corners);
      wallTargets.push(target);
    } else if (KICKOUT_TYPES.includes(typeId) && rad !== null) {
      const launch = presetValues(pf, entry, 400);
      const captureFraction = taggedFloats(entry, 306);
      const strength = taggedFloats(entry, 305);
      const direction = get(launch, 404, [0.0, -1.0, 0.0]);
      const kickout = new Kickout(entry.name, {
        center: points[0],
        field_radius: rad,
        capture_radius: captureFraction ? Math.max(rad * captureFraction[0], 0.001) : 0.001,
        strength: strength ? strength[0] : 0.0,
        direction: new Vec2(direction[0], direction[1]),
        spread: get(launch, 405, [0.0])[0],
        speed: get(launch, 402, [0.0])[0],
        variation: get(launch, 403, [0.0])[0] * 0.01,
        active: typeId === KICKOUT_TYPE,
        stays_off: typeId === GRAVITY_WELL_KICKOUT_TYPE,
        mask: m,
      });
      world.fields.push(kickout);
      kickouts.push(kickout);
    } else if (typeId === SINK_TYPE) {
      const launch = presetValues(pf, entry, 400);
      const exitPoint = taggedFloats(entry, 601);
      const delay = taggedFloats(entry, 407);
      const direction = get(launch, 404, [0.0, -1.0, 0.0]);
      const sink = new Sink(entry.name, {
        exit_position: exitPoint ? new Vec2(exitPoint[0], exitPoint[1]) : points[0],
        direction: new Vec2(direction[0], direction[1]),
        spread: get(launch, 405, [0.0])[0],
        speed: get(launch, 402, [0.0])[0],
        variation: get(launch, 403, [0.0])[0] * 0.01,
        eject_delay: delay ? delay[0] : 2.0,
      });
      world.segments.push(new Segment(points[0], points[1], { one_sided: true, mask: m, behavior: sink, ...coeffs }));
      sinks.push(sink);
    } else if (typeId === RAMP_HOLE_TYPE && rad !== null) {
      const hole = buildRampHole(entry, points[0], rad, m, gravityMagnitude);
      world.fields.push(hole);
      rampHoles.push(hole);
    } else if (typeId === KICKBACK_TYPE) {
      const kickback = new Kickback(entry.name, { kick: coeffs.kick });
      coeffs.kick_threshold = c.NO_KICK_THRESHOLD;
      world.segments.push(new Segment(points[0], points[1], { one_sided: true, mask: m, behavior: kickback, ...coeffs }));
      kickbacks.push(kickback);
    }
  }

  const plungerEntry = pf.find('plunger');
  const plungerShape = plungerEntry ? shape(plungerEntry) : null;
  const serve = plungerEntry ? taggedFloats(plungerEntry, 601) : null;
  if (plungerShape === null || serve === null) throw new Error('plunger entry lacks tag 600 / 601');
  const [faceA, faceB] = plungerShape[0];
  const plungerRest = new Vec2(serve[0], serve[1]);
  const plunger = new Plunger({ step: Math.trunc(100.0 / (spriteFrames(pf, plungerEntry) * 8.0)) });
  world.segments.push(new Segment(faceA, faceB, {
    restitution: PLUNGER_BOUNCE, tangent_retention: PLUNGER_BOUNCE, one_sided: true, behavior: plunger,
  }));

  const bumpers = [];
  for (const sprite of res.byCategory('a_bump')) {
    const entry = pf.find(sprite.name);
    const sh = entry ? shape(entry) : null;
    if (sh === null || sh[1] === null) continue;
    const lockout = taggedFloats(entry, 407);
    const circle = new Circle(sh[0][0], sh[1], {
      mask: mask(entry),
      cooldown: lockout ? lockout[0] : c.BUMPER_COOLDOWN,
      name: sprite.name,
      ...coefficients(pf, entry),
    });
    bumpers.push(circle);
    world.circles.push(circle);
  }

  const flipSprites = res.byCategory('a_flip').slice().sort((a, b) => a.center[0] - b.center[0]);
  const [leftFlipper, rightFlipper] = buildFlippers(pf, flipSprites, cam, ballRadius);
  for (const f of [leftFlipper, rightFlipper]) f.cells = world.grid.cellsInBox(...f.boundingBox());
  world.flippers.push(leftFlipper, rightFlipper);

  return new TableLayout({
    world,
    left_flipper: leftFlipper,
    right_flipper: rightFlipper,
    plunger_rest: plungerRest,
    plunger,
    camera: cam,
    screen_size: res.table_size,
    ball_radius: ballRadius,
    resources: res,
    wall_targets: wallTargets,
    rollovers,
    flags,
    passes,
    switches,
    center_post: centerPost,
    gates: [...gates.values()],
    kickbacks,
    sinks,
    kickouts,
    ramps,
    ramp_holes: rampHoles,
    bumpers,
    left_flipper_sprite: flipSprites[0],
    right_flipper_sprite: flipSprites[flipSprites.length - 1],
  });
}

export { buildTable, mask, spriteFrames, tableObjects, TableLayout };
