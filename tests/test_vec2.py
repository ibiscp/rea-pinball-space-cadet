import math

from space_cadet_pinball.vec2 import Vec2


def test_add_sub():
    a = Vec2(1, 2)
    b = Vec2(3, 4)
    assert a + b == Vec2(4, 6)
    assert b - a == Vec2(2, 2)


def test_length_and_normalize():
    v = Vec2(3, 4)
    assert v.length() == 5
    n = v.normalized()
    assert math.isclose(n.length(), 1.0, rel_tol=1e-6)


def test_dot_and_cross():
    a = Vec2(1, 0)
    b = Vec2(0, 1)
    assert a.dot(b) == 0
    assert a.cross(b) == 1


def test_rotated_quarter_turn():
    v = Vec2(1, 0)
    r = v.rotated(math.pi / 2)
    assert math.isclose(r.x, 0, abs_tol=1e-9)
    assert math.isclose(r.y, 1, abs_tol=1e-9)
