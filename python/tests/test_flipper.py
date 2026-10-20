import math

from space_cadet_pinball.ball import Ball
from space_cadet_pinball.flipper import Flipper
from space_cadet_pinball.grid import Grid
from space_cadet_pinball.vec2 import Vec2
from space_cadet_pinball.world import World

BALL_R = 0.3
DT = 1 / 60


def make_flipper(side: int) -> Flipper:
    """The shipped a_flip tags 800-805 (side=-1 is the mirror)."""
    return Flipper(
        pivot=Vec2(2.4888 * side, 12.0631),
        radius=0.3110,
        rest_tip=Vec2(0.9610 * side, 13.1310),
        tip_radius=0.1933,
        extended_tip=Vec2(0.9610 * side, 11.0066),
        up_time=0.04,
        down_time=0.08,
        ball_radius=BALL_R,
    )


def make_world(flipper: Flipper) -> World:
    world = World()
    world.jitter = False
    world.flippers.append(flipper)
    return world


def upper_face(flipper: Flipper) -> Vec2:
    flipper._pose(0.0)
    return min((flipper._line1[0], flipper._line2[0]), key=lambda n: n.y)


def ball_on_face(flipper: Flipper, frac: float) -> Ball:
    r = flipper.radius + (flipper.tip_radius - flipper.radius) * frac
    p = flipper.pivot + (flipper.rest_tip - flipper.pivot) * frac
    return Ball(position=p + upper_face(flipper) * (r + BALL_R + 0.001), radius=BALL_R)


def flip(side: int, frac: float) -> Ball:
    flipper = make_flipper(side)
    world = make_world(flipper)
    ball = ball_on_face(flipper, frac)
    world.balls = [ball]
    flipper.message(1, world.time)
    for _ in range(9):
        world.step(DT)
    return ball


def test_swing_angle_and_timing_follow_the_tags():
    f = make_flipper(1)
    assert math.isclose(abs(f.swing), 1.2149, abs_tol=1e-3)
    f.message(1, 10.0)
    assert f.angle_at(10.0) == 0.0
    assert math.isclose(f.angle_at(10.02), f.swing / 2, rel_tol=1e-9)
    assert math.isclose(f.angle_at(10.04), f.swing, rel_tol=1e-12)
    f.message(2, 10.05)  # still state 1: start time stays at the press
    assert f.state == 2 and f.start_time == 10.0


def test_flip_launches_a_resting_ball_upward():
    ball = flip(-1, 0.6)
    assert 40.0 < ball.speed() <= 60.0
    assert ball.velocity.y < -35.0


def test_flips_are_mirrored():
    left, right = flip(1, 0.6), flip(-1, 0.6)
    assert math.isclose(left.velocity.x, -right.velocity.x, abs_tol=1e-6)
    assert math.isclose(left.velocity.y, right.velocity.y, abs_tol=1e-6)


def test_fast_ball_never_tunnels_through_a_resting_flipper():
    for k in range(12):
        flipper = make_flipper(1)
        world = make_world(flipper)
        x = flipper.rest_tip.x + (flipper.pivot.x - flipper.rest_tip.x) * k / 11
        ball = Ball(position=Vec2(x, 10.0), radius=BALL_R, velocity=Vec2(0.0, 60.0))
        world.balls = [ball]
        hits = []
        collide = flipper.collide
        flipper.collide = lambda c=collide, h=hits: (h.append(1), c())[1]
        for _ in range(30):
            world.step(DT)
            flipper._pose(flipper.angle_at(world.time))
            assert flipper._inside(ball.position.x, ball.position.y) == 0
            if hits:
                break
        assert hits and ball.velocity.y < 0.0


def test_swinging_flipper_pushes_a_ball_out_on_the_next_tick():
    """While the flipper moves, FUN_0101b825 advances its inside-test point
    by step * direction and casts sub-rays of step * length -- both
    independent of the ball's speed -- so a fast ball can end a tick inside
    the swinging shape; the next test then finds it inside and moves it to
    the surface."""
    for k in range(12):
        flipper = make_flipper(1)
        world = make_world(flipper)
        x = flipper.rest_tip.x + (flipper.pivot.x - flipper.rest_tip.x) * k / 11
        ball = Ball(position=Vec2(x, 10.0), radius=BALL_R, velocity=Vec2(0.0, 60.0))
        world.balls = [ball]
        flipper.message(1, world.time)
        was_inside = False
        for _ in range(30):
            world.step(DT)
            flipper._pose(flipper.angle_at(world.time))
            inside = flipper._inside(ball.position.x, ball.position.y) != 0
            assert not (inside and was_inside)
            was_inside = inside


def test_ball_rolls_down_a_held_flipper_without_sinking_in():
    flipper = make_flipper(1)
    world = make_world(flipper)
    flipper.message(1, world.time)
    for _ in range(12):
        world.step(DT)
    flipper._pose(flipper.swing)
    ball = Ball(position=flipper.pivot + (flipper.tip() - flipper.pivot) * 0.7 + Vec2(0.0, -0.8), radius=BALL_R)
    world.balls = [ball]
    for _ in range(240):
        world.step(DT)
        flipper._pose(flipper.angle_at(world.time))
        assert flipper._inside(ball.position.x, ball.position.y) == 0
        if ball.position.x > flipper.pivot.x:
            break
    # The raised flipper slopes down to the pivot: the ball leaves past the
    # pivot end, never through the face.
    assert ball.position.x > flipper.pivot.x and ball.position.y < flipper.pivot.y


def test_flipper_is_only_tested_when_the_ray_walks_its_cells():
    flipper = make_flipper(1)
    world = make_world(flipper)
    world.grid = Grid(-8.0, -16.0, 16.0, 31.0)
    flipper.cells = world.grid.cells_in_box(*flipper.bounding_box())
    flipper.message(1, 0.0)
    ball = Ball(position=Vec2(-6.0, -10.0), radius=BALL_R, velocity=Vec2(0.0, 1.0))
    world.balls = [ball]
    for _ in range(30):
        world.step(DT)
    # The swing ended long ago, but no ray reached the flipper, so the edge
    # still holds the press state (FUN_0101b825 resets it lazily).
    assert flipper.state == 1
