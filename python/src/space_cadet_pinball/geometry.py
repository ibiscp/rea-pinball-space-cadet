"""Static and dynamic collision shapes used by the table."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from . import constants as c
from .vec2 import Vec2

if TYPE_CHECKING:
    from .ball import Ball


class ContactBehavior(Protocol):
    """An object's own collision handler (its vtable slot 5), for objects
    that do more than a plain bounce: capture the ball (sinks), change their
    kick at runtime (the kickback) or decide a hit (targets)."""

    def capture(self, ball: Ball, tilted: bool) -> bool: ...

    def kick_for_contact(self, tilted: bool) -> tuple[float, float]: ...

    def after_bounce(self, impact: float, threshold: float, tilted: bool) -> None: ...


@dataclass(slots=True)
class Segment:
    """An immovable line-segment wall.

    Bounces through the original's FUN_01017883 (see World.bounce): separate
    normal (`restitution`) and tangential (`tangent_retention`) coefficients,
    plus an extra `kick` along the normal when the closing speed reaches
    `kick_threshold` (dead by default, as for generic collision objects).

    `one_sided` walls are the original's plain line walls (FUN_0101c77e):
    FUN_01008beb gives the line from `a` to `b` the normal (dy, -dx) of its
    unit direction, and the swept test FUN_01008c8f only reports a hit for a
    ball moving against that normal, so a ball crossing from the back passes
    straight through (one-way walls, gates, the kickback plate). Polygon edges
    are left two-sided: they bound solid shapes the ball never gets inside.
    """

    a: Vec2
    b: Vec2
    restitution: float = c.WALL_RESTITUTION
    tangent_retention: float = c.WALL_TANGENT_RETENTION
    kick_threshold: float = c.NO_KICK_THRESHOLD
    kick: float = 0.0
    one_sided: bool = False
    # Collision layer bits (type-10 tag 602 in FUN_0100950a, default 1); a
    # ball only hits objects sharing a bit with its own mask (FUN_0100b316).
    mask: int = 1
    # Cleared while a gate is open (the object's "active" byte, +5).
    active: bool = True
    behavior: ContactBehavior | None = field(default=None, repr=False)
    # Shape walls (FUN_010179a9) sit one ball radius out along their normal
    # (FUN_0101c813); the table's own outer walls (FUN_0101c6fd) don't.
    radius_offset: bool = True
    _edge: tuple | None = field(default=None, repr=False, compare=False)

    def edge(self, ball_radius: float) -> tuple:
        """The swept-test line FUN_01008beb builds: (normal, c, direction,
        lo, hi, use_y) for the line a->b moved `ball_radius` along its
        normal when `radius_offset`; c = -(normal . a)."""
        if self._edge is None or self._edge[0] != ball_radius:
            self._edge = (ball_radius, _line(self.a, self.b, ball_radius if self.radius_offset else 0.0))
        return self._edge[1]

    def closest_point(self, p: Vec2) -> Vec2:
        ab = self.b - self.a
        length_sq = ab.length_sq()
        if length_sq < 1e-9:
            return self.a
        t = max(0.0, min(1.0, (p - self.a).dot(ab) / length_sq))
        return self.a + ab * t

    def line_normal(self) -> Vec2:
        d = (self.b - self.a).normalized()
        return Vec2(d.y, -d.x)


def _line(a: Vec2, b: Vec2, offset: float) -> tuple:
    """FUN_01008beb (after FUN_0101c813's shift of both ends by `offset`
    along the normal): unit direction d, normal (d.y, -d.x), c = -(n . a);
    the extent is checked on x, or on y when |d.x| < 1e-9 (then d.x = 0)."""
    d = b - a
    length = d.length()
    d = d * (1.0 / length) if length > 0 else Vec2(0.0, 0.0)
    normal = Vec2(d.y, -d.x)
    a = a + normal * offset
    b = b + normal * offset
    if abs(d.x) >= 1e-9:
        use_y, lo, hi = False, min(a.x, b.x), max(a.x, b.x)
    else:
        use_y, lo, hi = True, min(a.y, b.y), max(a.y, b.y)
    return normal, -normal.dot(a), lo, hi, use_y


def line_hit(origin: Vec2, direction: Vec2, length: float, tolerance: float, line: tuple) -> float | None:
    """FUN_01008c8f: distance along the ray to the line, or None. Only a ray
    moving against the normal hits (one-sided), from `-tolerance` up to
    `length`, with the contact point inside the line's extent."""
    normal, c, lo, hi, use_y = line
    denom = direction.dot(normal)
    if denom >= 0.0:
        return None
    t = -(origin.dot(normal) + c) / denom
    if t < -tolerance or t > length:
        return None
    contact = origin.y + direction.y * t if use_y else origin.x + direction.x * t
    if contact < lo or contact > hi:
        return None
    return t


