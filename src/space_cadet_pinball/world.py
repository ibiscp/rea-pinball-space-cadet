"""The physics world: integrates balls and resolves collisions against the
table's static geometry (walls, bumpers) and dynamic flippers each step.

Everything is in the original's world units (see constants.py/projection.py).
"""

from __future__ import annotations

import math
import random
import struct
from collections.abc import Callable
from typing import TYPE_CHECKING

from . import constants as c
from .ball import Ball
from .flipper import Flipper
from .geometry import Circle, Segment, TripLine, circle_hit, line_hit
from .grid import Grid
from .vec2 import Vec2

if TYPE_CHECKING:
    from .entities import Kickout, Ramp, RampHole

MAX_TOI_STEPS = 10  # FUN_01014a68: at most 10 time-of-impact steps per ball per tick
TOI_TOLERANCE = 0.002  # FUN_01014956's ray: a line still counts up to this far behind


def _f32(x: float) -> float:
    return struct.unpack("f", struct.pack("f", x))[0]


def gravity_from_triple(magnitude: float, a1: float, a2: float) -> Vec2:
    """FUN_0101a5ab: the "table" entry's tag-305 triple -> gravity vector."""
    return Vec2(math.cos(a2) * math.sin(a1) * magnitude, math.sin(a2) * math.sin(a1) * magnitude)


def bounce(
    velocity: Vec2,
    normal: Vec2,
    restitution: float,
    tangent_retention: float,
    kick_threshold: float = c.NO_KICK_THRESHOLD,
    kick: float = 0.0,
    separating: bool = False,
) -> tuple[Vec2, float]:
    """The original's FUN_01017883 for a ball touching a surface with unit
    `normal`; returns (new velocity, impact speed). It works on direction
    and speed separately: e_t/e_n only re-mix the direction, the speed loses
    (1 - e_n) of the closing speed, and a closing speed of at least
    `kick_threshold` adds `kick` along the normal.

    For a ball that isn't closing, the original keeps its direction, still
    damps its speed by the (now opening) normal speed and still kicks if the
    threshold allows; the port only asks for that (`separating=True`) where a
    caller needs it -- the moving flipper's kick, which must reach a ball at
    rest -- since its discrete overlap test would otherwise damp every
    resting contact."""
    speed = velocity.length()
    d = velocity * (1.0 / speed) if speed > 1e-12 else -normal
    closing = -normal.dot(d)
    if closing > 0:
        new_dir = ((d + normal * closing) * tangent_retention + normal * (closing * restitution)).normalized()
    elif separating:
        closing, new_dir = -closing, d
    else:
        return velocity, 0.0
    impact = closing * speed
    new_velocity = new_dir * (speed - (1.0 - restitution) * impact)
    if impact >= kick_threshold:
        new_velocity = normal * kick + new_velocity
    return new_velocity, impact


