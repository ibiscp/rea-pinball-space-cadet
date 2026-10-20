from space_cadet_pinball.controls import DEFAULT_KEYS, key_list, key_name
from space_cadet_pinball.geometry import Segment, circle_hit, line_hit
from space_cadet_pinball.logic import MAX_TIMERS, Timers
from space_cadet_pinball.vec2 import Vec2


def test_timer_pool_is_capped():
    timers = Timers()
    handles = [timers.schedule(1.0, lambda: None) for _ in range(MAX_TIMERS + 3)]
    assert all(handles[:MAX_TIMERS]) and handles[MAX_TIMERS:] == [0, 0, 0]


def test_timers_fire_two_due_per_tick_then_overdue_ones():
    timers = Timers()
    fired = []
    for k in range(4):
        timers.schedule(0.01, lambda k=k: fired.append(k))
    timers.update(0.05)  # 40 ms late: only two this tick
    assert fired == [0, 1]
    timers.update(0.001)
    assert fired == [0, 1, 2, 3]
    timers.schedule(0.0, lambda: fired.append("late"))
    timers.advance(150)
    timers.fire()
    assert fired[-1] == "late"


def test_timer_delay_is_truncated_to_whole_ms():
    timers = Timers()
    fired = []
    timers.schedule(0.0109, lambda: fired.append(1))  # expires at 10 ms
    timers.update(0.010)
    assert fired == [1]


def test_default_keys_and_key_list():
    assert DEFAULT_KEYS == (90, 191, 32, 88, 190, 38)
    names = [name for _vk, name in key_list()]
    assert names[:3] == ["A", "B", "C"] and "Space" in names and names[-1] == "Pause"
    assert [key_name(vk) for vk in DEFAULT_KEYS] == ["Z", "/", "Space", "X", ".", "Up"]


def test_swept_line_and_circle_tests():
    edge = Segment(Vec2(0, 0), Vec2(10, 0)).edge(1.0)  # normal (0, -1), moved to y = -1
    assert abs(line_hit(Vec2(5, -5), Vec2(0, 1), 10.0, 0.002, edge) - 4.0) < 1e-9
    assert line_hit(Vec2(5, 5), Vec2(0, -1), 10.0, 0.002, edge) is None  # from behind
    assert line_hit(Vec2(20, -5), Vec2(0, 1), 10.0, 0.002, edge) is None  # past the end
    assert abs(circle_hit(Vec2(0, -5), Vec2(0, 1), 10.0, Vec2(0, 0), 4.0) - 3.0) < 1e-9
    assert circle_hit(Vec2(0, 5), Vec2(0, 1), 10.0, Vec2(0, 0), 4.0) is None  # moving away
