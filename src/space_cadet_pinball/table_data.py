"""Builds the playable table from the real, reverse-engineered PINBALL.DAT.

Physics runs in the original's world units (see projection.py). Every
collision object comes from its own entry's real world-space shape (the
tag-600 point list, decoded by FUN_0100950a), instantiated the way the
`table_objects` manifest (FUN_0101aaf3's type switch) says:

- the table's outer walls: the "table" entry's polyline, one line wall per
  pair of points, exactly as the table constructor FUN_0101a5ab builds them;
- internal walls -- rails, lane guides, slingshots (`v_rebo*`), posts, the
  plunger-lane walls and the apron: manifest types 0x3e8/0x3f2, both built
  by FUN_010191ba, which hands the tag-600 shape to FUN_010179a9 (one point
  + radius -> circle, two points -> one-sided line, more -> closed polygon of
  the first n-1 points);
- one-way walls (`s_onewy*`, 0x3f8, FUN_01019204), the outlane gates
  (`v_gate*`, 0x3f5) and kickback plates (`a_kick*`, 0x3f6) as one-sided
  lines (see geometry.Segment / entities.Gate / entities.Kickback);
- the drain line, the bumpers' circles, the targets' and rollovers'
  polygons, the plunger face;
- the flippers: tags 800/801/802 (pivot circle, tip circle at rest, tip
  fully extended) and the 804/805 extend/retract times.

Each object's bounce coefficients come from its tag-300 preset (301 = e_t,
302 = e_n; FUN_01009249) and its kick from its tag-400 preset (401 =
threshold, 402 = kick; FUN_01009349), on top of FUN_01008fe0's defaults.
Its collision layer is the OR of `1 << v` over its type-10 tag-602 values
(default 1); the ball starts on layer 1 and the ramps move it between
layers (entities.Ramp).

Every wall is built as the original's collision edges: line walls moved
one ball radius out along their normal (FUN_0101c813), a circle of 1.001
ball radii at each left-turning polygon corner, circles grown by the ball
radius; the table's own outer walls are not offset. World tests the ball's
centre against them by time of impact.

Also real: the plunger (entities.Plunger), the sinks and kickout holes
(entities.Sink / entities.Kickout) and their eject presets, the wall-backed
targets (entities.WallTarget); the mission/light logic driving them is in
game.py / missions.py.

If the original assets aren't available, `build_table()` falls back to a
hand-authored placeholder layout in plain pixel units (`_build_default_table`)
so the game still runs.
"""

from __future__ import annotations

import itertools
import logging
import math
import struct
from dataclasses import dataclass, field

from . import constants as c
from . import partout
from .assets import pinball_data
from .entities import (
    CenterPost,
    Flag,
    Gate,
    Kickback,
    Kickout,
    PassLine,
    Plunger,
    Ramp,
    RampHole,
    RampTriangle,
    Rollover,
    Sink,
    WallSwitch,
    WallTarget,
)
from .flipper import Flipper
from .geometry import Circle, Segment, TripLine
from .grid import Grid
from .projection import IDENTITY, Camera, load_camera, tagged_floats
from .resources import SpriteObject, TableResources, load_table_resources
from .vec2 import Vec2
from .world import World, gravity_from_triple

log = logging.getLogger(__name__)

# table_objects type ids (FUN_0101aaf3's jump table at 0x101b017)
WALL_TYPES = (0x3E8, 0x3F2)  # FUN_010191ba
ONE_WAY_TYPE = 0x3F8  # FUN_01019204
GATE_TYPE = 0x3F5  # FUN_010196e5
KICKBACK_TYPE = 0x3F6  # FUN_0101983d
STANDUP_TARGET_TYPE = 0x3EE  # FUN_010195e0, a_targ1..9
DROP_TARGET_TYPE = 0x3FB  # FUN_0101961f, a_targ10..22
TARGET_TYPES = (STANDUP_TARGET_TYPE, DROP_TARGET_TYPE)
DROP_TARGET_RAISE_DELAY = 0.1  # FUN_0101961f: +0x56 = 0x3dcccccd
SINK_TYPE = 0x3F9  # FUN_0101a416, v_sink1/2/3/7
PLUNGER_BOUNCE = 0.5  # FUN_0101a4f3: e_n = e_t = float at 0x10024d0
# FUN_01019884 for both; 0x405 (a_kout1, the gravity well) starts inactive.
KICKOUT_TYPE = 0x3F4
GRAVITY_WELL_KICKOUT_TYPE = 0x405
KICKOUT_TYPES = (KICKOUT_TYPE, GRAVITY_WELL_KICKOUT_TYPE)
ROLLOVER_TYPES = (0x3F7, 0x3FC)  # FUN_01019771 (a_roll9: same switch, own class)
FLAG_TYPE = 0x3FA  # FUN_010194b0
TRIP_TYPE = 0x400  # FUN_01019816
CENTER_POST_TYPE = 0x3F3  # FUN_01019677, v_bloc1
ONE_WAY_BACK_OFFSET = 0.8  # FUN_01019204: the pass line sits 0.8 * ball radius out (0x1002528)
RAMP_TYPE = 0x3FD  # FUN_01019bb8: ramp, s_ramp9
RAMP_HOLE_TYPE = 0x3FE  # FUN_01019a1c: ramp_hole
# Which gate each kickback's listener closes after firing (FUN_0100c520 ->
# the v_gate1 slot at 0x1023808, FUN_0100c546 -> v_gate2 at 0x1023810).
KICKBACK_GATES = {"a_kick1": "v_gate1", "a_kick2": "v_gate2"}


