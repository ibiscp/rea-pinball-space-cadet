"""Minimal 2D vector math used throughout the physics engine."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class Vec2:
    x: float = 0.0
    y: float = 0.0

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vec2:
        return Vec2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def __neg__(self) -> Vec2:
        return Vec2(-self.x, -self.y)

    def dot(self, other: Vec2) -> float:
        return self.x * other.x + self.y * other.y

    def cross(self, other: Vec2) -> float:
        return self.x * other.y - self.y * other.x

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def length_sq(self) -> float:
        return self.x * self.x + self.y * self.y

    def normalized(self) -> Vec2:
        length = self.length()
        if length < 1e-9:
            return Vec2(0.0, 0.0)
        return Vec2(self.x / length, self.y / length)

    def normal(self) -> Vec2:
        """Returns the left-hand perpendicular (not normalized to unit length)."""
        return Vec2(-self.y, self.x)

    def rotated(self, radians: float) -> Vec2:
        cos_a, sin_a = math.cos(radians), math.sin(radians)
        return Vec2(self.x * cos_a - self.y * sin_a, self.x * sin_a + self.y * cos_a)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

    def as_int_tuple(self) -> tuple[int, int]:
        return (round(self.x), round(self.y))

    def copy(self) -> Vec2:
        return Vec2(self.x, self.y)