def circle_hit(origin: Vec2, direction: Vec2, length: float, center: Vec2, radius_sq: float) -> float | None:
    """FUN_01008b34: distance along the ray to the circle, or None. Only a
    circle ahead of the ray counts; a ray starting inside it hits at the
    (negative) distance back to its rim."""
    to_center = center - origin
    along = to_center.dot(direction)
    if along < 0.0:
        return None
    dist_sq = to_center.length_sq()
    if dist_sq < radius_sq:
        return along - math.sqrt(along * along + (radius_sq - dist_sq))
    disc = along * along + (radius_sq - dist_sq)
    if disc < 0.0:
        return None
    t = along - math.sqrt(disc)
    if t < 0.0 or t > length:
        return None
    return t


@dataclass(slots=True)
class TripLine:
    """A bare line wall that never bounces: its owner's collision handler
    just moves the ball to the contact point and changes its state (the
    ramps' triangle edges and score lines, FUN_01016c24). The swept test
    FUN_01008c8f fires when the ball's *centre* crosses it from the front
    (moving against the normal (dy, -dx) of a->b) within its extent; these
    lines aren't offset by the ball radius."""

    a: Vec2
    b: Vec2
    mask: int
    on_cross: Callable[[Ball], None] = field(repr=False)
    # The owner's "active" byte the line was built with (e.g. a rollover's
    # +5 / +0x4e); None = always active.
    active: Callable[[], bool] | None = field(default=None, repr=False)

    def edge(self) -> tuple:
        """The swept-test line (FUN_01008beb), not offset."""
        return _line(self.a, self.b, 0.0)

    def offset(self, distance: float) -> TripLine:
        """FUN_0101c813: the same line moved `distance` along its normal."""
        d = (self.b - self.a).normalized()
        shift = Vec2(d.y, -d.x) * distance
        return TripLine(self.a + shift, self.b + shift, self.mask, self.on_cross, self.active)

    def crossing(self, p0: Vec2, p1: Vec2) -> float | None:
        """Fraction along p0->p1 where the centre crosses the line from the
        front, or None."""
        d = (self.b - self.a).normalized()
        normal = Vec2(d.y, -d.x)
        move = p1 - p0
        denom = normal.dot(move)
        if denom >= 0:
            return None
        t = -normal.dot(p0 - self.a) / denom
        if not 0.0 < t <= 1.0:
            return None
        hit = p0 + move * t
        along = (hit - self.a).dot(d)
        if along < 0.0 or along > (self.b - self.a).length():
            return None
        return t


@dataclass(slots=True)
class Circle:
    """An immovable circular obstacle: post, bumper body, etc.

    Bumpers keep the generic 0.6/0.95 bounce (they have no tag-300 preset)
    and get their extra kick from their tag-400 preset's threshold/kick
    (see table_data.py).
    """

    center: Vec2
    radius: float
    restitution: float = c.WALL_RESTITUTION
    tangent_retention: float = c.WALL_TANGENT_RETENTION
    kick_threshold: float = c.NO_KICK_THRESHOLD
    kick: float = 0.0
    mask: int = 1
    behavior: ContactBehavior | None = field(default=None, repr=False)
    # A polygon's corner circle (FUN_010179a9) is part of the same object as
    # its line walls: it follows that wall's "active" byte.
    wall: Segment | None = field(default=None, repr=False)
    on_hit: object | None = field(default=None, repr=False)  # callable(Circle) -> None, fired on a kick
    # A brief lockout after a kick fires -- a port safeguard against a ball
    # wedged between closely-spaced bumpers re-firing them every substep.
    cooldown: float = 0.0
    _cooldown_remaining: float = field(default=0.0, repr=False)
    name: str = ""  # PINBALL.DAT entry name, for scoring
