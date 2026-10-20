from space_cadet_pinball.demo import DemoPlayer
from space_cadet_pinball.game import Game, TextBox
from space_cadet_pinball.highscores import CLEARED, HighScores, format_score
from space_cadet_pinball.logic import Bus, Light, Timers


def _box() -> tuple[TextBox, Timers, list]:
    timers, bus = Timers(), Bus()
    ended = []
    bus.mission = lambda code, obj: ended.append(code)
    return TextBox("info_text_box", timers, bus), timers, ended


def test_text_box_queues_timed_messages_in_order():
    """FUN_010144b7 / FUN_01014269: a second message waits for the first,
    which keeps its full time; each end notifies 0x3c."""
    box, timers, ended = _box()
    box.show("Crash Bonus", 2.0)
    box.show("Player 2", -1.0)
    assert box.message_text == "Crash Bonus"
    timers.update(1.9)
    assert box.message_text == "Crash Bonus"
    timers.update(0.2)
    assert box.message_text == "Player 2" and ended == [0x3C]
    timers.update(100.0)
    assert box.message_text == "Player 2"


def test_text_box_endless_message_is_replaced_and_repeat_refreshes():
    box, timers, _ = _box()
    box.show("TILT!", -1.0)
    box.show("Game Over", -1.0)  # an endless message clears the box first
    assert box.message_text == "Game Over" and len(box.queue) == 1
    box.show("Careful...", 2.0)
    assert box.message_text == "Careful..."
    timers.update(1.5)
    box.show("Careful...", 2.0)  # same text as the tail: its timer restarts
    timers.update(1.5)
    assert box.message_text == "Careful..."
    timers.update(0.6)
    assert box.message_text is None


def test_text_box_drops_stale_and_shows_at_least_a_quarter_second():
    """A queued message whose time ran out over 2 s ago is skipped; one
    with less than 0.25 s left still shows for 0.25 s."""
    box, timers, _ = _box()
    box.show("first", 5.0)
    box.show("stale", 1.0)
    box.show("short", 5.1)
    timers.update(5.0)  # "stale" ended 4 s ago -> dropped; "short" has 0.1 s left
    assert box.message_text == "short"
    timers.update(0.2)
    assert box.message_text == "short"
    timers.update(0.1)
    assert box.message_text is None


def test_high_score_rank_insert_and_format():
    table = HighScores()
    assert table.rank(0) == -1 and table.rank(1) == 0
    table.insert(5000, "A", table.rank(5000))
    table.insert(9000, "B", table.rank(9000))
    table.insert(5000, "C", table.rank(5000))  # ties go below
    assert [(e.name, e.score) for e in table.entries[:3]] == [("B", 9000), ("A", 5000), ("C", 5000)]
    assert table.entries[3].score == CLEARED
    assert format_score(CLEARED) == "" and format_score(999) == "999"
    assert format_score(1234567) == "1,234,567" and format_score(1_000_000_005) == "1,000,000,005"


def test_high_scores_round_trip_and_verification(tmp_path):
    path = tmp_path / "settings.ini"
    table = HighScores()
    table.insert(123456, "Cadet", 0)
    table.save(path)
    loaded = HighScores()
    loaded.load(path)
    assert loaded.entries[0].name == "Cadet" and loaded.entries[0].score == 123456
    text = path.read_text(encoding="latin-1").replace("123456", "999999")
    path.write_text(text, encoding="latin-1")
    loaded.load(path)  # Verification no longer matches: cleared
    assert all(e.score == CLEARED for e in loaded.entries)


def test_light_keeps_its_state_per_player():
    """FUN_01009ae3's 0x3fc: state saved under the current player, the next
    player's copy brought back."""
    timers, bus = Timers(), Bus()
    light = Light("lite1", timers, bus)
    game = Game.__new__(Game)
    game.current_player = 0
    game._slots = {}
    light.message(1)
    light.data = 7
    assert game._swap_player(light, 1)
    assert light.state == 0 and light.data == 0 and light.shown is None
    game.current_player = 1
    assert game._swap_player(light, 0)
    assert light.state == 1 and light.data == 7 and light.shown == 0


def test_demo_flips_after_its_delay_and_drops():
    timers = Timers()
    sent = []
    demo = DemoPlayer(timers, sent.append, restart=lambda: None, flip_delay=(0.2, 0.0), hold_time=(0.4, 0.0))
    demo.active = True
    demo.cross(1400)
    demo.cross(1400)  # already pending
    timers.update(0.19)
    assert sent == []
    timers.update(0.02)
    assert sent == [1000] and demo.left_up
    timers.update(0.41)
    assert sent == [1000, 0x3E9] and not demo.left_up
    demo.cross(1404)
    assert sent[-1] == 0x3EC
    timers.update(3.1)
    assert sent[-1] == 0x3ED


def test_typed_codes():
    """FUN_0100e1b0: "1MAX" gives an extra ball and marks the game cheated;
    any other key on the way resets the code."""
    game = Game.__new__(Game)
    game.objects, game.code_state, game.cheated, game.debug_mode = {}, 0, 0, 0
    extra = []
    game._extra_ball = extra.append
    for ch in "1MAX":
        game.type_key(ord(ch))
    assert extra == [2.0] and game.cheated == 1 and game.code_state == 0
    for ch in "1MZAX":
        game.type_key(ord(ch))
    assert extra == [2.0]
    for ch in "HIDDEN TEST":
        game.type_key(ord(ch))
    assert game.debug_mode == 1
