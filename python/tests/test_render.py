import struct

import numpy as np

from space_cadet_pinball.ball import Ball
from space_cadet_pinball.entities import Kickback, Rollover, WallSwitch
from space_cadet_pinball.logic import Timers
from space_cadet_pinball.render import (
    BitmapFont,
    FlipperAnimation,
    Frame,
    Sprite,
    ball_blit,
    ball_sprite_index,
    depth16,
    layout_text,
    nudge_shift,
    zblit,
)


def _sprite(frames: int, x_step: int = 0) -> Sprite:
    return Sprite(
        "s",
        [
            Frame(np.full((2, 2), i + 1, np.uint8), np.full((2, 2), 100, np.uint16), 1 + i * x_step, 1)
            for i in range(frames)
        ],
    )


def test_zblit_copies_where_depth_is_not_farther_and_stores_it():
    screen = np.zeros((4, 4), np.uint8)
    zbuf = np.full((4, 4), 0xFFFF, np.uint16)
    zbuf[1, 1] = 50  # something nearer already there
    sprite = _sprite(1)
    zblit(screen, zbuf, sprite, np.zeros((4, 4), np.uint16))
    assert screen[1, 1] == 0 and screen[1, 2] == 1 and screen[2, 2] == 1
    assert zbuf[1, 2] == 100 and zbuf[1, 1] == 50
    # equal depth also passes (<=): a later sprite at the same depth wins
    zblit(screen, zbuf, Sprite("t", [Frame(np.full((2, 2), 9, np.uint8), np.full((2, 2), 100, np.uint16), 1, 1)]), None)
    assert screen[1, 2] == 9


def test_ball_blit_skips_index_zero_and_needs_strictly_nearer():
    screen = np.zeros((3, 3), np.uint8)
    zbuf = np.full((3, 3), 500, np.uint16)
    pixels = np.array([[0, 7, 7], [7, 7, 7], [7, 7, 7]], np.uint8)
    ball_blit(screen, zbuf, pixels, 500, 0, 0)
    assert not screen.any()
    ball_blit(screen, zbuf, pixels, 499, 0, 0)
    assert screen[0, 0] == 0 and screen[0, 1] == 7


def test_set_bitmap_keeps_position_set_frame_moves():
    sprite = _sprite(3, x_step=5)
    sprite.set_bitmap(2)
    assert sprite.x == 1 and sprite.pixels[0, 0] == 3
    sprite.set_bitmap(None)
    assert sprite.pixels is None
    sprite.set_frame(2)
    assert sprite.x == 11 and sprite.pixels[0, 0] == 3


def test_depth16_matches_the_original_conversion():
    assert depth16(10.0, 19.5, 4304.0) == 0
    assert depth16(20.0, 19.5, 4304.0) == int(0.5 * 4304.0)
    assert depth16(36.0, 19.5, 4304.0) == int(16.5 * 4304.0) & 0xFFFF


def test_ball_sprite_index_takes_first_threshold_at_or_below():
    thresholds = [34.0, 25.0, 23.0, 21.0]
    assert ball_sprite_index(40.0, thresholds) == 0
    assert ball_sprite_index(24.0, thresholds) == 2
    assert ball_sprite_index(20.0, thresholds) == 3


def _font() -> BitmapFont:
    widths = bytearray(128)
    widths[ord(" ")] = 2
    for ch in "abc":
        widths[ord(ch)] = 3
    data = bytearray(struct.pack("<hhh", 1, 0, 4)) + widths
    for code, width in enumerate(widths):
        if width:
            data += bytes([0]) + bytes([code]) * (width * 4)
    return BitmapFont.parse(bytes(data))


def test_bitmap_font_parse_skips_each_glyphs_first_byte():
    font = _font()
    assert font.gap == 1 and font.height == 4
    assert font.glyphs[ord("a")].shape == (4, 3) and (font.glyphs[ord("a")] == ord("a")).all()


def test_text_breaks_at_last_space_and_stops_at_box_height():
    font = _font()
    # each letter takes 1 + 3; "ab ab" = 4 + 4 + 3 + 4 + 4 = 19 > 12
    placed = layout_text(font, "ab ab ab", 12, 8)
    assert [(chr(c), x, y) for c, x, y in placed] == [("a", 0, 0), ("b", 4, 0), ("a", 0, 4), ("b", 4, 4)]
    newline = layout_text(font, "a\nb", 40, 40)
    assert [(chr(c), y) for c, _x, y in newline] == [("a", 0), ("b", 4)]


def test_flipper_frames_follow_the_original_timer_at_60fps():
    timers = Timers()
    sprite = _sprite(8)
    anim = FlipperAnimation(sprite, up_time=0.04, down_time=0.08, timers=timers)
    seen = []
    anim.message(1)
    for _ in range(3):
        timers.update(1 / 60)
        seen.append(anim.frame)
    anim.message(2)
    for _ in range(4):
        timers.update(1 / 60)
        seen.append(anim.frame)
    assert seen == [3, 7, 7, 6, 3, 0, 0]
    assert anim.mode == 0


def test_nudge_shift_and_its_undo_cancel():
    assert nudge_shift(2.0, 1.0) == (2, -1)
    assert nudge_shift(-2.0, -1.0) == (-2, 1)
    assert nudge_shift(0.0, 1.0) == (0, -1)


def test_lit_rollover_shows_on_entry_and_hides_after_leaving():
    roll = Rollover("a_roll9", lights_on_entry=True, light_time=0.15)
    ball = Ball(position=None)
    assert not roll.shown
    roll.cross(ball)
    assert roll.shown
    roll.cross(ball)
    roll.update(0.1)
    assert roll.shown
    roll.update(0.06)
    assert not roll.shown


def test_plain_rollover_hides_while_the_ball_is_inside():
    roll = Rollover("a_roll1")
    ball = Ball(position=None)
    assert roll.shown
    roll.cross(ball)
    assert not roll.shown
    roll.cross(ball)
    assert roll.shown


def test_slingshot_hides_at_the_earliest_pending_timer():
    sling = WallSwitch("v_rebo1", kick_threshold=0.0, kick=1.0)
    sling.after_bounce(5.0, 0.0, False)
    sling.update(0.06)
    sling.after_bounce(5.0, 0.0, False)
    sling.update(0.05)  # the first timer ends: hidden despite the second hit
    assert not sling.lit


def test_kickback_sprite_frames():
    kickback = Kickback("a_kick1", kick=55.0)
    assert kickback.frame == 0
    kickback.kick_for_contact(False)
    kickback.update(0.7)
    assert kickback.frame == 1
    kickback.armed = False
    kickback.update(0.1)
    assert kickback.frame == 0