@dataclass(slots=True)
class TableLayout:
    world: World
    left_flipper: Flipper
    right_flipper: Flipper
    plunger_rest: Vec2
    plunger: Plunger | None = None
    camera: Camera = IDENTITY
    screen_size: tuple[int, int] = (c.TABLE_WIDTH, c.TABLE_HEIGHT)
    ball_radius: float = c.BALL_RADIUS
    resources: TableResources | None = None
    wall_targets: list[WallTarget] = field(default_factory=list)
    rollovers: list[Rollover] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    passes: list[PassLine] = field(default_factory=list)
    switches: list[WallSwitch] = field(default_factory=list)
    center_post: CenterPost | None = None
    gates: list[Gate] = field(default_factory=list)
    kickbacks: list[Kickback] = field(default_factory=list)
    sinks: list[Sink] = field(default_factory=list)
    kickouts: list[Kickout] = field(default_factory=list)
    ramps: list[Ramp] = field(default_factory=list)
    ramp_holes: list[RampHole] = field(default_factory=list)
    bumpers: list[Circle] = field(default_factory=list)
    left_flipper_sprite: SpriteObject | None = None
    right_flipper_sprite: SpriteObject | None = None


def build_table() -> TableLayout:
    try:
        return _build_from_real_table()
    except Exception:
        log.exception("Falling back to the placeholder table layout")
        return _build_default_table()


def _shape(entry: partout.Entry) -> tuple[list[Vec2], float | None] | None:
    """An entry's tag-600 shape: (points, circle radius or None)."""
    values = tagged_floats(entry, 600)
    if values is None:
        return None
    count = int(values[0])
    points = [Vec2(values[1 + 2 * i], values[2 + 2 * i]) for i in range(count)]
    radius = values[1 + 2 * count] if count == 1 else None
    return points, radius


def _tag10_stream(entry: partout.Entry) -> list[int]:
    """The entry's type-10 int16 stream (FUN_01006270(..., 0xa) takes the
    first type-10 variant; no entry has more than one). Two-word streams
    such as [300, 95] are common, so their size doesn't set them apart."""
    variant = next((v for v in entry.variants if v.type_tag == 10), None)
    if variant is None:
        return []
    return [int.from_bytes(variant.raw[i : i + 2], "little", signed=True) for i in range(0, len(variant.raw), 2)]


def _preset_values(pf: partout.PartoutFile, entry: partout.Entry, tag: int) -> dict[int, tuple[float, ...]]:
    """FUN_0100950a's tag-300/400 indirection: the value after `tag` in the
    entry's type-10 stream is the index of a shared preset entry whose float
    array is a run of (tag, value...) items (FUN_01009249/FUN_01009349; tag
    404, a direction vector, is the only 3-value one)."""
    stream = _tag10_stream(entry)
    for i in range(0, len(stream) - 1, 2):
        if stream[i] != tag:
            continue
        variant = next((v for v in pf.entries[stream[i + 1]].variants if v.type_tag == 11), None)
        if variant is None:
            return {}
        values = struct.unpack(f"<{len(variant.raw) // 4}f", variant.raw)
        out: dict[int, tuple[float, ...]] = {}
        j = 0
        while j + 1 < len(values):
            key = int(values[j])
            width = 3 if key == 404 else 1
            out[key] = values[j + 1 : j + 1 + width]
            j += 1 + width
        return out
    return {}


def _preset(pf: partout.PartoutFile, entry: partout.Entry, tag: int) -> dict[int, float]:
    return {key: values[0] for key, values in _preset_values(pf, entry, tag).items()}


