from space_cadet_pinball.ball import Ball
from space_cadet_pinball.entities import Rollover
from space_cadet_pinball.geometry import TripLine
from space_cadet_pinball.logic import Bus, Light, LightGroup, Timers
from space_cadet_pinball.vec2 import Vec2
from space_cadet_pinball.world import World


def _light(name: str, timers: Timers, bus: Bus) -> Light:
    return Light(name, timers, bus, frames=1, base_times=(0.1, 0.1))


def test_timed_on_then_listener_flash_then_off():
    """lite200's Re-Deploy cycle: message 9 (temporarily on 5 s); when it
    ends the listener (0x3c) answers 0x10 (flash 5 s, then off)."""
    timers, bus = Timers(), Bus()
    light = _light("lite200", timers, bus)
    events = []

    def listener(code, obj):
        events.append(code)
        if code == 0x3C and obj.data == 0:
            obj.message(0x10, 5.0)
            obj.data = 1

    bus.listeners["lite200"] = listener
    light.message(0x13)
    assert light.lit() and light.shown == 0
    light.message(9, 5.0)
    timers.update(4.9)
    assert light.temp_on and events == []
    timers.update(0.2)
    assert events == [0x3C] and light.flashing
    timers.update(5.0)
    assert not light.lit() and light.shown is None and events == [0x3C, 0x3C]


def test_blink_alternates_with_tag_900_901_times():
    timers, bus = Timers(), Bus()
    light = Light("l", timers, bus, base_times=(0.2, 0.1))
    light.message(4)  # flash forever, starting from off
    seen = []
    for _ in range(12):
        timers.update(0.05)
        seen.append(light.shown)
    # phase 1 (on) shows for 0.1 s, phase 0 (off) for 0.2 s
    assert seen[:2] == [0, None] and seen[2:5] == [None, None, None] and 0 in seen[5:7]


def test_group_rotate_and_bargraph_message():
    timers, bus = Timers(), Bus()
    lights = [_light(f"l{i}", timers, bus) for i in range(4)]
    group = LightGroup("g", timers, bus, lights)
    group.reset()
    lights[0].message(0x13)
    group.message(0x18, 0.0)  # one step, value 0 = no repeat
    assert [light.state for light in lights] == [0, 1, 0, 0]
    group.message(0x2D, 1.0)  # bargraph: members 0..1 on
    assert [light.state for light in lights] == [1, 1, 0, 0]
    assert group.message(0x25) == 2


def test_rollover_scores_on_entry_and_rearms_after_exit():
    """FUN_01018351: the tag-600 loop fires on the way in, the reversed
    tag-603 loop on the way out, then 0.1 s before it scores again."""
    world = World()
    world.jitter = False
    world.gravity = Vec2(0.0, 0.0)
    world.friction = 0.0
    hits = []
    rollover = Rollover("a_roll", notify=lambda code, obj: hits.append(code))
    square = [Vec2(1.0, 1.0), Vec2(-1.0, 1.0), Vec2(-1.0, -1.0), Vec2(1.0, -1.0)]
    for a, b in zip(square, square[1:] + square[:1], strict=True):
        world.trip_lines.append(TripLine(a, b, 1, rollover.cross, lambda: rollover.armed))
        world.trip_lines.append(TripLine(b, a, 1, rollover.cross, lambda: rollover.inside))
    ball = Ball(position=Vec2(0.0, 3.0), radius=0.3, velocity=Vec2(0.0, -10.0))
    world.balls = [ball]
    for _ in range(30):
        world.step(1 / 60)
        rollover.update(1 / 60)
    assert hits == [0x3F] and not rollover.inside


def test_ramp_edge_moves_ball_to_ramp_layer_and_back():
    world = World()
    world.jitter = False
    world.gravity = Vec2(0.0, 0.0)
    world.friction = 0.0
    layer = []
    # Crossing y = 0 going up (against the normal of (1,0)->(-1,0)) enters.
    world.trip_lines.append(TripLine(Vec2(1.0, 0.0), Vec2(-1.0, 0.0), 1, lambda b: (setattr(b, "mask", 2),
                                                                                       layer.append(2))))
    world.trip_lines.append(TripLine(Vec2(-1.0, 0.0), Vec2(1.0, 0.0), 2, lambda b: (setattr(b, "mask", 1),
                                                                                       layer.append(1))))
    ball = Ball(position=Vec2(0.0, 0.5), radius=0.3, velocity=Vec2(0.0, -6.0))
    world.balls = [ball]
    for _ in range(20):
        world.step(1 / 60)
    assert ball.mask == 2
    ball.velocity = Vec2(0.0, 6.0)
    for _ in range(20):
        world.step(1 / 60)
    assert ball.mask == 1 and layer == [2, 1]
