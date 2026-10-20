"""The original's spatial grid (FUN_0100b883): 10 x 15 cells over the box of
the "table" entry's first three tag-600 points (FUN_0101a5ab).

Stateless edges give the same nearest hit whether or not the grid narrows
the candidates, so the port tests them all. The grid only matters where it
changes behaviour: a field acts on a ball only in the cells it was
registered in (FUN_0100b316 looks up the ball's own cell), and the flipper's
swept test -- which keeps state between calls -- only runs when a ray's
cell walk (FUN_0100b486) reaches one of the flipper's cells.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

from .vec2 import Vec2

COLUMNS = 10
ROWS = 15


class Grid:
    def __init__(self, x0: float, y0: float, width: float, height: float) -> None:
        self.x0, self.y0 = x0, y0
        self.cell_w = width * 0.1
        self.cell_h = height * 0.06666667
        self.inv_w = 1.0 / self.cell_w
        self.inv_h = 1.0 / self.cell_h

    def col(self, x: float) -> int:
        """FUN_0100b0f4: floor((x - x0) / cell width), clamped to the grid."""
        return min(max(math.floor((x - self.x0) * self.inv_w), 0), COLUMNS - 1)

    def row(self, y: float) -> int:
        """FUN_0100b1ae."""
        return min(max(math.floor((y - self.y0) * self.inv_h), 0), ROWS - 1)

    def cell_of(self, p: Vec2) -> tuple[int, int]:
        return self.col(p.x), self.row(p.y)

    def cells_in_box(self, min_x: float, min_y: float, max_x: float, max_y: float) -> frozenset[tuple[int, int]]:
        """FUN_0100be21: every cell whose closed rectangle overlaps the box,
        widened by trunc(cell size * 0.001) (0 for this table)."""
        mx = int(self.cell_w * 0.001)
        my = int(self.cell_h * 0.001)
        x_lo, x_hi = min_x - mx, mx + max_x
        y_lo, y_hi = min_y - my, my + max_y
        cells = set()
        for c in range(self.col(x_lo), self.col(x_hi) + 1):
            left = c * self.cell_w + self.x0
            for r in range(self.row(y_lo), self.row(y_hi) + 1):
                top = r * self.cell_h + self.y0
                if left <= x_hi and x_lo <= left + self.cell_w and top <= y_hi and y_lo <= top + self.cell_h:
                    cells.add((c, r))
        return frozenset(cells)

    def walk(self, origin: Vec2, direction: Vec2, length: float) -> Iterator[tuple[int, int]]:
        """FUN_0100b486's cell walk along the ray, in visiting order (cells
        outside the grid are skipped by FUN_0100b3ae)."""
        x0, y0 = origin.x, origin.y
        c0, r0 = self.col(x0), self.row(y0)
        x1 = direction.x * length + x0
        y1 = direction.y * length + y0
        c1, r1 = self.col(x1), self.row(y1)
        sx = 1 if x1 > x0 else -1
        sy = 1 if y1 > y0 else -1
        w, h, gx, gy = self.cell_w, self.cell_h, self.x0, self.y0
        if r0 == r1:
            for c in range(c0, c1 + sx, sx) if (c1 - c0) * sx >= 0 else ():
                yield c, r0
            return
        if c0 == c1:
            for r in range(r0, r1 + sy, sy) if (r1 - r0) * sy >= 0 else ():
                yield c0, r
            return
        slope = (y0 - y1) / (x0 - x1)
        intercept = y0 - slope * x0
        yield c0, r0
        c, r = c0, r0
        if sx == 1:
            next_col = c0 + 1
            if sy == 1:
                next_row = r0 + 1
                while True:
                    yb = next_row * h + gy
                    yl = (next_col * w + gx) * slope + intercept
                    if yb <= yl:
                        if yl == yb:
                            c += 1
                            next_col += 1
                        r += 1
                        next_row += 1
                    else:
                        c += 1
                        next_col += 1
                    yield c, r
                    if not (c < c1 or r < r1):
                        return
            while True:
                yb = r * h + gy
                yl = (next_col * w + gx) * slope + intercept
                if yl <= yb:
                    if yl == yb:
                        c += 1
                        next_col += 1
                    r -= 1
                else:
                    c += 1
                    next_col += 1
                yield c, r
                if not (c < c1 or r1 < r):
                    return
        if sy == 1:
            next_row = r0 + 1
            while True:
                yb = next_row * h + gy
                yl = (c * w + gx) * slope + intercept
                if yb <= yl:
                    if yl == yb:
                        c -= 1
                    r += 1
                    next_row += 1
                else:
                    c -= 1
                yield c, r
                if not (c1 < c or r < r1):
                    return
        while True:
            yb = r * h + gy
            yl = (c * w + gx) * slope + intercept
            if yl <= yb:
                if yl == yb:
                    c -= 1
                r -= 1
            else:
                c -= 1
            yield c, r
            if not (c1 < c or r1 < r):
                return