def _centroid_and_radius(points: list[Vec2]) -> tuple[Vec2, float]:
    unique = points[:-1] if len(points) > 2 and points[0] == points[-1] else points
    cx = sum(p.x for p in unique) / len(unique)
    cy = sum(p.y for p in unique) / len(unique)
    center = Vec2(cx, cy)
    return center, max((p - center).length() for p in unique)


def _sprite_frames(pf: partout.PartoutFile, entry: partout.Entry) -> int:
    """An object's bitmap list: its own entry (type-0 value 200) plus the
    unnamed continuation entries after it (type-0 value 201)."""
    index = pf.entries.index(entry)
    frames = 1
    for following in pf.entries[index + 1 :]:
        marker = next((v for v in following.variants if v.type_tag == 0), None)
        if marker is None or int.from_bytes(marker.raw, "little", signed=True) != 201:
            break
        frames += 1
    return frames


def _mask(entry: partout.Entry) -> int:
    """FUN_0100950a: collision layer bits from type-10 tag 602 (default 1)."""
    stream = _tag10_stream(entry)
    mask = 0
    for i in range(0, len(stream) - 1, 2):
        if stream[i] == 602:
            mask |= 1 << stream[i + 1]
    return mask or 1


def _coefficients(pf: partout.PartoutFile, entry: partout.Entry) -> dict[str, float]:
    """FUN_010190b3's copy of the entry's visual record into the collision
    object: e_n/e_t from the tag-300 preset, threshold/kick from tag 400."""
    bounce = _preset(pf, entry, 300)
    kick = _preset(pf, entry, 400)
    return {
        "restitution": bounce.get(302, c.WALL_RESTITUTION),
        "tangent_retention": bounce.get(301, c.WALL_TANGENT_RETENTION),
        "kick_threshold": kick.get(401, c.NO_KICK_THRESHOLD),
        "kick": kick.get(402, 0.0),
    }


def _table_objects(pf: partout.PartoutFile) -> list[tuple[int, partout.Entry]]:
    """The `table_objects` manifest: a header word, then (type, entry) pairs."""
    manifest = pf.find("table_objects")
    if manifest is None:
        raise ValueError("PINBALL.DAT has no table_objects entry")
    stream = _tag10_stream(manifest)
    return [(t, pf.entries[i]) for t, i in zip(stream[1::2], stream[2::2], strict=False)]


def _walls_from_shape(
    points: list[Vec2], radius: float | None, mask: int, coeffs: dict[str, float], ball_radius: float
) -> tuple[list[Segment], list[Circle]]:
    """FUN_010179a9: n = point count - 1; n == 0 -> a circle of radius r
    (plus the ball radius, see World), n == 1 -> one line wall, otherwise a
    closed loop over the first n points (the last stored point, a repeat of
    the first, is never used): a line wall per edge, and at each corner that
    turns left (cross product > 0) a circle of 1.001 ball radii (0x10024a0).
    Every line wall is moved one ball radius along its normal (FUN_0101c813),
    so the walls are tested against the ball's centre."""
    if len(points) == 1 and radius is not None:
        return [], [Circle(points[0], radius, mask=mask, **coeffs)]
    if len(points) == 2:
        return [Segment(points[0], points[1], one_sided=True, mask=mask, **coeffs)], []
    loop = points[:-1]
    n = len(loop)
    segments = [Segment(loop[i], loop[i + 1] if i + 1 < n else points[-1], mask=mask, **coeffs) for i in range(n)]
    corners = []
    for i in range(n):
        prev, cur, nxt = loop[i - 1], loop[i], loop[(i + 1) % n]
        a, b = cur - prev, nxt - cur
        if a.x * b.y - a.y * b.x > 0.0 and ball_radius > 0.0:
            corners.append(
                Circle(cur, ball_radius * 1.001 - ball_radius, mask=mask, wall=segments[i], **coeffs)
            )
    return segments, corners


