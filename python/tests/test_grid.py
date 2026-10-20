import itertools

from space_cadet_pinball.ball import Ball
from space_cadet_pinball.entities import Ramp
from space_cadet_pinball.grid import Grid
from space_cadet_pinball.vec2 import Vec2

GRID = Grid(0.0, 0.0, 10.0, 15.0)  # 1 x 1 cells, 10 columns, 15 rows


def test_cell_lookup_clamps_to_the_grid():
    assert GRID.cell_of(Vec2(-5.0, -5.0)) == (0, 0)
    assert GRID.cell_of(Vec2(3.5, 7.2)) == (3, 7)
    assert GRID.cell_of(Vec2(50.0, 50.0)) == (9, 14)


def test_box_registration_takes_every_touched_cell():
    # FUN_0100be21 compares closed rectangles: a box edge on a cell boundary
    # also registers the neighbour.
    assert GRID.cells_in_box(1.2, 1.2, 2.0, 1.8) == {(1, 1), (2, 1)}
    assert GRID.cells_in_box(1.2, 1.2, 1.8, 1.8) == {(1, 1)}


def test_walk_is_a_connected_path_between_the_end_cells():
    for direction in (Vec2(0.6, 0.8), Vec2(-0.6, 0.8), Vec2(0.6, -0.8), Vec2(-0.6, -0.8)):
        origin = Vec2(5.3, 7.4)
        cells = list(GRID.walk(origin, direction, 3.0))
        assert cells[0] == GRID.cell_of(origin)
        assert cells[-1] == GRID.cell_of(origin + direction * 3.0)
        for (c0, r0), (c1, r1) in itertools.pairwise(cells):
            assert abs(c1 - c0) + abs(r1 - r0) in (1, 2)


def test_ramp_field_acts_in_whole_cells():
    ramp = Ramp("ramp", mask=1, friction=0.2, bounds=(2.2, 2.2, 3.4, 3.4), grid=GRID)
    ramp.cells = GRID.cells_in_box(*ramp.bounds)
    moving = Vec2(1.0, 0.0)
    outside_box_same_cell = Ball(position=Vec2(2.05, 2.1), radius=0.3, velocity=moving)
    other_cell = Ball(position=Vec2(4.5, 2.5), radius=0.3, velocity=moving)
    assert ramp.accel(outside_box_same_cell) is not None
    assert ramp.accel(other_cell) is None
