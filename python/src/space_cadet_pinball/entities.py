"""Scoring/feature entities beyond plain walls and bumpers: targets, lanes,
kickers and the gravity well -- the signature Space Cadet table features."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from .ball import Ball
from .geometry import Segment
from .grid import Grid
from .vec2 import Vec2


def _rotate_like_original(v: Vec2, angle: float) -> Vec2:
    """FUN_0101ccf3, including its quirk: the new y is computed from the
    already-rotated x (y' = sin*x' + cos*y)."""
    s, co = math.sin(angle), math.cos(angle)
    x = co * v.x - s * v.y
    return Vec2(x, s * x + co * v.y)


def launch_ball(ball: Ball, direction: Vec2, spread: float, speed: float, variation: float) -> None:
    """FUN_01015935: aim the ball along `direction` (copied as-is, not
    normalised) turned by spread * U(-1, 1), at speed * (1 + variation *
    U(-1, 1)), where U = 1 - 2 * rand() * 3.0518e-5."""
    turned = _rotate_like_original(direction, (1.0 - 2.0 * random.random()) * spread)
    ball.velocity = turned * (speed + (1.0 - 2.0 * random.random()) * speed * variation)


@dataclass(slots=True)
class Sink:
    """`v_sink1/2/3/7` (type 0x3f9, FUN_0101a416): a one-sided line across a
    hole's mouth. Its collision handler FUN_010184ed takes the ball out of
    play on contact (bouncing off instead while tilted) and notifies the
    listener, which sends 0x38 back with the tag-407 delay (2.0 s); the
    timer (FUN_01017130) puts the ball on the tag-601 exit point and
    launches it with the tag-400 preset: 404 direction, 405 spread, 402
    speed, 403 * 0.01 speed variation.

    The wormholes (v_sink1..3, listener FUN_0100d303, game.py) can instead
    route the ball out of a *different* sink when the wormhole lights say
    so (`ball_source` hands the sink the ball to eject)."""

    name: str
    exit_position: Vec2
    direction: Vec2
    spread: float
    speed: float
    variation: float
    eject_delay: float
    held_ball: Ball | None = None
    timer: float | None = None
    data: int = 0
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    sound: Callable[[], float] | None = field(default=None, repr=False)
    # The ball the 0x38 timer puts back in play: the listener may route the
    # ball captured by one sink out of another (the wormholes).
    ball_source: Callable[[], Ball | None] | None = field(default=None, repr=False)
    on_eject: Callable[[Sink], None] | None = field(default=None, repr=False)

    def capture(self, ball: Ball, tilted: bool) -> bool:
        """FUN_010184ed: out of play (the ball's active byte cleared, its
        sprite hidden), the sink's sound (+0x7a), then 0x3f to the listener,
        which answers with 0x38 and a delay. Tilted, the ball just bounces."""
        if tilted:
            return False
        ball.held = True
        ball.velocity = Vec2(0.0, 0.0)
        self.held_ball = ball
        if self.sound:
            self.sound()
        if self.notify:
            self.notify(0x3F, self)
        return True

    def message(self, code: int, value: float = 0.0) -> int:
        """FUN_01017197: 0x38 = eject (from this sink) after `value` seconds,
        or the tag-407 delay if negative; 0x400 = cancel."""
        if code == 0x38:
            self.timer = self.eject_delay if value < 0 else value
        elif code == 0x400:
            self.timer = None
            self.data = 0
        return 0

    def kick_for_contact(self, tilted: bool) -> tuple[float, float]:
        return 1.0e9, 0.0

    def after_bounce(self, impact: float, threshold: float, tilted: bool) -> None:
        pass

    def update(self, dt: float) -> None:
        if self.timer is None:
            return
        self.timer -= dt
        if self.timer > 0:
            return
        self.timer = None
        self.held_ball = None
        ball = self.ball_source() if self.ball_source else None
        if ball is None or not ball.alive:
            return
        ball.held = False
        ball.position = self.exit_position.copy()
        launch_ball(ball, self.direction, self.spread, self.speed, self.variation)
        if self.on_eject:
            self.on_eject(self)


@dataclass(slots=True)
class WallTarget:
    """A real target: its tag-600 polygon is a solid wall (the base
    constructor is called with walls on), and its collision handler decides
    the hit.

    - `a_targ1..9` (type 0x3ee, FUN_010195e0 / handler FUN_010181ed): a hit
      counts only when the impact exceeds the tag-400 threshold (3.0); it
      bounces with the preset's kick (5) and notifies the listener (0x3f).
    - `a_targ10..22` (type 0x3fb, FUN_0101961f / handler FUN_01018295): the
      same, and the target also drops (message 0x31 -> inactive) and pops
      back up `drop_time` (+0x56 = 0.1 s) later (FUN_0101620b -> 0x32).
    While tilted both bounce with threshold 1e9 / kick 0, so nothing counts.
    """

    name: str
    kick_threshold: float
    kick: float
    segments: list[Segment] = field(default_factory=list)
    drop_time: float = 0.0  # a_targ10..22: back up after +0x56 = 0.1 s
    reset_delay: float = 0.25  # a_targ1..9: tag 407, the delay of message 0x32
    up: bool = True  # +5 (and its sprite)
    data: int = 0
    _down_timer: float = 0.0
    _raise_timer: float = 0.0
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    sound: Callable[[], float] | None = field(default=None, repr=False)

    def capture(self, ball: Ball, tilted: bool) -> bool:
        return False

    def kick_for_contact(self, tilted: bool) -> tuple[float, float]:
        return (1.0e9, 0.0) if tilted else (self.kick_threshold, self.kick)

    def after_bounce(self, impact: float, threshold: float, tilted: bool) -> None:
        if tilted or impact <= threshold:
            return
        if self.sound:
            self.sound()
        self.message(0x31)
        if self.drop_time > 0:
            self._down_timer = self.drop_time
        if self.notify:
            self.notify(0x3F, self)

    def message(self, code: int, value: float = 0.0) -> int:
        """0x31 = down (inactive, sprite hidden); 0x32 = back up -- at once
        for a drop target (FUN_01016230), after `reset_delay` for a standup
        one (FUN_010160f4); 0x400 = reset."""
        if code == 0x31:
            self._set_up(False)
        elif code == 0x32:
            if self.drop_time > 0:
                self._set_up(True)
            else:
                self._raise_timer = self.reset_delay
        elif code == 0x400:
            self.data = 0
            self._down_timer = self._raise_timer = 0.0
            self._set_up(True)
        return 0

    def update(self, dt: float) -> None:
        if self._down_timer > 0:
            self._down_timer -= dt
            if self._down_timer <= 0:
                self.message(0x32)
        if self._raise_timer > 0:
            self._raise_timer -= dt
            if self._raise_timer <= 0:
                self._set_up(True)

    def _set_up(self, up: bool) -> None:
        self.up = up
        for segment in self.segments:
            segment.active = up


@dataclass(slots=True, eq=False)
class Rollover:
    """`a_roll*` (type 0x3f7, FUN_01019771 / collision FUN_01018351): the
    same polygon twice as centre-crossing trip lines -- tag 600 wound so its
    edges fire as the ball enters, tag 603 the other way round so they fire
    as it leaves. Entering (while armed, +5) plays its sound (tag 304),
    notifies 0x3f and lights the switch sprite (+0x4e); leaving disarms it
    for 0.1 s (FUN_0101644b). Nothing happens while tilted.

    Its sprite (`shown`): a plain rollover shows frame 0 except while the
    ball is inside (FUN_01018351, reset FUN_01016460). `a_roll9` (type 0x3fc,
    FUN_010197bb / collision FUN_010164f2) starts hidden, shows frame 0 when
    the ball enters and hides `light_time` (tag 407) after it leaves, unless
    that timer is already running (FUN_010164d1); its reset hides it
    (FUN_010165a7).
    """

    name: str
    mask: int = 1
    armed: bool = True  # +5: the entry lines' active byte
    inside: bool = False  # +0x4e: the exit lines' active byte
    lights_on_entry: bool = False  # type 0x3fc
    light_time: float = 0.0  # +0x57, tag 407 (type 0x3fc)
    shown: bool = True
    data: int = 0
    _rearm: float = 0.0
    _hide: float | None = None  # +0x5b
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    sound: Callable[[], float] | None = field(default=None, repr=False)
    tilted: Callable[[], bool] = field(default=lambda: False, repr=False)

    def __post_init__(self) -> None:
        self.shown = not self.lights_on_entry

    def cross(self, ball: Ball) -> None:
        if self.tilted():
            return
        if not self.inside:
            if self.sound:
                self.sound()
            if self.notify:
                self.notify(0x3F, self)
            self.shown = self.lights_on_entry
        else:
            self._rearm = 0.1
            self.armed = False
            if not self.lights_on_entry:
                self.shown = True
            elif self._hide is None:
                self._hide = self.light_time
        self.inside = not self.inside

    def message(self, code: int, value: float = 0.0) -> int:
        if code == 0x400:
            self.armed = True
            self.inside = False
            self._rearm = 0.0
            self._hide = None
            self.shown = not self.lights_on_entry
        return 0

    def update(self, dt: float) -> None:
        if self._rearm > 0:
            self._rearm -= dt
            if self._rearm <= 0:
                self.armed = True
        if self._hide is not None:
            self._hide -= dt
            if self._hide <= 0:
                self._hide = None
                self.shown = False


@dataclass(slots=True, eq=False)
class Flag:
    """`a_flag1/2` (type 0x3fa, FUN_010194b0 / collision FUN_01018150): a
    spinning flag on two opposite centre-crossing lines between its two
    tag-600 points. A pass sets the spin direction (+1 through the first
    line, -1 through the second) and rate = ball speed * 20, clamped to
    [tag 1201, tag 1200]; each spin step (FUN_01015f4e) advances the sprite
    frame, notifies 0x3f (and 0x3e at frame 0), plays tag 304 and multiplies
    the rate by tag 1202, re-running after 1/rate s while the rate stays at
    least tag 1201. A new pass starts another step chain without stopping
    the old one, as the original does."""

    name: str
    frames: int
    max_rate: float
    min_rate: float
    decay: float
    schedule: Callable[[float, Callable[[], None]], object] | None = field(default=None, repr=False)
    frame: int = 0
    direction: int = 1
    rate: float = 0.0
    data: int = 0
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    sound: Callable[[], float] | None = field(default=None, repr=False)
    tilted: Callable[[], bool] = field(default=lambda: False, repr=False)

    def cross(self, ball: Ball, reverse: bool) -> None:
        self.direction = -1 if reverse else 1
        speed = ball.speed()
        self.rate = speed * 20.0 if speed != 0.0 else self.min_rate
        self.rate = min(max(self.rate, self.min_rate), self.max_rate)
        self.step()

    def step(self) -> None:
        self.frame += self.direction
        if self.frame >= self.frames:
            self.frame = 0
        elif self.frame < 0:
            self.frame = self.frames - 1
        if not self.tilted():
            if self.notify:
                self.notify(0x3F, self)
            if self.sound:
                self.sound()
            if self.frame == 0 and self.notify:
                self.notify(0x3E, self)
        self.rate *= self.decay
        if self.min_rate <= self.rate and self.schedule is not None:
            self.schedule(1.0 / self.rate, self.step)

    def message(self, code: int, value: float = 0.0) -> int:
        if code == 0x400:
            self.frame = 0
        return 0


@dataclass(slots=True, eq=False)
class PassLine:
    """A line whose hit only reports the pass (0x3f, unless tilted, plus the
    object's sound): the trip lines `s_trip*` (type 0x400, FUN_01019816 /
    FUN_010165ed) and the back line of each one-way wall `s_onewy*`
    (FUN_01019204 / FUN_01018032)."""

    name: str
    data: int = 0
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    sound: Callable[[], float] | None = field(default=None, repr=False)
    tilted: Callable[[], bool] = field(default=lambda: False, repr=False)

    def cross(self, ball: Ball) -> None:
        if self.tilted():
            return
        if self.sound:
            self.sound()
        if self.notify:
            self.notify(0x3F, self)

    def message(self, code: int, value: float = 0.0) -> int:
        return 0


@dataclass(slots=True, eq=False)
class WallSwitch:
    """A named wall's own collision handler (types 0x3e8/0x3f2, FUN_010191ba
    / FUN_01017fde over FUN_01017f29) -- the slingshots `v_rebo*`: a hit
    above its kick threshold plays the loud sound (tag 406), shows the
    wall's sprite for 0.1 s and notifies 0x3f; a softer one above 0.2 plays
    the soft sound (tag 304). Tilted: a dead bounce, nothing else.

    Each loud hit starts its own 0.1 s hide timer and none is cancelled, so
    the sprite goes out when the earliest pending one ends (FUN_01015ace);
    0x400 hides it at once (FUN_01015af3)."""

    name: str
    kick_threshold: float
    kick: float
    lit: bool = False  # the sprite is shown
    _hide_timers: list[float] = field(default_factory=list, repr=False)
    data: int = 0
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    sound: Callable[[], float] | None = field(default=None, repr=False)
    soft_sound: Callable[[], float] | None = field(default=None, repr=False)

    def capture(self, ball: Ball, tilted: bool) -> bool:
        return False

    def kick_for_contact(self, tilted: bool) -> tuple[float, float]:
        return (1.0e9, 0.0) if tilted else (self.kick_threshold, self.kick)

    def after_bounce(self, impact: float, threshold: float, tilted: bool) -> None:
        if tilted:
            return
        if impact > threshold:
            if self.sound:
                self.sound()
            self.lit = True
            self._hide_timers.append(0.1)
            if self.notify:
                self.notify(0x3F, self)
        elif impact > 0.2 and self.soft_sound:
            self.soft_sound()

    def update(self, dt: float) -> None:
        remaining = [t - dt for t in self._hide_timers]
        if any(t <= 0 for t in remaining):
            self.lit = False
        self._hide_timers = [t for t in remaining if t > 0]

    def message(self, code: int, value: float = 0.0) -> int:
        if code == 0x400 and self._hide_timers:
            self._hide_timers.pop()
            self.lit = False
        return 0


@dataclass(slots=True, eq=False)
class CenterPost:
    """`v_bloc1` (type 0x3f3, FUN_01019677; messages FUN_0101631c): the
    center post between the flippers, a solid polygon that starts down.
    0x34 raises it (sound +0x5a) for `value` s, 0x3b keeps it up `value` s
    more, 0x33 drops it (sound +0x5e), 0x400 resets; when a raise/keep timer
    ends (FUN_010162ff) it notifies 0x3c and the listener decides."""

    name: str
    segments: list[Segment] = field(default_factory=list)
    up_time: float = 55.0  # +0x4e
    warn_time: float = 5.0  # +0x52
    up: bool = False
    data: int = 0
    _timer: float | None = None
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)

    def message(self, code: int, value: float = 0.0) -> int:
        if code in (0x33, 0x3F3, 0x3FC, 0x400):
            self._timer = None
            self.data = 0
            self._set_up(False)
        elif code in (0x34, 0x3B):
            if code == 0x34:
                self._set_up(True)
            self._timer = max(value, 0.0)
        return 0

    def _set_up(self, up: bool) -> None:
        self.up = up
        for segment in self.segments:
            segment.active = up

    def update(self, dt: float) -> None:
        if self._timer is None:
            return
        self._timer -= dt
        if self._timer <= 0:
            self._timer = None
            if self.notify:
                self.notify(0x3C, self)


@dataclass(slots=True)
class Kickout:
    """`a_kout1..3` (types 0x3f4/0x405, FUN_01019884): a hole with its own
    attraction field, built without walls.

    - Field (vtable slot 6, FUN_0101685b): while not holding a ball and the
      ball is within the shape radius, adds `strength * unit(center - p) - v`
      to its acceleration (strength = tag 305), on top of the table's own
      gravity/friction.
    - Capture (slot 5, FUN_01016745): a bare circle of radius shape radius *
      tag 306 (no ball radius added) -- once the ball's centre is inside it,
      the ball is held at the centre; the listener answers 0x37 with a
      negative delay (default +0x5a = 1.5 s), or the kickout uses 0.1 s while
      tilted.
    - Eject (FUN_010167dd): launch from the centre with the tag-400 preset
      (as for sinks), then the kickout is inactive for +0x5e = 0.05 s.
    - `a_kout1` (type 0x405) starts inactive (+0x52 set): it's the gravity
      well, switched on by its listener / missions (game.py).
    """

    name: str
    center: Vec2
    field_radius: float
    capture_radius: float
    strength: float
    direction: Vec2
    spread: float
    speed: float
    variation: float
    eject_delay: float = 1.5
    rearm_delay: float = 0.05
    active: bool = True
    mask: int = 1
    # a_kout1 (+0x52): stays inactive after an eject until a mission arms it.
    stays_off: bool = False
    hold_z: float | None = None  # +0x62: the ball's height while held
    held_ball: Ball | None = None
    data: int = 0
    _eject_timer: float | None = None
    _rearm_timer: float | None = None
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    sound: Callable[[], float] | None = field(default=None, repr=False)

    def accel(self, ball: Ball) -> Vec2 | None:
        if not self.active or self.held_ball is not None or not self.mask & ball.mask:
            return None
        to_center = self.center - ball.position
        if to_center.length_sq() >= self.field_radius * self.field_radius:
            return None
        return to_center.normalized() * self.strength - ball.velocity

    def can_capture(self, ball: Ball) -> bool:
        return self.active and self.held_ball is None and bool(self.mask & ball.mask)

    def try_capture(self, ball: Ball, tilted: bool, force: bool = False) -> bool:
        """FUN_01016745, when the ball's centre reaches the capture circle
        (`force`: the swept test already found the contact)."""
        if not self.can_capture(ball):
            return False
        if not force and (ball.position - self.center).length() >= self.capture_radius:
            return False
        ball.held = True
        ball.velocity = Vec2(0.0, 0.0)
        ball.position = self.center.copy()
        if self.hold_z is not None:
            ball.z = self.hold_z
        self.held_ball = ball
        if tilted:
            self.message(0x37, 0.1)
        else:
            if self.sound:
                self.sound()
            if self.notify:
                self.notify(0x3F, self)
        return True

    def message(self, code: int, value: float = 0.0) -> int:
        """FUN_010168e3: 0x37 = eject after `value` s (+0x5a = 1.5 s if
        negative); 0x3f3 / 0x400 = eject now, and a_kout1 goes inactive."""
        if code == 0x37:
            if self.held_ball is not None:
                self._eject_timer = self.eject_delay if value < 0 else value
        elif code in (0x3F3, 0x400):
            if code == 0x400 and self.held_ball is not None:
                self._eject_timer = 0.0
                self.update(0.0)
            if self.stays_off:
                self.active = False
        return 0

    def update(self, dt: float) -> None:
        if self._rearm_timer is not None:
            self._rearm_timer -= dt
            if self._rearm_timer <= 0:
                self._rearm_timer = None
                if not self.stays_off:
                    self.active = True
        if self._eject_timer is None:
            return
        self._eject_timer -= dt
        if self._eject_timer > 0:
            return
        self._eject_timer = None
        ball, self.held_ball = self.held_ball, None
        if ball is None or not ball.alive:
            return
        ball.held = False
        ball.z = ball.radius
        launch_ball(ball, self.direction, self.spread, self.speed, self.variation)
        self.active = False
        if not self.stays_off:
            self._rearm_timer = self.rearm_delay


@dataclass(slots=True)
class RampTriangle:
    """One record of a ramp's tag-1300 mesh (13 floats): the plane
    z = a*x + b*y + c, three vertices, a slope and a direction angle, and the
    gravity the constructor stores back into the record (FUN_01019bb8):
    sin(slope) * (cos(direction), sin(direction)) * the table's gravity
    magnitude (the tag-305 triple's first value, sim+0x10e)."""

    plane: tuple[float, float, float]
    vertices: tuple[Vec2, Vec2, Vec2]
    gravity: Vec2


@dataclass(slots=True)
class Ramp:
    """`ramp` / `s_ramp9` (type 0x3fd, FUN_01019bb8): a triangle mesh on its
    own collision layer (tag 602), built only out of trip lines
    (geometry.TripLine) handled by FUN_01016c24:

    - each triangle edge, crossed into the triangle, puts the ball on the
      ramp's layer and gives it the triangle's plane (its height) and
      gravity;
    - the two edges named by tags 1301/1302 (matched to the mesh by
      FUN_01016b27) connect to other layers: crossing out of the mesh there
      moves the ball to that tag's layer (and, with tag 1305 set, to the
      tag's height); crossing in from that layer is allowed only if the
      tag's flag is set;
    - the tag-1303 line on its own layer scores (message 0x3f to the
      listener, unless tilted).

    Its field (vtable slot 6, FUN_01016d2e) adds the triangle's gravity
    minus `friction` (tag 701) * velocity while the ball is on its layer --
    on top of the table's own gravity and friction, which apply on every
    layer (FUN_0101a5ab registers the table's field with mask 0xffffffff)."""

    name: str
    mask: int
    friction: float
    bounds: tuple[float, float, float, float]  # the mesh's box: min_x, min_y, max_x, max_y
    triangles: list[RampTriangle] = field(default_factory=list)
    set_height_on_exit: bool = False  # tag 1305
    # FUN_0100be21 registers the field in every grid cell the box overlaps,
    # and FUN_0100b316 applies it to a ball in any of those cells (the field
    # itself has no range check). Without a grid: the exact box.
    grid: Grid | None = field(default=None, repr=False)
    cells: frozenset[tuple[int, int]] = frozenset()
    data: int = 0
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    tilted: Callable[[], bool] = field(default=lambda: False, repr=False)

    def accel(self, ball: Ball) -> Vec2 | None:
        if not self.mask & ball.mask:
            return None
        if self.grid is not None:
            if self.grid.cell_of(ball.position) not in self.cells:
                return None
        else:
            min_x, min_y, max_x, max_y = self.bounds
            if not (min_x <= ball.position.x <= max_x and min_y <= ball.position.y <= max_y):
                return None
        return ball.ramp_gravity - ball.velocity * self.friction

    def enter(self, ball: Ball, triangle: RampTriangle) -> None:
        a, b, c = triangle.plane
        ball.ramp_gravity = triangle.gravity.copy()
        ball.z = a * ball.position.x + b * ball.position.y + c + ball.radius
        ball.mask = self.mask

    def leave(self, ball: Ball, layer_mask: int, height: float) -> None:
        ball.mask = layer_mask
        if self.set_height_on_exit:
            ball.z = ball.radius + height

    def score_line(self, ball: Ball) -> None:
        if not self.tilted() and self.notify:
            self.notify(0x3F, self)


@dataclass(slots=True)
class RampHole:
    """`ramp_hole` (type 0x3fe, FUN_01019a1c): the hole at the end of the
    upper-deck track that drops the ball back onto the table.

    - Field (slot 6, FUN_010169c0, not holding): within the shape radius,
      acceleration += `strength` (tag 305) * unit(centre - p) - v, on its own
      layer only.
    - Capture (slot 5, FUN_01018476): a bare circle of radius shape radius *
      tag 306; the ball is held at the centre with no vertical speed, and
      after 0.5 s (FUN_010169a4) it starts to fall.
    - While held (the ball's holder gets slot 6 once per frame with the
      frame time): z_velocity -= gravity magnitude * dt * `drop_friction`
      (tag 701), z += z_velocity; once z <= `floor_z` (tag 408's third value)
      the ball is released at rest on layer `exit_mask` (tag 1304, the value
      itself, not a bit index) and the listener gets 0x3a.
    """

    name: str
    center: Vec2
    field_radius: float
    capture_radius: float
    strength: float
    mask: int
    drop_friction: float
    floor_z: float
    exit_mask: int
    gravity_magnitude: float
    drop_delay: float = 0.5
    held_ball: Ball | None = None
    dropping: bool = False
    data: int = 0
    _timer: float | None = None
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)

    def accel(self, ball: Ball) -> Vec2 | None:
        if self.held_ball is not None or not self.mask & ball.mask:
            return None
        to_center = self.center - ball.position
        if to_center.length_sq() > self.field_radius * self.field_radius:
            return None
        return to_center.normalized() * self.strength - ball.velocity

    def can_capture(self, ball: Ball) -> bool:
        return self.held_ball is None and bool(self.mask & ball.mask)

    def try_capture(self, ball: Ball, tilted: bool, force: bool = False) -> bool:
        if not self.can_capture(ball):
            return False
        if not force and (ball.position - self.center).length() >= self.capture_radius:
            return False
        ball.held = True
        ball.velocity = Vec2(0.0, 0.0)
        ball.position = self.center.copy()
        ball.z_velocity = 0.0
        self.held_ball = ball
        self.dropping = False
        self._timer = self.drop_delay
        if self.notify and not tilted:
            self.notify(0x39, self)
        return True

    def update(self, dt: float) -> None:
        ball = self.held_ball
        if ball is None:
            return
        if self._timer is not None:
            self._timer -= dt
            if self._timer <= 0:
                self._timer = None
                self.dropping = True
        if not self.dropping:
            return
        ball.z_velocity -= self.gravity_magnitude * dt * self.drop_friction
        ball.z += ball.z_velocity
        if ball.z > self.floor_z:
            return
        ball.z = self.floor_z
        ball.z_velocity = 0.0
        ball.mask = self.exit_mask
        ball.velocity = Vec2(0.0, 0.0)
        ball.held = False
        self.held_ball = None
        self.dropping = False
        if self.notify:
            self.notify(0x3A, self)


