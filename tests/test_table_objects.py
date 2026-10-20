from space_cadet_pinball.ball import Ball
from space_cadet_pinball.entities import Kickback, Sink
from space_cadet_pinball.geometry import Segment
from space_cadet_pinball.vec2 import Vec2
from space_cadet_pinball.world import World


def _world_with(segment: Segment) -> World:
    world = World()
    world.jitter = False
    world.segments.append(segment)
    return world


def test_one_sided_line_blocks_from_front_and_passes_from_back():
    # a -> b along +x: normal (dy, -dx) = (0, -1), so the front is -y.
    line = Segment(Vec2(0.0, 0.0), Vec2(10.0, 0.0), one_sided=True)
    world = _world_with(line)
    world.gravity = Vec2(0.0, 0.0)

    from_front = Ball(position=Vec2(5.0, -0.5), radius=0.3, velocity=Vec2(0.0, 10.0))
    world.balls = [from_front]
    for _ in range(10):
        world.step(1 / 60)
    assert from_front.position.y < 0.0 and from_front.velocity.y < 0.0

    from_back = Ball(position=Vec2(5.0, 0.5), radius=0.3, velocity=Vec2(0.0, -10.0))
    world.balls = [from_back]
    for _ in range(10):
        world.step(1 / 60)
    assert from_back.position.y < -0.5  # went straight through


def test_kickback_kicks_a_resting_ball_after_its_arm_delay():
    kickback = Kickback("a_kick1", kick=55.0)
    plate = Segment(Vec2(0.0, 0.0), Vec2(2.0, 0.0), restitution=0.2, tangent_retention=0.7, one_sided=True)
    plate.behavior = kickback
    world = _world_with(plate)
    ball = Ball(position=Vec2(1.0, -0.3), radius=0.3)
    world.balls = [ball]
    kicked_at = None
    for frame in range(120):
        world.step(1 / 60)
        kickback.update(1 / 60)
        if ball.velocity.y < -20.0:
            kicked_at = frame / 60
            break
    assert kicked_at is not None and 0.6 <= kicked_at <= 0.9
    assert not kickback.armed


def test_sink_holds_then_ejects_from_its_exit_point():
    """FUN_010184ed holds the ball and notifies 0x3f; the listener's 0x38
    (FUN_01017197, negative = the tag-407 delay) ejects it."""
    notified = []
    sink = Sink(
        "v_sink",
        exit_position=Vec2(5.0, 5.0),
        direction=Vec2(0.0, -1.0),
        spread=0.0,
        speed=35.0,
        variation=0.0,
        eject_delay=2.0,
    )
    mouth = Segment(Vec2(0.0, 0.0), Vec2(2.0, 0.0), one_sided=True, behavior=sink)
    world = _world_with(mouth)
    ball = Ball(position=Vec2(1.0, -0.5), radius=0.3, velocity=Vec2(0.0, 5.0))
    world.balls = [ball]
    sink.ball_source = lambda: ball
    sink.notify = lambda code, obj: notified.append(code)
    for _ in range(30):
        world.step(1 / 60)
        sink.update(1 / 60)
    assert ball.held and sink.held_ball is ball and notified == [0x3F]
    sink.message(0x38, -1.0)
    for _ in range(125):
        sink.update(1 / 60)
    assert not ball.held
    assert ball.position == Vec2(5.0, 5.0)
    assert abs(ball.velocity.y + 35.0) < 1e-9
