"""The original game's world -> screen camera, decoded from Pinball.exe.

The original simulates everything in its own 2D "world units" on the table
plane and only converts to pixels when drawing, through a single perspective
projection (see PHYSICS_SPEC_11.md, kept outside this repo):

- `FUN_01015424` reads the `camera_info` entry's 15 floats: a 3x4 camera
  matrix, then `d`; it calls `proj::init` (`FUN_01008e4b`) with the matrix,
  `d` and a provisional centre of `table_size * 0.5`.
- The table constructor `FUN_0101a5ab` then re-centres the projection
  (`FUN_01008eba`) on the `table` entry's tag 700 point, (183, 238).
- `FUN_01008f03` (xform_to_2d): `v = M * (x, y, z)`; `k = d / v.z` (or
  999999.875 when `v.z == 0`); `screen = (v.x * k + cx, v.y * k + cy)`.
- The ball's repaint (`FUN_01015c08`) projects its world position directly;
  every other sprite is drawn at its bitmap origin *minus* the `table`
  bitmap's own origin (`table+0xea`/`+0xee`, set in `FUN_0101a5ab`). This
  port draws sprites at their raw origins, so projected points get that
  origin added back.

Cross-checked against independent data: the flippers' tagged pivot/tip
circles land on their sprites' corners to within a pixel, bumper centres
land on their sprites' centres, and the `table` entry's world-space outer
rectangle (x in [-8, 8], y in [-14, 15]) projects onto the tapered table art.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import partout
from .vec2 import Vec2


@dataclass(frozen=True, slots=True)
class Camera:
    matrix: tuple[tuple[float, float, float, float], ...]  # 3 rows of 4
    d: float
    center_x: float
    center_y: float
    offset_x: float = 0.0
    offset_y: float = 0.0
    identity: bool = False

    def _view(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        m = self.matrix
        return (
            m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
        )

    def to_screen(self, p: Vec2, z: float = 0.0) -> Vec2:
        if self.identity:
            return Vec2(p.x, p.y)
        vx, vy, vz = self._view(p.x, p.y, z)
        k = self.d / vz if vz != 0 else 999999.875
        return Vec2(vx * k + self.center_x + self.offset_x, vy * k + self.center_y + self.offset_y)

    def to_world(self, s: Vec2, z: float = 0.0) -> Vec2:
        """Inverse of `to_screen` for points on the plane at height `z`."""
        if self.identity:
            return Vec2(s.x, s.y)
        m, d = self.matrix, self.d
        u = s.x - self.center_x - self.offset_x
        v = s.y - self.center_y - self.offset_y
        # u * view_z = d * view_x and v * view_z = d * view_y, both linear in (x, y).
        a11, a12 = u * m[2][0] - d * m[0][0], u * m[2][1] - d * m[0][1]
        b1 = d * (m[0][2] * z + m[0][3]) - u * (m[2][2] * z + m[2][3])
        a21, a22 = v * m[2][0] - d * m[1][0], v * m[2][1] - d * m[1][1]
        b2 = d * (m[1][2] * z + m[1][3]) - v * (m[2][2] * z + m[2][3])
        det = a11 * a22 - a12 * a21
        return Vec2((b1 * a22 - a12 * b2) / det, (a11 * b2 - b1 * a21) / det)

    def px_per_unit(self, p: Vec2, z: float = 0.0) -> float:
        if self.identity:
            return 1.0
        return abs(self.d / self._view(p.x, p.y, z)[2])

    def screen_vector_to_world(self, v: Vec2, at: Vec2, z: float = 0.0) -> Vec2:
        """Converts a pixel-space displacement/velocity measured at world
        point `at` into world units (first-order, via the local Jacobian)."""
        origin = self.to_screen(at, z)
        return self.to_world(origin + v, z) - at


IDENTITY = Camera(matrix=((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0)), d=1.0, center_x=0, center_y=0, identity=True)


def _floats(entry: partout.Entry) -> list[tuple[float, ...]]:
    return [struct.unpack(f"<{len(v.raw) // 4}f", v.raw) for v in entry.variants if v.type_tag == 11]


def tagged_floats(entry: partout.Entry, tag: int) -> tuple[float, ...] | None:
    """The values following `tag` in one of the entry's type-11 float arrays
    (the generic tagged accessor `FUN_0100978e`)."""
    for values in _floats(entry):
        if values and int(values[0]) == tag:
            return values[1:]
    return None


def load_camera(pf: partout.PartoutFile) -> Camera:
    camera_info = pf.find("camera_info")
    table = pf.find("table")
    if camera_info is None or table is None:
        raise ValueError("PINBALL.DAT has no camera_info/table entry")
    cam = _floats(camera_info)[0]
    center = tagged_floats(table, 700)
    table_bitmap = next(v.decoded for v in table.variants if v.type_tag == partout.BITMAP_TYPE)
    if center is None:
        raise ValueError("table entry has no tag 700 projection centre")
    return Camera(
        matrix=(tuple(cam[0:4]), tuple(cam[4:8]), tuple(cam[8:12])),
        d=cam[12],
        center_x=center[0],
        center_y=center[1],
        offset_x=float(table_bitmap["origin_x"]),
        offset_y=float(table_bitmap["origin_y"]),
    )