@dataclass(slots=True)
class Plunger:
    """The `plunger` (type 0x3e9, FUN_0101a4f3): its tag-600 face is a
    one-sided line wall with e_n = e_t = 0.5 (0x10024d0) whose kick is the
    launch. Message handler FUN_010185ad:

    - 0x3ec (key down): kick = 0, then FUN_01017314 adds `step` every
      `tick` (+0x5e = 0.025 s) up to `max_kick` (+0x56 = 100); `step` (+0x5a)
      is int(100 / (sprite frames * 8));
    - 0x3ed (key up): threshold 0 -- the next contact kicks -- and after
      `tick` FUN_010173c8 resets threshold 1e9 / kick 0;
    - collision FUN_0101875f bounces with kick * (1 + 0.1 * rand); while
      tilted it first sends itself 0x3f9 (an automatic full launch: kick =
      `max_kick`, threshold 0, reset after 0.2 s).
    The ball speed cap (60 u/s) applies on top, so pulls past ~55 all launch
    at the cap.
    """

    step: float
    max_kick: float = 100.0
    tick: float = 0.025
    kick: float = 0.0
    threshold: float = 1.0e9
    pulling: bool = False
    _pull_timer: float = 0.0
    _reset_timer: float | None = None

    def capture(self, ball: Ball, tilted: bool) -> bool:
        return False

    def kick_for_contact(self, tilted: bool) -> tuple[float, float]:
        if tilted:
            self.threshold, self.kick = 0.0, self.max_kick
            self._reset_timer = 0.2
        return self.threshold, self.kick * (1.0 + random.random() * 0.1)

    def after_bounce(self, impact: float, threshold: float, tilted: bool) -> None:
        pass

    def press(self) -> None:
        if self.pulling:
            return
        self.pulling = True
        self.threshold = 1.0e9
        self._reset_timer = None
        # FUN_01017314 runs once immediately, then re-arms itself.
        self.kick = min(self.max_kick, self.step)
        self._pull_timer = self.tick

    def release(self) -> None:
        if not self.pulling:
            return
        self.pulling = False
        self.threshold = 0.0
        self._reset_timer = self.tick

    def auto_launch(self) -> None:
        """0x3f9 (Game > Launch Ball): kick = `max_kick`, threshold 0, reset
        after 0.2 s."""
        self.pulling = False
        self.threshold, self.kick = 0.0, self.max_kick
        self._reset_timer = 0.2

    def update(self, dt: float) -> None:
        if self.pulling and self.kick < self.max_kick:
            self._pull_timer -= dt
            while self._pull_timer <= 0 and self.kick < self.max_kick:
                self.kick = min(self.max_kick, self.kick + self.step)
                self._pull_timer += self.tick
        if self._reset_timer is not None:
            self._reset_timer -= dt
            if self._reset_timer <= 0:
                self._reset_timer = None
                self.threshold = 1.0e9
                self.kick = 0.0