def _build_from_real_table() -> TableLayout:
    res = load_table_resources()
    pf = pinball_data()
    cam = load_camera(pf)
    world = World()

    table = pf.find("table")
    ball_entry = pf.find("ball")
    drain = pf.find("drain")
    if table is None or ball_entry is None or drain is None:
        raise ValueError("PINBALL.DAT is missing the table/ball/drain entries")

    gravity = tagged_floats(table, 305) or c.GRAVITY_TRIPLE
    world.gravity = gravity_from_triple(*gravity[:3])
    friction = tagged_floats(table, 701)
    world.friction = friction[0] if friction else c.FRICTION
    radius = tagged_floats(ball_entry, 500)
    ball_radius = radius[0] if radius else c.BALL_RADIUS
    world.max_ball_speed = ball_radius * 200.0

    # Outer walls: FUN_0101a5ab makes one line wall per consecutive pair of
    # the table's tag-600 points, bouncing with the table's tag-400
    # threshold and a literal 15.0 boost.
    table_shape = _shape(table)
    if table_shape is None:
        raise ValueError("table entry has no tag-600 outline")
    outline, _ = table_shape
    threshold = _preset(pf, table, 400).get(401, c.NO_KICK_THRESHOLD)
    # FUN_0101c6fd(next, current): not offset by the ball radius.
    for a, b in itertools.pairwise(outline):
        world.segments.append(
            Segment(b, a, kick_threshold=threshold, kick=c.TABLE_WALL_KICK, one_sided=True, radius_offset=False)
        )
    world.frame_bounds = (
        min(p.x for p in outline),
        min(p.y for p in outline),
        max(p.x for p in outline),
    )
    # FUN_0101a5ab: the grid spans the box of the outline's first three points.
    corner = outline[:3]
    gx0, gy0 = min(p.x for p in corner), min(p.y for p in corner)
    world.grid = Grid(gx0, gy0, max(p.x for p in corner) - gx0, max(p.y for p in corner) - gy0)

    drain_shape = _shape(drain)
    world.drain_y = drain_shape[0][0].y if drain_shape else max(p.y for p in outline)

    gravity_magnitude = gravity[0]
    objects = _table_objects(pf)
    ramps = [
        _build_ramp(entry, gravity_magnitude, world)
        for type_id, entry in objects
        if type_id == RAMP_TYPE
    ]
    ramp_holes: list[RampHole] = []
    gates: dict[str, Gate] = {}
    kickbacks: list[Kickback] = []
    wall_targets: list[WallTarget] = []
    sinks: list[Sink] = []
    kickouts: list[Kickout] = []
    rollovers: list[Rollover] = []
    flags: list[Flag] = []
    passes: list[PassLine] = []
    center_post: CenterPost | None = None
    switches: list[WallSwitch] = []
    for type_id, entry in objects:
        shape = _shape(entry)
        if shape is None:
            continue
        points, radius = shape
        mask = _mask(entry)
        coeffs = _coefficients(pf, entry)
        if type_id in ROLLOVER_TYPES:
            rollovers.append(_build_rollover(entry, points, mask, world, lights_on_entry=type_id == 0x3FC))
            continue
        if type_id == FLAG_TYPE:
            flags.append(_build_flag(pf, entry, points, mask, world))
            continue
        if type_id == TRIP_TYPE:
            # FUN_010179a9 with one segment: a line wall a->b moved one ball
            # radius out along its normal; FUN_010165ed only reports the pass.
            trip = PassLine(entry.name)
            line = TripLine(points[0], points[1], mask, trip.cross)
            world.trip_lines.append(line.offset(ball_radius))
            passes.append(trip)
            continue
        if type_id == CENTER_POST_TYPE:
            segments, corners = _walls_from_shape(points, radius, mask, coeffs, ball_radius)
            for segment in segments:
                segment.active = False
            world.segments.extend(segments)
            world.circles.extend(corners)
            center_post = CenterPost(entry.name, segments)
            continue
        if type_id in WALL_TYPES:
            segments, circles = _walls_from_shape(points, radius, mask, coeffs, ball_radius)
            if entry.name:
                switch = WallSwitch(entry.name, kick_threshold=coeffs["kick_threshold"], kick=coeffs["kick"])
                for segment in segments:
                    segment.behavior = switch
                for circle in circles:
                    circle.behavior = switch
                switches.append(switch)
            world.segments.extend(segments)
            world.circles.extend(circles)
        elif type_id == ONE_WAY_TYPE:
            # FUN_01019204: a blocking line a->b, plus the reversed line b->a
            # (+0x52) moved -0.8 ball radius along its own normal, whose hit
            # only reports the pass (FUN_01018032).
            world.segments.append(Segment(points[0], points[1], one_sided=True, mask=mask, **coeffs))
            back = PassLine(entry.name)
            line = TripLine(points[1], points[0], mask, back.cross)
            world.trip_lines.append(line.offset(-ONE_WAY_BACK_OFFSET * ball_radius))
            passes.append(back)
        elif type_id == GATE_TYPE:
            segment = Segment(points[0], points[1], one_sided=True, mask=mask, **coeffs)
            world.segments.append(segment)
            gates[entry.name] = Gate(entry.name, segment)
        elif type_id in TARGET_TYPES:
            reset = tagged_floats(entry, 407)
            target = WallTarget(
                entry.name,
                kick_threshold=coeffs["kick_threshold"],
                kick=coeffs["kick"],
                drop_time=DROP_TARGET_RAISE_DELAY if type_id == DROP_TARGET_TYPE else 0.0,
                reset_delay=reset[0] if reset else 0.25,
            )
            segments, corners = _walls_from_shape(points, radius, mask, coeffs, ball_radius)
            for segment in segments:
                segment.behavior = target
            target.segments = segments
            world.segments.extend(segments)
            world.circles.extend(corners)
            wall_targets.append(target)
        elif type_id in KICKOUT_TYPES and radius is not None:
            launch = _preset_values(pf, entry, 400)
            capture_fraction = tagged_floats(entry, 306)
            strength = tagged_floats(entry, 305)
            direction = launch.get(404, (0.0, -1.0, 0.0))
            kickout = Kickout(
                entry.name,
                center=points[0],
                field_radius=radius,
                capture_radius=max(radius * capture_fraction[0], 0.001) if capture_fraction else 0.001,
                strength=strength[0] if strength else 0.0,
                direction=Vec2(direction[0], direction[1]),
                spread=launch.get(405, (0.0,))[0],
                speed=launch.get(402, (0.0,))[0],
                variation=launch.get(403, (0.0,))[0] * 0.01,
                active=type_id == KICKOUT_TYPE,
                stays_off=type_id == GRAVITY_WELL_KICKOUT_TYPE,
                mask=mask,
            )
            world.fields.append(kickout)
            kickouts.append(kickout)
        elif type_id == SINK_TYPE:
            launch = _preset_values(pf, entry, 400)
            exit_point = tagged_floats(entry, 601)
            delay = tagged_floats(entry, 407)
            direction = launch.get(404, (0.0, -1.0, 0.0))
            sink = Sink(
                entry.name,
                exit_position=Vec2(exit_point[0], exit_point[1]) if exit_point else points[0],
                direction=Vec2(direction[0], direction[1]),
                spread=launch.get(405, (0.0,))[0],
                speed=launch.get(402, (0.0,))[0],
                variation=launch.get(403, (0.0,))[0] * 0.01,
                eject_delay=delay[0] if delay else 2.0,
            )
            world.segments.append(Segment(points[0], points[1], one_sided=True, mask=mask, behavior=sink, **coeffs))
            sinks.append(sink)
        elif type_id == RAMP_HOLE_TYPE and radius is not None:
            hole = _build_ramp_hole(entry, points[0], radius, mask, gravity_magnitude)
            world.fields.append(hole)
            ramp_holes.append(hole)
        elif type_id == KICKBACK_TYPE:
            kickback = Kickback(entry.name, kick=coeffs["kick"])
            # FUN_0101983d overrides the preset's threshold with 1e9; the
            # kickback's own handler drives it from then on.
            coeffs["kick_threshold"] = c.NO_KICK_THRESHOLD
            segment = Segment(points[0], points[1], one_sided=True, mask=mask, behavior=kickback, **coeffs)
            world.segments.append(segment)
            kickbacks.append(kickback)

    # Plunger (FUN_0101a4f3): its tag-600 segment is a one-sided line wall,
    # the face the ball rests on, spanning the lane; the ball is served at
    # its tag-601 point (stored into the simulation at +0x11e/+0x122).
    plunger_entry = pf.find("plunger")
    plunger_shape = _shape(plunger_entry) if plunger_entry else None
    serve = tagged_floats(plunger_entry, 601) if plunger_entry else None
    if plunger_shape is None or serve is None:
        raise ValueError("plunger entry lacks its tag-600 face / tag-601 serve point")
    face_a, face_b = plunger_shape[0][0], plunger_shape[0][1]
    plunger_rest = Vec2(serve[0], serve[1])
    plunger = Plunger(step=float(int(100.0 / (_sprite_frames(pf, plunger_entry) * 8.0))))
    world.segments.append(
        Segment(
            face_a,
            face_b,
            restitution=PLUNGER_BOUNCE,
            tangent_retention=PLUNGER_BOUNCE,
            one_sided=True,
            behavior=plunger,
        )
    )

    bumpers: list[Circle] = []
    for sprite in res.by_category("a_bump"):
        entry = pf.find(sprite.name)
        shape = _shape(entry) if entry else None
        if shape is None or shape[1] is None:
            continue
        # FUN_01015d0f: after a kick the bumper's threshold is 1e9 for its
        # tag-407 time (0.1 s), then restored (FUN_01015cb2).
        lockout = tagged_floats(entry, 407)
        circle = Circle(
            shape[0][0],
            radius=shape[1],
            mask=_mask(entry),
            cooldown=lockout[0] if lockout else c.BUMPER_COOLDOWN,
            name=sprite.name,
            **_coefficients(pf, entry),
        )
        bumpers.append(circle)
        world.circles.append(circle)

    flip_sprites = sorted(res.by_category("a_flip"), key=lambda s: s.center[0])
    left_flipper, right_flipper = _build_flippers(pf, flip_sprites, cam, ball_radius)
    for flipper in (left_flipper, right_flipper):
        flipper.cells = world.grid.cells_in_box(*flipper.bounding_box())
    world.flippers.extend([left_flipper, right_flipper])

    return TableLayout(
        world=world,
        left_flipper=left_flipper,
        right_flipper=right_flipper,
        plunger_rest=plunger_rest,
        plunger=plunger,
        camera=cam,
        screen_size=res.table_size,
        ball_radius=ball_radius,
        resources=res,
        wall_targets=wall_targets,
        rollovers=rollovers,
        flags=flags,
        passes=passes,
        switches=switches,
        center_post=center_post,
        gates=list(gates.values()),
        kickbacks=kickbacks,
        sinks=sinks,
        kickouts=kickouts,
        ramps=ramps,
        ramp_holes=ramp_holes,
        bumpers=bumpers,
        left_flipper_sprite=flip_sprites[0],
        right_flipper_sprite=flip_sprites[-1],
    )


