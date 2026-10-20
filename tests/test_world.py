from space_cadet_pinball.ball import Ball
from space_cadet_pinball.geometry import Circle, Segment
from space_cadet_pinball.vec2 import Vec2
from space_cadet_pinball.world import World, bounce


def test_gravity_pulls_ball_down():
    world = World()
    ball = Ball(position=Vec2(100, 100), radius=5)
    world.balls = [ball]
    world.step(1 / 60)
    assert ball.position.y > 100
    assert ball.velocity.y > 0


def test_ball_bounces_off_floor_segment():
    # The line wall sits one ball radius out along its normal (0, -1), so the
    # ball's centre stops at y = 195 (FUN_0101c813 + FUN_01008c8f).
    world = World()
    world.segments.append(Segment(Vec2(0, 200), Vec2(200, 200), restitution=0.8))
    ball = Ball(position=Vec2(100, 194.5), radius=5)
    ball.velocity = Vec2(0, 50)
    world.balls = [ball]
    world.step(1 / 60)
    assert ball.position.y <= 195 + 1e-9
    assert ball.velocity.y < 0  # bounced back upward


def test_fast_ball_does_not_tunnel():
    # Time of impact: even a ball crossing far more than the wall's width in
    # one tick stops at the contact.
    world = World()
    world.max_ball_speed = 10000.0
    world.segments.append(Segment(Vec2(0, 200), Vec2(200, 200)))
    ball = Ball(position=Vec2(100, 100), radius=5)
    ball.velocity = Vec2(0, 6000)
    world.balls = [ball]
    world.step(1 / 60)
    assert ball.position.y <= 195 + 1e-9
    assert ball.velocity.y < 0


def test_line_wall_is_one_sided():
    # FUN_01008c8f only hits a ray moving against the normal: from behind,
    # the ball passes straight through.
    world = World()
    world.max_ball_speed = 1000.0
    world.segments.append(Segment(Vec2(0, 200), Vec2(200, 200), one_sided=True))
    ball = Ball(position=Vec2(100, 210), radius=5)
    ball.velocity = Vec2(0, -120)
    world.balls = [ball]
    world.step(0.1)
    assert ball.position.y < 199
    assert ball.velocity.y < 0


def test_bumper_kicks_ball_outward():
    world = World()
    hits = []
    world.max_ball_speed = 1000.0
    world.circles.append(
        Circle(Vec2(100, 100), radius=10, kick_threshold=10.0, kick=300.0, on_hit=lambda c: hits.append(c))
    )
    ball = Ball(position=Vec2(100, 87), radius=5)
    ball.velocity = Vec2(0, 50)
    world.balls = [ball]
    world.step(1 / 60)
    assert hits, "bumper on_hit callback should fire"
    assert ball.velocity.y < 0  # kicked back out, away from the bumper
    assert ball.velocity.length() >= 300.0 - 50.0  # kick plus what's left of the bounce


def test_bumper_does_not_kick_below_threshold():
    world = World()
    hits = []
    world.circles.append(
        Circle(Vec2(100, 100), radius=10, kick_threshold=10.0, kick=300.0, on_hit=lambda c: hits.append(c))
    )
    ball = Ball(position=Vec2(100, 86), radius=5)
    ball.velocity = Vec2(0, 2)
    world.balls = [ball]
    world.step(1 / 60)
    assert not hits
    assert ball.velocity.length() < 10.0


def test_bounce_matches_original_formula():
    # FUN_01017883: direction re-mixed by e_t/e_n, speed loses (1 - e_n) of
    # the closing speed. Head-on: speed 10 -> 10 - 0.4 * 10 = 6, straight back.
    v, impact = bounce(Vec2(0, 10), Vec2(0, -1), 0.6, 0.95)
    assert impact == 10
    assert abs(v.x) < 1e-9 and abs(v.y + 6.0) < 1e-9


def test_ball_drains_below_table():
    world = World()
    world.drain_y = 400
    drained = []
    world.on_ball_drained = lambda b: drained.append(b)
    ball = Ball(position=Vec2(100, 395), radius=5)
    ball.velocity = Vec2(0, 1000)
    world.balls = [ball]
    world.step(1 / 60)
    assert not ball.alive
    assert drained == [ball]