@dataclass(slots=True)
class Gate:
    """`v_gate1`/`v_gate2` (type 0x3f5, FUN_010196e5): a one-sided line wall
    across the top of an outlane's kickback slot. Closed (solid) when built;
    its message handler FUN_010163db opens it on 0x35 (clears the active
    byte) and closes it on 0x36/0x400. The plunger's new-ball handler
    (FUN_01012285) opens both; a kickback's listener closes its own gate once
    it has fired (FUN_0100c520/FUN_0100c546, message 0x36)."""

    name: str
    segment: Segment
    data: int = 0
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    open_sound: Callable[[], float] | None = field(default=None, repr=False)
    close_sound: Callable[[], float] | None = field(default=None, repr=False)

    @property
    def is_open(self) -> bool:
        return not self.segment.active

    def set_open(self, is_open: bool) -> None:
        self.segment.active = not is_open

    def message(self, code: int, value: float = 0.0) -> int:
        """FUN_010163db: 0x35 opens, 0x36 / 0x400 close (sounds +0x52 /
        +0x4e); every message but 0x3fc is passed on to the listener."""
        if code == 0x3FC:
            return 0
        if code == 0x35:
            self.set_open(True)
            if self.open_sound:
                self.open_sound()
        elif code in (0x36, 0x400):
            self.set_open(False)
            if code == 0x36 and self.close_sound:
                self.close_sound()
        if self.notify:
            self.notify(code, self)
        return 0


