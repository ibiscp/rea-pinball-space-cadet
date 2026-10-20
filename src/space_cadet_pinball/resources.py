"""Loads PINBALL.DAT at runtime and turns it into renderable/placeable game
objects: the shared 256-color palette, the real table background art, and
every named game object that carries its own sprite bitmap (bumpers,
flippers, targets, rollovers, lights, the plunger, the ball...).

Positions come directly from each bitmap's `origin_x`/`origin_y` -- the
on-table pixel coordinates the original game blits that sprite at. This was
cross-validated during the REA/Ghidra pass by checking that it places things
sensibly (the two flippers end up symmetric about the table's horizontal
center at the bottom edge, the plunger ends up in the bottom-right corner,
etc.) -- see the README's reverse-engineering section.

Exact collision *shapes* (the fine polygon/circle data in each object's
type-11/type-12 variants) were not decoded to a confirmed coordinate system
in the REA pass, so collision geometry here is approximated from each
sprite's bounding box rather than lifted byte-for-byte from the file -- see
`table_data.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pygame

from . import partout
from .assets import pinball_data


@dataclass(slots=True)
class SpriteObject:
    name: str
    category: str  # the name's alphabetic prefix, e.g. "a_bump", "lite"
    origin_x: int
    origin_y: int
    width: int
    height: int
    surface: pygame.Surface

    @property
    def center(self) -> tuple[float, float]:
        return (self.origin_x + self.width / 2.0, self.origin_y + self.height / 2.0)


@dataclass(slots=True)
class TableResources:
    table_size: tuple[int, int]
    table_art: SpriteObject | None  # the `table` entry's bitmap, the playfield
    objects: dict[str, SpriteObject]
    palette: list[tuple[int, int, int]]
    # The `background` entry's bitmap: despite its name, the right-hand info
    # panel (logo, BALL, player and score boxes, the two message boxes),
    # copied opaquely at its own origin (386, 12) when the 600x416 screen
    # buffer is built (FUN_01015424 -> FUN_01004870; PHYSICS_SPEC_14 §1).
    panel: SpriteObject | None = None
    # Left/right playfield boundary, traced directly from the real table
    # background art (see `_trace_playfield_silhouette`): for each sampled
    # row y, the leftmost/rightmost non-background pixel of the original
    # painted table shape, in table-space pixel coordinates. This is how we
    # get the real tapered table outline without the (undecoded) type-12
    # wall/rail collision geometry.
    playfield_left: list[tuple[float, float]] = field(default_factory=list)
    playfield_right: list[tuple[float, float]] = field(default_factory=list)

    def by_category(self, prefix: str) -> list[SpriteObject]:
        return [o for o in self.objects.values() if o.category == prefix]


def _category_of(name: str) -> str:
    # Object families are named "<prefix><index>", e.g. "a_bump1", "lite42".
    i = len(name)
    while i > 0 and name[i - 1].isdigit():
        i -= 1
    return name[:i] or name


def _bitmap_to_surface(bitmap: dict, palette: list[tuple[int, int, int]], colorkey: int | None = 0) -> pygame.Surface:
    width, height, stride = bitmap["width"], bitmap["height"], bitmap["stride"]
    pixels: bytes = bitmap["pixel_data"]
    surface = pygame.Surface((width, height), depth=8)
    surface.set_palette([palette[i] if i < len(palette) else (0, 0, 0) for i in range(256)])
    pygame.pixelcopy.array_to_surface(
        surface,
        # pixel_data is row-major with the given stride; pygame wants a
        # (width, height) indexed array, column-major internally, so we hand
        # it a correctly-shaped numpy-free buffer via a temporary surface.
        _rows_to_buffer(pixels, width, height, stride),
    )
    if colorkey is not None:
        surface.set_colorkey(colorkey)
    return surface.convert_alpha() if colorkey is not None else surface.convert()


def _rows_to_buffer(pixels: bytes, width: int, height: int, stride: int):
    arr = np.frombuffer(pixels, dtype=np.uint8).reshape(height, stride)[:, :width]
    # The original format stores scanlines bottom-up (confirmed by visual
    # comparison: without this flip, the table art -- and every sprite --
    # renders upside down, e.g. the "CINEMATRONICS"/"MAXIS" logos and the
    # bottom star shape end up at the top of the table instead of the
    # bottom). Flip to the top-down row order pygame surfaces expect.
    arr = arr[::-1, :]
    return np.ascontiguousarray(arr.T)


def _trace_playfield_silhouette(
    bitmap: dict, sample_every: int = 8
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """For each sampled row of the real table background art, finds the
    leftmost/rightmost painted (non-index-0) pixel, in table-space pixel
    coordinates. This traces the actual tapered table shape straight out of
    the original art instead of guessing an outline by eye."""
    width, height, stride = bitmap["width"], bitmap["height"], bitmap["stride"]
    origin_x, origin_y = bitmap["origin_x"], bitmap["origin_y"]
    arr = np.frombuffer(bitmap["pixel_data"], dtype=np.uint8).reshape(height, stride)[:, :width]
    arr = arr[::-1, :]  # rows are stored bottom-up -- see _rows_to_buffer
    nonzero = arr != 0
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for y in range(0, height, sample_every):
        xs = np.where(nonzero[y])[0]
        if len(xs) == 0:
            continue
        left.append((float(origin_x + xs.min()), float(origin_y + y)))
        right.append((float(origin_x + xs.max()), float(origin_y + y)))
    return left, right


def screen_palette(data_palette: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """The colors the original actually puts on screen (FUN_010043b9).

    Only entries 10-245 come from PINBALL.DAT; the other 20 are taken from
    GetSystemPaletteEntries. The render buffer is a DIB_PAL_COLORS bitmap
    (FUN_01004520 -> FUN_01004154 with mode 1), so pixels show exactly these
    logical-palette colors. On a true-color display (no RC_PALETTE) the
    system-palette read fails, those 20 entries keep the zeroed static
    LOGPALETTE from .data (black), and entry 255 is forced to white.
    """
    colors = [(0, 0, 0)] * 256
    colors[10:246] = data_palette[10:246]
    colors[255] = (255, 255, 255)
    return colors


def debug_strip_palette() -> list[tuple[int, int, int]]:
    """The gradient WinMain (FUN_0100833a) loads through FUN_010043b9 when
    the "hidden test" H frame-time strip is first created: entry 10 + i gets
    red min(8i, 255) and green = blue = 8i, or i once 8i passes 255. It is
    never replaced afterwards, so the whole screen keeps these colours."""
    colors = [(0, 0, 0)] * 256
    for i in range(246):
        ramp = 8 * i
        grey = (ramp if ramp <= 0xFF else i) & 0xFF
        colors[10 + i] = (min(ramp, 0xFF), grey, grey)
    return screen_palette(colors)


@lru_cache(maxsize=1)
def load_table_resources() -> TableResources:
    pf = pinball_data()

    background_entry = pf.find("background")
    palette: list[tuple[int, int, int]] = [(0, 0, 0)] * 256
    if background_entry is not None:
        for variant in background_entry.variants:
            if variant.type_tag == 5:
                palette = screen_palette(variant.decoded)
                break

    table_size_entry = pf.find("table_size")
    table_size = tuple(table_size_entry.variants[-1].decoded) if table_size_entry else (600, 416)

    # "background" is the info panel (see TableResources.panel), not a table
    # object; "table" is the playfield art.
    NON_PLAYFIELD_BITMAPS = {"background"}

    objects: dict[str, SpriteObject] = {}
    table_sprite: SpriteObject | None = None
    panel_sprite: SpriteObject | None = None
    playfield_left: list[tuple[float, float]] = []
    playfield_right: list[tuple[float, float]] = []

    for entry in pf.entries:
        name = entry.name
        if not name:
            continue
        bitmap_variant = next((v for v in entry.variants if v.type_tag == partout.BITMAP_TYPE), None)
        if bitmap_variant is None:
            continue
        bitmap = bitmap_variant.decoded
        is_background_art = name == "table"
        if is_background_art:
            playfield_left, playfield_right = _trace_playfield_silhouette(bitmap)
        surface = _bitmap_to_surface(bitmap, palette, colorkey=None if is_background_art else 0)
        sprite = SpriteObject(
            name=name,
            category=_category_of(name),
            origin_x=bitmap["origin_x"],
            origin_y=bitmap["origin_y"],
            width=bitmap["width"],
            height=bitmap["height"],
            surface=surface,
        )
        if is_background_art:
            table_sprite = sprite
        elif name in NON_PLAYFIELD_BITMAPS:
            panel_sprite = sprite
        else:
            objects[name] = sprite

    return TableResources(
        table_size=(int(table_size[0]), int(table_size[1])),
        table_art=table_sprite,
        objects=objects,
        palette=palette,
        panel=panel_sprite,
        playfield_left=playfield_left,
        playfield_right=playfield_right,
    )
