from space_cadet_pinball import assets, partout
from space_cadet_pinball.render import BitmapFont


def test_pinball_data_matches_the_original_table():
    pf = assets.pinball_data()
    assert len(pf.entries) == 541
    assert pf.signature == "PARTOUT(4.0)RESOURCE"
    assert pf.find("table_size").variants[-1].decoded == [600, 416]
    palette = next(v.decoded for v in pf.find("background").variants if v.type_tag == 5)
    assert palette[10] == (212, 32, 40)
    table = next(v.decoded for v in pf.find("table").variants if v.type_tag == partout.BITMAP_TYPE)
    assert (table["width"], table["height"]) == (365, 470)
    assert table["stride"] * table["height"] == table["data_size"] == len(table["pixel_data"])


def test_font_and_splash_are_ported():
    font = BitmapFont.parse(assets.font_data())
    assert font.height > 0 and ord("A") in font.glyphs
    assert assets.SPLASH_PATH.exists()


def test_referenced_sounds_ship_with_the_game():
    names = {p.name.lower() for p in assets.SOUNDS_DIR.iterdir()}
    assert {"pinball.mid", "sound1.wav", "sound12.wav"} <= names