@dataclass(slots=True)
class Kickback:
    """`a_kick1`/`a_kick2` (type 0x3f6, FUN_0101983d): the plate at the
    bottom of an outlane's kickback slot. It's a one-sided line wall with its
    own collision handler FUN_010183e8 -- not a capture hole:

    - first contact while idle: arm (+0x5a), set the kick threshold (+0x42)
      to 1e9 and start an `arm_delay` (+0x4e = 0.7 s) timer, then bounce with
      the plate's dead 0.2/0.7 coefficients (no kick yet);
    - timer (FUN_0101663f): while still armed, drop the threshold to 0 and
      re-run every `ready_period` (+0x52 = 0.1 s); the next contact kicks the
      ball out along the plate normal with the tag-400 kick (55) and disarms;
      once disarmed, the timer stops and notifies the listener (0x3c), which
      closes this side's gate;
    - while tilted it bounces with threshold 0 and the full kick.

    Its sprite (`frame`) starts on frame 0; each armed tick of
    FUN_0101663f shows frame 1, the closing tick frame 0, and a reset while
    the timer runs hides it (FUN_010166f6).
    """

    name: str
    kick: float
    arm_delay: float = 0.7
    ready_period: float = 0.1
    threshold: float = 1.0e9
    armed: bool = False
    timer: float | None = None
    frame: int | None = 0
    data: int = 0
    notify: Callable[[int, object], None] | None = field(default=None, repr=False)
    sound: Callable[[], float] | None = field(default=None, repr=False)

    def capture(self, ball: Ball, tilted: bool) -> bool:
        return False

    def kick_for_contact(self, tilted: bool) -> tuple[float, float]:
        if tilted:
            return 0.0, self.kick
        if not self.armed:
            self.threshold = 1.0e9
            self.armed = True
            self.timer = self.arm_delay
        return self.threshold, self.kick

    def after_bounce(self, impact: float, threshold: float, tilted: bool) -> None:
        # FUN_01017f29 reports a "loud" hit (and plays the preset's sound)
        # only for impact > threshold.
        if not tilted and impact > threshold:
            self.armed = False
            if self.sound:
                self.sound()

    def update(self, dt: float) -> None:
        if self.timer is None:
            return
        self.timer -= dt
        if self.timer > 0:
            return
        if self.armed:
            self.threshold = 0.0
            self.timer = self.ready_period
            self.frame = 1
        else:
            self.timer = None
            self.frame = 0
            if self.notify:
                self.notify(0x3C, self)

    def message(self, code: int, value: float = 0.0) -> int:
        """FUN_010166f6: 0x3f3 / 0x400 reset."""
        if code in (0x3F3, 0x400):
            if self.timer is not None:
                self.frame = None
            self.armed = False
            self.timer = None
            self.threshold = 1.0e9
        return 0