def _polygon(points: list[Vec2]) -> list[tuple[Vec2, Vec2]]:
    """FUN_010179a9's closed loop over the first n-1 points."""
    loop = points[:-1]
    return list(zip(loop, loop[1:] + loop[:1], strict=True))


def _build_rollover(
    entry: partout.Entry, points: list[Vec2], mask: int, world: World, lights_on_entry: bool = False
) -> Rollover:
    """FUN_010182e4: the tag-600 loop on the +5 (armed) byte and the tag-603
    loop (same polygon, reversed) on the +0x4e (inside) byte, both bare
    centre lines (no ball-radius offset)."""
    light_time = tagged_floats(entry, 407) if lights_on_entry else None
    rollover = Rollover(
        entry.name, mask=mask, lights_on_entry=lights_on_entry, light_time=light_time[0] if light_time else 0.0
    )
    for a, b in _polygon(points):
        world.trip_lines.append(TripLine(a, b, mask, rollover.cross, lambda r=rollover: r.armed))
    exit_values = tagged_floats(entry, 603)
    if exit_values is not None:
        count = int(exit_values[0])
        exit_points = [Vec2(exit_values[1 + 2 * i], exit_values[2 + 2 * i]) for i in range(count)]
        for a, b in _polygon(exit_points):
            world.trip_lines.append(TripLine(a, b, mask, rollover.cross, lambda r=rollover: r.inside))
    return rollover


