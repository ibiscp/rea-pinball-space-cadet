"""The game's data, ported from the original 3D Pinball files into standard
formats and shipped inside the package (`data/`), so nothing from the
original game is needed at runtime:

- `data/pinball/`: PINBALL.DAT -- `manifest.json` (every entry and variant,
  in file order) plus indexed PNGs for the bitmaps and .npy arrays for the
  depth fields; `partout.load_ported` rebuilds the exact PartoutFile.
- `data/pbmsg_ft.png` + `.json`: Pinball.exe's PBMSG_FT text-box font.
- `data/splash.png`: Pinball.exe's SPLASH_BITMAP.
- `data/sounds/`: the WAVs PINBALL.DAT references and the PINBALL.MID theme.

`tools/convert_original.py` regenerates `data/` from an original copy.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import partout, pngio

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
PINBALL_DIR = DATA_DIR / "pinball"
SOUNDS_DIR = DATA_DIR / "sounds"
SPLASH_PATH = DATA_DIR / "splash.png"
FONT_PNG = DATA_DIR / "pbmsg_ft.png"
FONT_JSON = DATA_DIR / "pbmsg_ft.json"


@lru_cache(maxsize=1)
def pinball_data() -> partout.PartoutFile:
    """The table data (PINBALL.DAT), rebuilt from its ported files."""
    return partout.load_ported(PINBALL_DIR)


def font_data() -> bytes | None:
    """The PBMSG_FT resource bytes (render.BitmapFont.parse reads them):
    gap, unused, line height (int16), 128 glyph widths, then per glyph its
    lead byte and width*height pixels. The atlas holds the glyphs side by
    side in code order."""
    if not FONT_PNG.exists() or not FONT_JSON.exists():
        return None
    meta = json.loads(FONT_JSON.read_text())
    atlas = pngio.read_indexed(FONT_PNG)
    out = bytearray()
    for value in (meta["gap"], meta["unused"], meta["height"]):
        out += value.to_bytes(2, "little", signed=True)
    out += bytes(meta["widths"])
    x = 0
    for code, width in enumerate(meta["widths"]):
        if not width:
            continue
        out.append(meta["lead"][str(code)])
        out += atlas[:, x : x + width].tobytes()
        x += width
    return bytes(out)
