"""The flipper's collision edge, ported from the original's flipper edge
object:

- FUN_0101c2ba (constructor): pivot circle (tag 800), tip circle at rest
  (801), tip fully extended (802), swing durations 804 (up) / 805 (down),
  kick factor 803, the object's e_n / e_t. Both circles are grown by the ball
  radius; the two side lines run tangent to them, one ball radius out.
- FUN_0101bf98 (messages 1 = up, 2 = down, 0x400 = reset to rest),
  FUN_0101b1f7 (angle at a time), FUN_0101b327 + FUN_0101b281 (the shape
  posed at that angle).
- FUN_0101b825 (the swept test the time-of-impact loop calls), with
  FUN_0101b5a8 (is a point inside the shape) and FUN_0101b43a (nearest of
  the two lines and two circles along a ray).
- FUN_0101be06 (the collision handler: bounce, and the moving face's kick).

Angles are measured from the rest pose; the swing A (+0x45) is signed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geometry import _line, circle_hit, line_hit
from .vec2 import Vec2

NO_KICK = 1e9


def _rotate(p: Vec2, pivot: Vec2, s: float, c: float) -> Vec2:
    """FUN_0101cbb1."""
    dx, dy = p.x - pivot.x, p.y - pivot.y
    return Vec2(dx * c - dy * s + pivot.x, dy * c + dx * s + pivot.y)


@dataclass
class Flipper:
    pivot: Vec2  # +0x21 / +0x25 (tag 800 x, y)
    radius: float  # tag 800 radius
    rest_tip: Vec2  # +0x99 / +0x9d (tag 801 x, y)
    tip_radius: float  # +0xa1 (tag 801 radius)
    extended_tip: Vec2  # +0xa5 / +0xa9 (tag 802)
    up_time: float  # +0xd5 (tag 804)
    down_time: float  # +0xd9 (tag 805)
    ball_radius: float
    kick_factor: float = 0.9  # +0x95 (tag 803)
    restitution: float = 0.75  # +0x19
    tangent_retention: float = 0.5  # +0x1d
    mask: int = 1
    is_left: bool = True

    pressed: bool = False
    # Grid cells the edge is registered in (FUN_0101b0d4 -> FUN_0100be21).
    cells: frozenset[tuple[int, int]] = frozenset()

    state: int = 0  # +0x15: 0 at rest, else the last message code
    start_angle: float = 0.0  # +0x49
    target_angle: float = 0.0  # +0x4d
    start_time: float = 0.0  # +0xc9
    end_time: float = 0.0  # +0xcd
    duration: float = 0.0  # +0xd1
    skip_next: bool = False  # +0xc5, set by the collision handler
    leading: bool = False  # +0x51
    trailing: bool = False  # +0x55
    face_normal: Vec2 = field(default_factory=Vec2)  # +0x59
    contact: Vec2 = field(default_factory=Vec2)  # +0xdd
    normal: Vec2 = field(default_factory=Vec2)  # +0xb9

    def __post_init__(self) -> None:
        r1 = self.radius + self.ball_radius  # +0x2d
        r2 = self.tip_radius + self.ball_radius  # +0x31
        self._r1, self._r2 = r1, r2
        self._r1_sq, self._r2_sq = r1 * r1, r2 * r2  # +0x35 / +0x39
        self._inner1_sq = (r1 * 1.01) ** 2  # +0x3d
        self._inner2_sq = (r2 * 1.01) ** 2  # +0x41
        u = (self.rest_tip - self.pivot).normalized()
        e = (self.extended_tip - self.pivot).normalized()
        swing = math.acos(max(-1.0, min(1.0, u.dot(e))))
        self.swing = -swing if u.x * e.y - e.x * u.y < 0.0 else swing  # +0x45
        n = Vec2(-u.y, u.x)
        p65 = self.rest_tip + n * r2
        p71 = self.pivot + n * r1
        p7d = self.pivot - n * r1
        p89 = self.rest_tip - n * r2
        if self.swing < 0.0:
            p65, p7d = p7d, p65
            p71, p89 = p89, p71
        self._rest_points = (p65, p71, p7d, p89)
        reach = (self.rest_tip - self.pivot).length() + r2
        self._reach_sq = reach * reach  # +0xb1
        sweep = (self.rest_tip - self.extended_tip).length() / r2
        self.step = min(self.up_time, self.down_time) / (sweep + sweep)  # +0xb5
        self.length = (self.rest_tip - self.pivot).length()
        self._pose(0.0)

    # -- registration --------------------------------------------------------
    def bounding_box(self) -> tuple[float, float, float, float]:
        """FUN_0101b0d4: (min_x, min_y, max_x, max_y) over the pivot circle
        and the rest and extended tip circles, each grown by the ball."""
        r1, r2 = self._r1, self._r2
        xs = (self.pivot.x - r1, self.pivot.x + r1, self.rest_tip.x - r2, self.rest_tip.x + r2,
              self.extended_tip.x - r2, self.extended_tip.x + r2)
        ys = (self.pivot.y - r1, self.pivot.y + r1, self.rest_tip.y - r2, self.rest_tip.y + r2,
              self.extended_tip.y - r2, self.extended_tip.y + r2)
        return min(xs), min(ys), max(xs), max(ys)

    # -- motion ---------------------------------------------------------------
    def message(self, code: int, time: float) -> None:
        """FUN_0101bf98."""
        if code == 1:
            self.start_angle = self.angle_at(time)
            self.target_angle = self.swing
            self.duration = self.up_time
        elif code == 2:
            self.start_angle = self.angle_at(time)
            self.target_angle = 0.0
            self.duration = self.down_time
        elif code == 0x400:
            self.state = 0
            self.target_angle = 0.0
            return
        if self.state == 0:
            self.start_time = time
        self.state = code
        self.end_time = self.duration + self.start_time

    def angle_at(self, time: float) -> float:
        """FUN_0101b1f7."""
        if self.state == 0:
            return self.target_angle
        span = abs((self.target_angle - self.start_angle) / self.swing * self.duration)
        frac = (time - self.start_time) / span if span >= 1e-7 else 1.0
        frac = min(1.0, max(0.0, frac))
        if self.state == 2:
            frac = 1.0 - frac
        return frac * self.swing

    def _pose(self, angle: float) -> None:
        """FUN_0101b327 + FUN_0101b281: the shape turned `angle` from rest."""
        s, c = math.sin(angle), math.cos(angle)
        p65, p71, p7d, p89 = (_rotate(p, self.pivot, s, c) for p in self._rest_points)
        self._p65, self._p71, self._p7d, self._p89 = p65, p71, p7d, p89
        self._tip = _rotate(self.rest_tip, self.pivot, s, c)
        self._line1 = _line(p65, p71, 0.0)
        self._line2 = _line(p7d, p89, 0.0)

    def tip(self) -> Vec2:
        """The tip circle's centre as last posed (debug drawing)."""
        return self._tip

    # -- tests -----------------------------------------------------------------
    def _inside(self, x: float, y: float) -> int:
        """FUN_0101b5a8: 0 outside, else 4 or 5 for the side of the arm."""
        a, b, c, d = self._p65, self._p71, self._p7d, self._p89
        outside_quad = (
            (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x) < 0.0
            or (y - b.y) * (c.x - b.x) - (x - b.x) * (c.y - b.y) < 0.0
            or (y - c.y) * (d.x - c.x) - (x - c.x) * (d.y - c.y) < 0.0
            or (y - d.y) * (a.x - d.x) - (x - d.x) * (a.y - d.y) < 0.0
        )
        px, py = self.pivot.x, self.pivot.y
        tip = self._tip
        if (
            outside_quad
            and (px - x) ** 2 + (py - y) ** 2 > self._r1_sq
            and self._r2_sq <= (tip.y - y) ** 2 + (tip.x - x) ** 2
        ):
            return 0
        st = self.state
        if self.swing < 0.0:
            ref = c if st == 1 else b if st == 2 else tip
            v = (y - ref.y) * (px - ref.x) - (x - ref.x) * (py - ref.y)
            return 4 if v >= 0.0 else 5
        if st == 2:
            v = (px - a.x) * (y - a.y) - (py - a.y) * (x - a.x)
        else:
            ref = d if st == 1 else tip
            v = (y - ref.y) * (px - ref.x) - (x - ref.x) * (py - ref.y)
        return 4 if v < 0.0 else 5

    def _nearest(self, origin: Vec2, direction: Vec2, length: float, tolerance: float):
        """FUN_0101b43a: (t, contact, normal) of the nearest of line 1, the
        pivot circle, the tip circle and line 2, or None."""
        best, kind = None, -1
        for k, t in (
            (0, line_hit(origin, direction, length, tolerance, self._line1)),
            (2, circle_hit(origin, direction, length, self.pivot, self._r1_sq)),
            (3, circle_hit(origin, direction, length, self._tip, self._r2_sq)),
            (1, line_hit(origin, direction, length, tolerance, self._line2)),
        ):
            if t is not None and (best is None or t < best):
                best, kind = t, k
        if best is None:
            return None
        contact = origin + direction * best
        if kind == 0:
            normal = self._line1[0]
        elif kind == 1:
            normal = self._line2[0]
        else:
            normal = (contact - (self.pivot if kind == 2 else self._tip)).normalized()
        return best, contact, normal

    def sweep(
        self, origin: Vec2, direction: Vec2, length: float, tolerance: float, time: float, window: float
    ) -> float | None:
        """FUN_0101b825: the swept test for a ray starting at `time` and
        lasting `window` seconds. Returns the distance to the contact (0 when
        the flipper is pushing the ball out of its shape), or None; the
        contact point and normal are left in `contact` / `normal` for
        `collide`.

        While the flipper moves, it is posed every `step` seconds through the
        window; the ray's own sub-length is step * length and the inside test
        point advances by step * direction, exactly as the original does
        (both independent of the ball's speed)."""
        if self.end_time < time:
            self.state = 0
        if self.skip_next:
            self.skip_next = False
            return None
        if self.state == 0:
            self.leading = self.trailing = False
            self._pose(self.angle_at(time))
            inside = self._inside(origin.x, origin.y)
            if inside == 0:
                hit = self._nearest(origin, direction, length, tolerance)
                if hit is None:
                    return None
                t, contact, normal = hit
                self.contact = contact - direction * 1e-5 if t == 0.0 else contact
                self.normal = normal
                return t
            if (self.pivot - origin).length_sq() < self._inner1_sq:
                push = (self.pivot - origin).normalized()
            elif (self._tip - origin).length_sq() < self._inner2_sq:
                push = (self._tip - origin).normalized()
            else:
                push = -(self._line1[0] if inside == 4 else self._line2[0])
            hit = self._nearest(origin - push * 5.0, push, length + 10.0, tolerance)
            if hit is None:
                push = (self.pivot - origin).normalized()
                hit = self._nearest(origin - push * 5.0, push, length + 10.0, tolerance)
                if hit is None:
                    return None
            _, contact, self.normal = hit
            self.contact = contact - push * 1e-5
            return 0.0

        position = origin
        sub_length = self.step * length
        advance = direction * self.step
        t = time
        while t < window + time:
            self._pose(self.angle_at(t))
            inside = self._inside(position.x, position.y)
            if inside != 0:
                if self.state == 1 and inside != 5:
                    face = self._line1[0]
                elif self.state != 2 or inside == 4:
                    push = (self.pivot - position).normalized()
                    self.leading, self.trailing = False, True
                    hit = self._nearest(position - push * 5.0, push, length + 10.0, tolerance)
                    if hit is not None:
                        _, contact, self.normal = hit
                        self.contact = contact - push * 1e-5
                    else:
                        self.contact = position
                        self.normal = -push
                    return 0.0
                else:
                    face = self._line2[0]
                push = -face
                self.face_normal = face
                self.leading, self.trailing = True, False
                hit = self._nearest(origin - push * 5.0, push, length + 10.0, 0.002)
                if hit is not None:
                    self.normal = hit[2]
                if hit is None:
                    return None
                self.contact = hit[1] - push * 1e-5
                return 0.0
            hit = self._nearest(origin, direction, sub_length, tolerance)
            if hit is not None:
                distance, contact, normal = hit
                self.contact = contact - direction * 1e-5
                tip, pivot = self._tip, self.pivot
                cross = (self.contact.y - tip.y) * (pivot.x - tip.x) - (self.contact.x - tip.x) * (pivot.y - tip.y)
                k = (cross < 0.0) == (self.swing > 0.0)
                if self.state == 2:
                    self.face_normal = self._line2[0]
                    self.leading = not k
                else:
                    self.leading = k
                    self.face_normal = self._line1[0]
                self.normal = normal
                return distance
            t += self.step
            position = position + advance
        return None

    def collide(self) -> tuple[float, float, float, float]:
        """FUN_0101be06: (e_n, e_t, threshold, kick) for FUN_01017883 at
        `contact` / `normal`; the next swept test of this edge is skipped."""
        self.skip_next = True
        e_n, e_t = self.restitution, self.tangent_retention
        if self.state == 0:
            return e_n, e_t, NO_KICK, 0.0
        d_sq = (self.contact - self.pivot).length_sq()
        if not self.leading:
            if self.trailing and self._r1_sq * 1.01 < d_sq:
                e_n = (1.0 - math.sqrt(d_sq / self._reach_sq)) * e_n
            return e_n, e_t, NO_KICK, 0.0
        if d_sq <= self._r1_sq * 1.01:
            kick = 0.0
        else:
            k = self.face_normal.dot(self.normal)
            kick = k * (abs(self.swing) / self.duration) * math.sqrt(d_sq / self._reach_sq) if k >= 0.0 else 0.0
        kick *= self.kick_factor
        return e_n, e_t, (-1.0 if kick > 0.0 else NO_KICK), kick