def _build_flag(pf: partout.PartoutFile, entry: partout.Entry, points: list[Vec2], mask: int, world: World) -> Flag:
    """FUN_010194b0: lines P1->P0 and P0->P1 (+0x6a); rate limits tags 1200
    (max, default 50000) / 1201 (min, 5) and decay tag 1202 (0.65)."""
    max_rate = tagged_floats(entry, 1200)
    min_rate = tagged_floats(entry, 1201)
    decay = tagged_floats(entry, 1202)
    flag = Flag(
        entry.name,
        frames=_sprite_frames(pf, entry),
        max_rate=max_rate[0] if max_rate else 50000.0,
        min_rate=min_rate[0] if min_rate else 5.0,
        decay=decay[0] if decay else 0.65,
    )
    p0, p1 = points[0], points[1]
    world.trip_lines.append(TripLine(p1, p0, mask, lambda ball: flag.cross(ball, reverse=False)))
    world.trip_lines.append(TripLine(p0, p1, mask, lambda ball: flag.cross(ball, reverse=True)))
    return flag


def _build_ramp(entry: partout.Entry, gravity_magnitude: float, world: World) -> Ramp:
    """FUN_01019bb8. Tag 1300 = count + 13-float triangle records; 1301 /
    1302 = (layer, entry-allowed flag, 2, A, B, height): the mesh edges
    nearest A->B (FUN_01016b27) link the ramp to `layer`; 1303 = (layer, 2,
    P, Q): the score line Q->P on that layer; 1305 = set the height on exit;
    701 = friction. Builds the ramp's trip lines into `world`."""
    mesh = tagged_floats(entry, 1300)
    if mesh is None:
        raise ValueError(f"{entry.name} has no tag-1300 mesh")
    friction = tagged_floats(entry, 701)
    height_flag = tagged_floats(entry, 1305)
    mask = _mask(entry)
    triangles: list[RampTriangle] = []
    for k in range(int(mesh[0])):
        r = mesh[1 + 13 * k : 14 + 13 * k]
        slope, direction = r[9], r[10]
        triangles.append(
            RampTriangle(
                plane=(r[0], r[1], r[2]),
                vertices=(Vec2(r[3], r[4]), Vec2(r[5], r[6]), Vec2(r[7], r[8])),
                gravity=Vec2(math.cos(direction), math.sin(direction)) * (math.sin(slope) * gravity_magnitude),
            )
        )
    xs = [v.x for t in triangles for v in t.vertices]
    ys = [v.y for t in triangles for v in t.vertices]
    bounds = (min(xs), min(ys), max(xs), max(ys))
    ramp = Ramp(
        entry.name,
        mask=mask,
        friction=friction[0] if friction else 0.2,
        bounds=bounds,
        triangles=triangles,
        set_height_on_exit=bool(height_flag and int(height_flag[0])),
        grid=world.grid,
        cells=world.grid.cells_in_box(*bounds) if world.grid is not None else frozenset(),
    )

    def link(tag: int) -> tuple[int, int, int, int, float]:
        """(triangle, edge index, layer mask, entry mask, height) for a
        1301/1302 tag; edge i runs vertex i -> vertex (i+1) % 3."""
        v = tagged_floats(entry, tag)
        a, b = Vec2(v[3], v[4]), Vec2(v[5], v[6])
        best = None
        for k, tri in enumerate(triangles):
            for i in range(3):
                s, e = tri.vertices[i], tri.vertices[(i + 1) % 3]
                d = (a - s).length() + (b - e).length()
                if best is None or d < best[0]:
                    best = (d, k, i)
        layer_mask = 1 << math.floor(v[0])
        return best[1], best[2], layer_mask, layer_mask if math.floor(v[1]) else 0, v[7]

    links = [link(1301), link(1302)]
    for k, tri in enumerate(triangles):
        for i in range(3):
            s, e = tri.vertices[i], tri.vertices[(i + 1) % 3]
            edge_mask = mask
            for lk, li, _, entry_mask, _ in links:
                if (lk, li) == (k, i):
                    edge_mask = entry_mask
                    break
            if edge_mask:
                world.trip_lines.append(TripLine(s, e, edge_mask, lambda ball, t=tri: ramp.enter(ball, t)))
    for lk, li, layer_mask, _, height in links:
        tri = triangles[lk]
        s, e = tri.vertices[li], tri.vertices[(li + 1) % 3]
        world.trip_lines.append(
            TripLine(e, s, mask, lambda ball, m=layer_mask, h=height: ramp.leave(ball, m, h))
        )
    score = tagged_floats(entry, 1303)
    if score is not None:
        world.trip_lines.append(
            TripLine(
                Vec2(score[4], score[5]),
                Vec2(score[2], score[3]),
                1 << math.floor(score[0]),
                lambda ball: ramp.score_line(ball),
            )
        )
    world.ramps.append(ramp)
    return ramp