class World:
    def __init__(self) -> None:
        self.segments: list[Segment] = []
        self.circles: list[Circle] = []
        self.flippers: list[Flipper] = []
        self.balls: list[Ball] = []
        self.fields: list[Kickout | RampHole] = []
        # Ramps' fields (their triangle gravity) and their trip lines.
        self.ramps: list[Ramp] = []
        self.trip_lines: list[TripLine] = []
        self._trip_edges: dict[int, tuple] = {}
        self.gravity = gravity_from_triple(*c.GRAVITY_TRIPLE)
        self.friction = c.FRICTION
        self.max_ball_speed = c.MAX_BALL_SPEED
        self.jitter = True
        # While tilted the table's own walls lose their boost (FUN_01017e85's
        # tilt-lock branch passes threshold 1e9, boost 0).
        self.tilted = False
        self.on_ball_drained: Callable[[Ball], None] | None = None
        # The "drain" entry's tag-600 line; touching it loses the ball.
        self.drain_y: float = math.inf
        # Last-resort backstop (min_x, min_y, max_x) in case the ball tunnels
        # through a wall; the bottom stays open for the drain.
        self.frame_bounds: tuple[float, float, float] | None = None
        # The game clock (_DAT_01025630), float seconds; flipper messages
        # are stamped with it.
        self.time = 0.0
        # The spatial grid; set by the table builder (None: every flipper
        # test runs, as in the placeholder table).
        self.grid: Grid | None = None

    def step(self, dt: float) -> None:
        """FUN_01014bf9 / FUN_01014a68 for one tick of `dt` seconds.

        Each free ball's velocity gets the summed fields once (gravity,
        friction, jitter, kickout pulls, ramp gravity: FUN_0100b316), then
        it moves by time of impact (FUN_01014956, at most 10 steps a tick):
        the ray from its centre along its velocity, as long as the distance
        it would travel, starting at the current game time, is tested
        against every line, circle, trip line, capture circle and flipper
        (FUN_0100b486); with no hit the ball moves the whole way, otherwise
        the edge's owner handles the collision (placing the ball at the
        contact) and the step uses up distance / speed of the time.
        """
        start = self.time
        for circle in self.circles:
            if circle._cooldown_remaining > 0:
                circle._cooldown_remaining -= dt
        for ball in self.balls:
            if ball.alive and not ball.held:
                self._integrate(ball, dt)
                self._move(ball, start, dt)
        self.time = _f32(start + dt)

    def _integrate(self, ball: Ball, dt: float) -> None:
        """FUN_010173e7 + FUN_0100b316 + FUN_01014a68: a = g - friction*v,
        plus an x-only jitter of friction * speed * U(-0.5, 0.5), plus every
        field over the ball (the kickouts' pull, the ramps' own gravity)."""
        speed = ball.speed()
        jitter_x = self.friction * speed * (random.random() - 0.5) if self.jitter else 0.0
        accel = Vec2(self.gravity.x + jitter_x, self.gravity.y) - ball.velocity * self.friction
        for source in (*self.fields, *self.ramps):
            pull = source.accel(ball)
            if pull is not None:
                accel = accel + pull
        ball.velocity = ball.velocity + accel * dt

    def _move(self, ball: Ball, time: float, dt: float) -> None:
        """FUN_01014a68's loop of FUN_01014956: up to 10 steps, each from the
        current time over the time left; the rest of the tick is dropped."""
        remaining = dt
        steps = MAX_TOI_STEPS
        excluded: list[object] = []
        while remaining > 1e-6 and steps:
            steps -= 1
            used = self._toi_step(ball, time, remaining, excluded)
            remaining -= used
            time += used
            if not ball.alive or ball.held:
                return
            self._after_move(ball)
            if not ball.alive or ball.held:
                return

    def _toi_step(self, ball: Ball, time: float, remaining: float, excluded: list[object]) -> float:
        """FUN_01014956: returns the time used."""
        speed = ball.speed()
        if speed > self.max_ball_speed:
            ball.velocity = ball.velocity * (self.max_ball_speed / speed)
            speed = self.max_ball_speed
        direction = ball.velocity * (1.0 / speed) if speed > 0.0 else Vec2(0.0, 0.0)
        skip = list(excluded)
        excluded.clear()
        hit = self._nearest_hit(ball, direction, remaining * speed, skip, time, remaining)
        if hit is None:
            ball.position = ball.position + ball.velocity * remaining
            return remaining
        t, kind, edge = hit
        if kind != "flipper":
            ball.position = ball.position + direction * t
        self._hit(ball, kind, edge, excluded)
        if speed > 1e-9:
            return abs(t / speed)
        return remaining

    def _nearest_hit(
        self,
        ball: Ball,
        direction: Vec2,
        length: float,
        excluded: list[object],
        time: float = 0.0,
        window: float = 0.0,
    ) -> tuple[float, str, object] | None:
        """FUN_0100b486: the nearest edge along the ray (active, sharing a
        layer bit with the ball, not in the ball's skip list)."""
        origin = ball.position
        radius = ball.radius
        best: tuple[float, str, object] | None = None
        for seg in self.segments:
            if not seg.active or not seg.mask & ball.mask or seg in excluded:
                continue
            t = line_hit(origin, direction, length, TOI_TOLERANCE, seg.edge(radius))
            if t is not None and (best is None or t < best[0]):
                best = (t, "segment", seg)
        for circle in self.circles:
            if not circle.mask & ball.mask or circle in excluded:
                continue
            if circle.wall is not None and not circle.wall.active:
                continue
            edge_radius = circle.radius + radius
            t = circle_hit(origin, direction, length, circle.center, edge_radius * edge_radius)
            if t is not None and (best is None or t < best[0]):
                best = (t, "circle", circle)
        for line in self.trip_lines:
            if not line.mask & ball.mask or line in excluded:
                continue
            if line.active is not None and not line.active():
                continue
            edge = self._trip_edges.get(id(line))
            if edge is None:
                edge = self._trip_edges[id(line)] = line.edge()
            t = line_hit(origin, direction, length, TOI_TOLERANCE, edge)
            if t is not None and (best is None or t < best[0]):
                best = (t, "trip", line)
        for hole in self.fields:
            capture = hole.capture_radius
            if not hole.can_capture(ball):
                continue
            t = circle_hit(origin, direction, length, hole.center, capture * capture)
            if t is not None and (best is None or t < best[0]):
                best = (t, "capture", hole)
        if self.flippers:
            # The flipper's test keeps state, so it only runs when the ray's
            # cell walk reaches one of its cells, at most once per query.
            walked = set(self.grid.walk(origin, direction, length)) if self.grid is not None else None
            for flipper in self.flippers:
                if not flipper.mask & ball.mask or flipper in excluded:
                    continue
                if walked is not None and walked.isdisjoint(flipper.cells):
                    continue
                t = flipper.sweep(origin, direction, length, TOI_TOLERANCE, time, window)
                if t is not None and (best is None or t < best[0]):
                    best = (t, "flipper", flipper)
        return best

    def _hit(self, ball: Ball, kind: str, edge, excluded: list[object]) -> None:
        """The edge's collision (vtable slot 0) -> its owner's handler
        (slot 5), with the ball already at the contact point."""
        if kind == "trip":
            excluded.append(edge)  # FUN_0101590f: skipped by the next query
            edge.on_cross(ball)
        elif kind == "capture":
            edge.try_capture(ball, self.tilted, force=True)
        elif kind == "flipper":
            # FUN_0101be06 -> FUN_01017883 at the edge's own contact point.
            restitution, tangent_retention, threshold, kick = edge.collide()
            ball.position = edge.contact.copy()
            ball.velocity, _ = bounce(
                ball.velocity, edge.normal, restitution, tangent_retention, threshold, kick, separating=True
            )
        elif kind == "segment":
            self._bounce_off(ball, edge, edge.edge(ball.radius)[0], edge.behavior)
        else:
            normal = (ball.position - edge.center).normalized()
            if edge.wall is not None:
                self._bounce_off(ball, edge.wall, normal, edge.wall.behavior)
            elif edge.on_hit is not None:
                self._bounce_circle(ball, edge, normal)
            else:
                self._bounce_off(ball, edge, normal, edge.behavior)

    def _bounce_off(self, ball: Ball, wall: Segment | Circle, normal: Vec2, behavior) -> None:
        """FUN_01017e85 (and the objects' own slot-5 handlers through
        `behavior`): FUN_01017883 with the wall's e_n / e_t and its kick,
        no kick while tilted."""
        if behavior is not None and behavior.capture(ball, self.tilted):
            return
        if behavior is not None:
            threshold, kick = behavior.kick_for_contact(self.tilted)
        elif self.tilted:
            threshold, kick = c.NO_KICK_THRESHOLD, 0.0
        else:
            threshold, kick = wall.kick_threshold, wall.kick
        ball.velocity, impact = bounce(
            ball.velocity, normal, wall.restitution, wall.tangent_retention, threshold, kick, separating=True
        )
        if behavior is not None:
            behavior.after_bounce(impact, threshold, self.tilted)

    def _bounce_circle(self, ball: Ball, circle: Circle, normal: Vec2) -> None:
        armed = circle._cooldown_remaining <= 0
        threshold = circle.kick_threshold if armed else c.NO_KICK_THRESHOLD
        if self.tilted:
            threshold = c.NO_KICK_THRESHOLD
        ball.velocity, impact = bounce(
            ball.velocity, normal, circle.restitution, circle.tangent_retention, threshold, circle.kick, separating=True
        )
        # FUN_0101811d -> FUN_01017f29: a hit only above the threshold.
        if armed and not self.tilted and impact > circle.kick_threshold:
            circle._cooldown_remaining = circle.cooldown
            if circle.on_hit:
                circle.on_hit(circle)

    def _after_move(self, ball: Ball) -> None:
        self._collide_frame_bounds(ball)
        if ball.position.y + ball.radius >= self.drain_y:
            ball.alive = False
            if self.on_ball_drained:
                self.on_ball_drained(ball)

    def _collide_frame_bounds(self, ball: Ball) -> None:
        if self.frame_bounds is None:
            return
        min_x, min_y, max_x = self.frame_bounds
        if ball.position.x - ball.radius < min_x:
            ball.position.x = min_x + ball.radius
            ball.velocity.x = abs(ball.velocity.x) * c.WALL_RESTITUTION
        elif ball.position.x + ball.radius > max_x:
            ball.position.x = max_x - ball.radius
            ball.velocity.x = -abs(ball.velocity.x) * c.WALL_RESTITUTION
        if ball.position.y - ball.radius < min_y:
            ball.position.y = min_y + ball.radius
            ball.velocity.y = abs(ball.velocity.y) * c.WALL_RESTITUTION
