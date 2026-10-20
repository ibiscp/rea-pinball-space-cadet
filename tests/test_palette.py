from space_cadet_pinball.partout import _decode_generic
from space_cadet_pinball.resources import screen_palette


def test_palette_records_are_rgbquad():
    raw = bytearray(1024)
    raw[40:44] = bytes([40, 32, 212, 0])  # entry 10 as stored: blue, green, red
    decoded = _decode_generic(5, bytes(raw))
    assert decoded[10] == (212, 32, 40)


def test_screen_palette_keeps_only_entries_10_to_245():
    data = [(7, 8, 9)] * 256
    colors = screen_palette(data)
    assert colors[0:10] == [(0, 0, 0)] * 10
    assert colors[10:246] == [(7, 8, 9)] * 236
    assert colors[246:255] == [(0, 0, 0)] * 9
    assert colors[255] == (255, 255, 255)


def test_debug_strip_palette_is_winmains_gradient():
    from space_cadet_pinball.resources import debug_strip_palette

    colors = debug_strip_palette()
    assert colors[11] == (8, 8, 8)
    assert colors[41] == (248, 248, 248)
    assert colors[42] == (255, 32, 32)  # 8 * 32 passed 255: green = blue = i
    assert colors[246:255] == [(0, 0, 0)] * 9
    assert colors[255] == (255, 255, 255)