def _build_ramp_hole(
    entry: partout.Entry, center: Vec2, radius: float, mask: int, gravity_magnitude: float
) -> RampHole:
    """FUN_01019a1c: field radius = shape radius, capture radius = shape
    radius * tag 306, strength = tag 305, drop friction = tag 701, floor =
    tag 408's third value, exit layer = tag 1304 (used as the mask itself)."""
    capture = tagged_floats(entry, 306)
    strength = tagged_floats(entry, 305)
    friction = tagged_floats(entry, 701)
    floor = tagged_floats(entry, 408)
    exit_layer = tagged_floats(entry, 1304)
    return RampHole(
        entry.name,
        center=center,
        field_radius=radius,
        capture_radius=radius * capture[0] if capture else 0.001,
        strength=strength[0] if strength else 0.0,
        mask=mask,
        drop_friction=friction[0] if friction else 0.5,
        floor_z=floor[2] if floor else radius,
        exit_mask=math.floor(exit_layer[0]) if exit_layer else 1,
        gravity_magnitude=gravity_magnitude,
    )


def _build_flippers(
    pf: partout.PartoutFile, flip_sprites: list[SpriteObject], cam: Camera, ball_radius: float
) -> tuple[Flipper, Flipper]:
    """Each flipper's edge straight from its own tags (FUN_0101c59d ->
    FUN_0101c2ba): 800 = pivot circle (x, y, r), 801 = tip circle at rest,
    802 = tip fully extended, 803 = kick factor, 804 / 805 = seconds for a
    full extend / retract; e_n / e_t from the entry's collision preset."""
    if len(flip_sprites) < 2:
        raise ValueError("expected at least 2 flipper sprites")
    flippers = []
    for sprite in (flip_sprites[0], flip_sprites[-1]):
        entry = pf.find(sprite.name)
        tags = {tag: tagged_floats(entry, tag) if entry else None for tag in (800, 801, 802, 803, 804, 805)}
        if any(tags[tag] is None for tag in (800, 801, 802, 804, 805)):
            raise ValueError(f"{sprite.name} lacks flipper tags 800-805")
        pivot = Vec2(tags[800][0], tags[800][1])
        coefficients = _coefficients(pf, entry)
        flippers.append(
            Flipper(
                pivot=pivot,
                radius=tags[800][2],
                rest_tip=Vec2(tags[801][0], tags[801][1]),
                tip_radius=tags[801][2],
                extended_tip=Vec2(tags[802][0], tags[802][1]),
                up_time=tags[804][0],
                down_time=tags[805][0],
                ball_radius=ball_radius,
                kick_factor=tags[803][0] if tags[803] else 0.9,
                restitution=coefficients["restitution"],
                tangent_retention=coefficients["tangent_retention"],
                mask=_mask(entry),
                is_left=cam.to_screen(pivot).x < cam.to_screen(Vec2(0.0, pivot.y)).x,
            )
        )
    left, right = sorted(flippers, key=lambda f: cam.to_screen(f.pivot).x)
    return left, right


def _build_default_table() -> TableLayout:
    """Placeholder layout in plain pixel units, with matching pixel-scale
    physics, for when the original assets can't be loaded."""
    w, h = c.TABLE_WIDTH, c.TABLE_HEIGHT
    world = World()
    world.gravity = Vec2(0.0, 420.0)
    world.friction = 0.05
    world.max_ball_speed = 900.0
    world.jitter = False
    world.frame_bounds = (0.0, 0.0, float(w))
    margin = 14

    outline = [
        Vec2(margin, h - 40),
        Vec2(margin, 120),
        Vec2(w * 0.25, 30),
        Vec2(w * 0.75, 30),
        Vec2(w - margin, 120),
        Vec2(w - margin, h - 40),
    ]
    for a, b in itertools.pairwise(outline):
        world.segments.append(Segment(a, b))

    lane_x = w - margin - 28
    world.segments.append(Segment(Vec2(lane_x, h - 40), Vec2(lane_x, 140)))
    plunger = Plunger(step=10.0, max_kick=900.0)
    world.segments.append(
        Segment(Vec2(lane_x, h - 48), Vec2(w - margin, h - 48), one_sided=True, behavior=plunger)
    )

    bumpers: list[Circle] = []
    for pos in (Vec2(w * 0.35, h * 0.35), Vec2(w * 0.5, h * 0.28), Vec2(w * 0.65, h * 0.35)):
        circle = Circle(pos, radius=18, kick_threshold=40.0, kick=260.0, cooldown=c.BUMPER_COOLDOWN)
        bumpers.append(circle)
        world.circles.append(circle)

    for pos in (Vec2(w * 0.3, h * 0.55), Vec2(w * 0.7, h * 0.55)):
        world.circles.append(Circle(pos, radius=8))

    rest = math.radians(c.FLIPPER_REST_ANGLE_DEG)
    active = math.radians(c.FLIPPER_ACTIVE_ANGLE_DEG)

    def placeholder_flipper(pivot: Vec2, rest_angle: float, active_angle: float, is_left: bool) -> Flipper:
        arm = Vec2(math.cos(rest_angle), math.sin(rest_angle)) * c.FLIPPER_LENGTH
        up = Vec2(math.cos(active_angle), math.sin(active_angle)) * c.FLIPPER_LENGTH
        return Flipper(
            pivot=pivot,
            radius=9.0,
            rest_tip=pivot + arm,
            tip_radius=6.0,
            extended_tip=pivot + up,
            up_time=0.04,
            down_time=0.08,
            ball_radius=4.5,
            is_left=is_left,
        )

    left_flipper = placeholder_flipper(Vec2(w * 0.38, h - 40), math.pi - rest, math.pi - active, True)
    right_flipper = placeholder_flipper(Vec2(w * 0.62, h - 40), active, rest, False)
    world.flippers.extend([left_flipper, right_flipper])
    world.drain_y = h - 4

    return TableLayout(
        world=world,
        left_flipper=left_flipper,
        right_flipper=right_flipper,
        plunger_rest=Vec2(lane_x + 8.0, h - 60),
        plunger=plunger,
        ball_radius=4.5,
        bumpers=bumpers,
    )
