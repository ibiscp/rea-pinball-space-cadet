"""The original renderer, ported from Pinball.exe (see PHYSICS_SPEC_14.md,
kept outside this repo, for every address cited here).

- The window is a 600x416 8-bit buffer sized from `table_size`
  (FUN_01015424 -> FUN_01013705), filled with palette index 0. The
  right-hand panel is the `background` bitmap, copied opaquely at its own
  origin (386, 12) by FUN_01004870.
- Table sprites live in a z-buffered layer. The `table` bitmap is a sprite
  at (0, 0) with its type-12 depth map (FUN_0101a5ab); every other sprite
  sits at its bitmap origin minus the table bitmap's origin (FUN_01017c6d).
  Rows past 416 are simply outside the buffer.
- A sprite pixel is written, and its depth stored, when its depth is <= the
  depth already there (FUN_01004a76), in creation order: the table first,
  then `table_objects` in manifest order (FUN_0101aaf3).
- The ball is drawn last: a non-zero pixel is written when the ball's
  16-bit depth is < the z-buffer (FUN_01004b75). Its sprite is chosen by
  distance from the camera against each size's tag-501 point
  (FUN_01015c08 / FUN_01019309).
- The score, ball and player boxes (`score1` / `ballcount1` /
  `player_number1`) are cleared to index 0, then get right-aligned digits
  from the `font1` entries (FUN_01013bb3 / FUN_01013d2d).
- The two text boxes are cleared to index 0, then get word-wrapped text in
  the PBMSG_FT bitmap font (FUN_01014269; string 158 "1 UseBitmapFont"
  turns that font on in FUN_01015424). Without that resource the original
  falls back to GDI DrawTextA in the colour from string 189
  (FUN_01003803), and so does this port.
- A nudge shifts the table region on screen by (floor(x + 0.5),
  floor(0.5 - y)) pixels (FUN_01014dcf -> FUN_01013a8f) until its undo.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, replace

import numpy as np
import pygame

from . import partout
from .projection import Camera, tagged_floats
from .vec2 import Vec2

CONTINUATION = 201
TEXT_COLOR_DEFAULT = (255, 255, 255)  # string 189 "255 255 255"


@dataclass(slots=True)
class Frame:
    pixels: np.ndarray  # (h, w) palette indices, top row first
    zmap: np.ndarray | None  # (h, w) uint16 depths, top row first
    x: int  # render-space position
    y: int


def bitmap_array(bitmap: dict) -> np.ndarray:
    """Type-1 pixels; stored bottom-up, as every PARTOUT bitmap."""
    arr = np.frombuffer(bitmap["pixel_data"], dtype=np.uint8).reshape(bitmap["height"], bitmap["stride"])
    return np.ascontiguousarray(arr[::-1, : bitmap["width"]])


def zmap_array(raw: bytes) -> np.ndarray:
    """Type-12 depth map: u16 width, height, stride, then 8 header bytes and
    `stride * height` unsigned 16-bit depths, bottom-up (0xffff = nothing)."""
    width, height, stride = struct.unpack_from("<HHH", raw, 0)
    arr = np.frombuffer(raw, dtype="<u2", count=stride * height, offset=14).reshape(height, stride)
    return np.ascontiguousarray(arr[::-1, :width])


def _is_continuation(entry: partout.Entry) -> bool:
    return any(
        v.type_tag == 0 and int.from_bytes(v.raw, "little", signed=True) == CONTINUATION for v in entry.variants
    )


def entry_frames(pf: partout.PartoutFile, index: int, origin: tuple[int, int]) -> list[Frame]:
    """An object's bitmaps and depth maps (FUN_0100950a on each of its
    sub-entries): the entry itself plus the type-0 = 201 entries after it."""
    frames = []
    entries = pf.entries
    i = index
    while i < len(entries) and (i == index or _is_continuation(entries[i])):
        bitmap = next((v.decoded for v in entries[i].variants if v.type_tag == partout.BITMAP_TYPE), None)
        zraw = next((v.raw for v in entries[i].variants if v.type_tag == 12), None)
        if bitmap is not None:
            frames.append(
                Frame(
                    pixels=bitmap_array(bitmap),
                    zmap=zmap_array(zraw) if zraw is not None else None,
                    x=bitmap["origin_x"] - origin[0],
                    y=bitmap["origin_y"] - origin[1],
                )
            )
        i += 1
    return frames


class Sprite:
    """A render object (FUN_0101385c). It starts on its first frame."""

    def __init__(self, name: str, frames: list[Frame]) -> None:
        self.name = name
        self.frames = frames
        first = frames[0]
        self.pixels: np.ndarray | None = first.pixels
        self.zmap = first.zmap
        self.x, self.y = first.x, first.y

    def set_bitmap(self, index: int | None) -> None:
        """FUN_010139b6: swap the bitmap only (None hides the sprite); the
        position and depth map stay those it already had."""
        self.pixels = None if index is None else self.frames[index].pixels

    def set_frame(self, index: int) -> None:
        """FUN_01013974: bitmap, depth map and position of that frame."""
        frame = self.frames[index]
        self.pixels, self.zmap, self.x, self.y = frame.pixels, frame.zmap, frame.x, frame.y


def _clip(x: int, y: int, h: int, w: int, height: int, width: int):
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, width), min(y + h, height)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def zblit(screen: np.ndarray, zbuf: np.ndarray, sprite: Sprite, table_zmap: np.ndarray) -> None:
    """FUN_01004a76: copy each pixel whose depth is <= the z-buffer's and
    store that depth. A sprite with no depth map of its own uses the table's
    at the same screen position (FUN_0101385c, DAT_010253b8)."""
    pixels = sprite.pixels
    if pixels is None:
        return
    if sprite.zmap is None:
        zsrc, zx, zy = table_zmap, 0, 0
    else:
        zsrc, zx, zy = sprite.zmap, sprite.x, sprite.y
    h = min(pixels.shape[0], zsrc.shape[0] + zy - sprite.y)
    w = min(pixels.shape[1], zsrc.shape[1] + zx - sprite.x)
    box = _clip(sprite.x, sprite.y, h, w, *screen.shape)
    if box is None:
        return
    x0, y0, x1, y1 = box
    src = pixels[y0 - sprite.y : y1 - sprite.y, x0 - sprite.x : x1 - sprite.x]
    depth = zsrc[y0 - zy : y1 - zy, x0 - zx : x1 - zx]
    zregion = zbuf[y0:y1, x0:x1]
    mask = depth <= zregion
    screen[y0:y1, x0:x1][mask] = src[mask]
    zregion[mask] = depth[mask]


def ball_blit(screen: np.ndarray, zbuf: np.ndarray, pixels: np.ndarray, depth: int, x: int, y: int) -> None:
    """FUN_01004b75: non-zero ball pixels where the ball is nearer than the
    z-buffer."""
    box = _clip(x, y, *pixels.shape, *screen.shape)
    if box is None:
        return
    x0, y0, x1, y1 = box
    src = pixels[y0 - y : y1 - y, x0 - x : x1 - x]
    mask = (src != 0) & (depth < zbuf[y0:y1, x0:x1])
    screen[y0:y1, x0:x1][mask] = src[mask]


def depth16(distance: float, zmin: float, scale: float) -> int:
    """FUN_010139ec: 0 nearer than zmin; else trunc((d - zmin) * scale) kept
    as 16 bits; 0xffff past the original's 2^32/scale + zmin limit
    (FUN_01013705)."""
    if not distance >= zmin:
        return 0
    value = (distance - zmin) * scale
    if value > 4294967296.0 / scale + zmin:
        return 0xFFFF
    return int(value) & 0xFFFF


def ball_sprite_index(distance: float, thresholds: list[float]) -> int:
    """FUN_01015c08: the first size whose tag-501 distance is <= the ball's;
    the last size otherwise."""
    for i, threshold in enumerate(thresholds[:-1]):
        if threshold <= distance:
            return i
    return len(thresholds) - 1


@dataclass(slots=True)
class DigitBox:
    """FUN_01013bb3: [first glyph entry, x, y, w, h]."""

    x: int
    y: int
    w: int
    h: int


@dataclass(slots=True)
class BitmapFont:
    """The PBMSG_FT resource (FUN_01013e73): gap, ?, line height, 128
    widths, then per glyph one byte and width*height pixels, top row first."""

    gap: int
    height: int
    glyphs: dict[int, np.ndarray]

    @classmethod
    def parse(cls, data: bytes) -> BitmapFont:
        gap, _unused, height = struct.unpack_from("<hhh", data, 0)
        widths = data[6:134]
        glyphs: dict[int, np.ndarray] = {}
        offset = 134
        for code, width in enumerate(widths):
            if not width:
                continue
            size = width * height
            glyphs[code] = np.frombuffer(data, dtype=np.uint8, count=size, offset=offset + 1).reshape(height, width)
            offset += size + 1
        return cls(gap, height, glyphs)


def layout_text(font: BitmapFont, text: str, box_w: int, box_h: int) -> list[tuple[int, int, int]]:
    """FUN_01014269's line breaking, as (char, x, y) placements relative to
    the box: a line takes characters while gap + width keeps it within the
    box, breaking at its last space if it has one; spaces after a break and
    one newline are skipped; lines stop once the next one would not fit."""
    data = [ord(ch) & 0x7F for ch in text] + [0]
    placed: list[tuple[int, int, int]] = []
    pos, y = 0, 0
    while data[pos] != 0 and y + font.height <= box_h:
        end, width, last_space = pos, 0, None
        while data[end] not in (0, 10):
            glyph = font.glyphs.get(data[end])
            if glyph is None:
                end += 1  # the original spins here; no shipped string has such a char
                continue
            width += font.gap + glyph.shape[1]
            if width > box_w:
                if last_space is not None:
                    end = last_space
                break
            if data[end] == 32:
                last_space = end
            end += 1
        x = 0
        while pos < end:
            glyph = font.glyphs.get(data[pos])
            if glyph is not None:
                placed.append((data[pos], x, y))
                x += font.gap + glyph.shape[1]
            pos += 1
        while data[pos] == 32:
            pos += 1
        if data[pos] == 10:
            pos += 1
        y += font.height
    return placed


class FlipperAnimation:
    """The flipper sprite's own frame timer (0x101c070), started by its
    message handler (0x101c178): 1 = up with frame time tag 804 / (frames -
    1), 2 = down with tag 805 / (frames - 1) (FUN_0101c59d). Each tick moves
    floor((now - start) / frame_time + 0.5) frames (at least 1) until the end
    frame; the first tick waits one frame time from rest, or the remainder of
    the time since the physics swing started (sub+0xc9) when already
    animating. The physics swing restarts its clock only from rest
    (FUN_0101bf98), and ends tag 804/805 seconds later (0x101b837)."""

    def __init__(self, sprite: Sprite, up_time: float, down_time: float, timers) -> None:
        self.sprite = sprite
        self.count = len(sprite.frames)
        self.durations = {1: up_time, 2: down_time}
        self.frame_times = {1: up_time / (self.count - 1), 2: down_time / (self.count - 1)}
        self.timers = timers
        self.mode = 0  # +6
        self.frame = 0  # +0x4e
        self.start = 0.0  # +0x66
        self.frame_time = self.frame_times[1]  # +0x62
        self._timer = 0  # +0x56
        self._swing_start = 0.0  # sub+0xc9
        self._swing_end = -1.0  # sub+0xcd

    def message(self, code: int) -> None:
        now = self.timers.now
        self.frame_time = self.frame_times[code]
        if self._timer:
            self.timers.cancel(self._timer)
            self._timer = 0
        if self.mode == 0:
            delay = self.frame_time
        else:
            elapsed = now - self._swing_start
            delay = elapsed - math.floor(elapsed / self.frame_time) * self.frame_time
            delay = max(delay, 0.0)
        self.mode = code
        self.start = now
        self._timer = self.timers.schedule(delay, self._tick)
        if now > self._swing_end:
            self._swing_start = now
        self._swing_end = self._swing_start + self.durations[code]

    def reset(self) -> None:
        """0x3fc / 0x400 while animating: frame -1, going down, ticked at
        once -- i.e. straight to frame 0 (0x101c1c0)."""
        if not self.mode:
            return
        if self._timer:
            self.timers.cancel(self._timer)
            self._timer = 0
        self.frame = -1
        self.mode = 2
        self._tick()

    def _tick(self) -> None:
        self._timer = 0
        steps = math.floor((self.timers.now - self.start) / self.frame_time + 0.5)
        steps = max(1, min(steps, self.count))
        done = False
        if self.mode == 1:
            self.frame += steps
            if self.frame >= self.count - 1:
                self.frame, done = self.count - 1, True
        elif self.mode == 2:
            self.frame -= steps
            if self.frame <= 0:
                self.frame, done = 0, True
        if done:
            self.mode = 0
        else:
            self._timer = self.timers.schedule(self.frame_time, self._tick)
        self.sprite.set_frame(self.frame)


def nudge_shift(x: float, y: float) -> tuple[int, int]:
    """FUN_01014dcf's screen offset for a nudge call (x, y)."""
    return math.floor(x + 0.5), math.floor(0.5 - y)


class Renderer:
    def __init__(
        self,
        pf: partout.PartoutFile,
        palette: list[tuple[int, int, int]],
        camera: Camera,
        font_data: bytes | None = None,
    ) -> None:
        width, height = _tag10(pf.find("table_size"))[:2]
        self.width, self.height = int(width), int(height)
        self.palette = palette
        table_entry = pf.find("table")
        table_bitmap = next(v.decoded for v in table_entry.variants if v.type_tag == partout.BITMAP_TYPE)
        self.origin = (table_bitmap["origin_x"], table_bitmap["origin_y"])
        # Projections land in table space (FUN_01008f03), not raw origins.
        self.camera = replace(camera, offset_x=0.0, offset_y=0.0)
        cam = _floats(pf.find("camera_info"))
        self.zmin, self.zscale = cam[13], cam[14]

        index = {id(e): i for i, e in enumerate(pf.entries)}
        table_frames = entry_frames(pf, index[id(table_entry)], self.origin)
        self.table = Sprite("table", [replace(table_frames[0], x=0, y=0)])
        self.table_zmap = self.table.zmap

        self.base = np.zeros((self.height, self.width), dtype=np.uint8)
        panel = pf.find("background")
        if panel is not None:
            bitmap = next(v.decoded for v in panel.variants if v.type_tag == partout.BITMAP_TYPE)
            pixels = bitmap_array(bitmap)
            ph, pw = pixels.shape
            x, y = bitmap["origin_x"], bitmap["origin_y"]
            self.base[y : y + ph, x : x + pw] = pixels

        self.sprites: list[Sprite] = []
        self.by_name: dict[str, Sprite] = {}
        self.types: dict[str, int] = {}
        for type_id, entry_index in _manifest(pf):
            frames = entry_frames(pf, entry_index, self.origin)
            if not frames:
                continue
            name = pf.entries[entry_index].name or f"#{entry_index}"
            sprite = Sprite(name, frames)
            self.sprites.append(sprite)
            self.by_name[name] = sprite
            self.types[name] = type_id

        ball = pf.find("ball")
        ball_index = index[id(ball)]
        self.ball_frames = [f.pixels for f in entry_frames(pf, ball_index, (0, 0))]
        self.ball_thresholds = []
        for i in range(len(self.ball_frames)):
            point = tagged_floats(pf.entries[ball_index + i], 501)
            self.ball_thresholds.append(self.distance(Vec2(point[0], point[1]), point[2]))

        self.digit_boxes: dict[str, DigitBox] = {}
        self.digits: list[np.ndarray] = []
        for name in ("score1", "ballcount1", "player_number1"):
            values = _tag10(pf.find(name))
            first, x, y, w, h = values[:5]
            self.digit_boxes[name] = DigitBox(x, y, w, h)
            if not self.digits:
                self.digits = [entry_frames(pf, first + d, (0, 0))[0].pixels for d in range(10)]

        self.text_boxes: dict[str, tuple[int, int, int, int]] = {}
        for name in ("info_text_box", "mission_text_box"):
            stream = _tag10(pf.find(name))
            at = stream.index(1500)
            self.text_boxes[name] = tuple(stream[at + 1 : at + 5])
        self.font = BitmapFont.parse(font_data) if font_data else None
        self._fallback_font: pygame.font.Font | None = None

        self.shift = (0, 0)
        self.screen = self.base.copy()
        self.surface = pygame.Surface((self.width, self.height), depth=8)
        self.surface.set_palette([palette[i] if i < len(palette) else (0, 0, 0) for i in range(256)])

    def set_palette(self, palette: list[tuple[int, int, int]]) -> None:
        """FUN_010043b9 called again: every pixel now shows the new colours."""
        self.palette = palette
        self.surface.set_palette(palette)

    def distance(self, p: Vec2, z: float) -> float:
        """FUN_01008ed8: length of the camera-space vector."""
        m = self.camera.matrix
        v = [m[r][0] * p.x + m[r][1] * p.y + m[r][2] * z + m[r][3] for r in range(3)]
        return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

    # -- composition ----------------------------------------------------
    def compose(
        self,
        ball: tuple[Vec2, float] | None,
        score: int | None,
        ball_number: int | None,
        player: int | None,
        texts: dict[str, str | None],
    ) -> np.ndarray:
        vscreen = self.base.copy()
        zbuf = np.full((self.height, self.width), 0xFFFF, dtype=np.uint16)
        zblit(vscreen, zbuf, self.table, self.table_zmap)
        for sprite in self.sprites:
            zblit(vscreen, zbuf, sprite, self.table_zmap)
        if ball is not None:
            self._draw_ball(vscreen, zbuf, *ball)
        self._draw_digits(vscreen, "score1", score)
        self._draw_digits(vscreen, "ballcount1", ball_number)
        self._draw_digits(vscreen, "player_number1", player)
        for name, text in texts.items():
            self._draw_text_box(vscreen, name, text)
        self._present(vscreen)
        return vscreen

    def _draw_ball(self, vscreen: np.ndarray, zbuf: np.ndarray, position: Vec2, z: float) -> None:
        """FUN_01015c08."""
        distance = self.distance(position, z)
        pixels = self.ball_frames[ball_sprite_index(distance, self.ball_thresholds)]
        screen = self.camera.to_screen(position, z)
        x = int(screen.x) - pixels.shape[1] // 2
        y = int(screen.y) - pixels.shape[0] // 2
        ball_blit(vscreen, zbuf, pixels, depth16(distance, self.zmin, self.zscale), x, y)

    def _draw_digits(self, vscreen: np.ndarray, name: str, value: int | None) -> None:
        """FUN_01013caa + FUN_01013d2d: clear the box; a value >= 0 is drawn
        right-aligned, digit by digit from the last; past 1e9 nothing at all."""
        box = self.digit_boxes[name]
        if value is not None and value > 1_000_000_000:
            return
        vscreen[box.y : box.y + box.h, box.x : box.x + box.w] = 0
        if value is None or value < 0:
            return
        x = box.x + box.w
        for digit in reversed(str(value)):
            glyph = self.digits[int(digit)]
            gh, gw = glyph.shape
            x -= gw
            region = _clip(x, box.y, gh, gw, *vscreen.shape)
            if region is not None:
                x0, y0, x1, y1 = region
                vscreen[y0:y1, x0:x1] = glyph[y0 - box.y : y1 - box.y, x0 - x : x1 - x]

    def _draw_text_box(self, vscreen: np.ndarray, name: str, text: str | None) -> None:
        x, y, w, h = self.text_boxes[name]
        vscreen[y : y + h, x : x + w] = 0
        if not text or self.font is None:
            return
        for code, gx, gy in layout_text(self.font, text, w, h):
            glyph = self.font.glyphs[code]
            gh, gw = glyph.shape
            vscreen[y + gy : y + gy + gh, x + gx : x + gx + gw] = glyph

    def _present(self, vscreen: np.ndarray) -> None:
        """The window copy: everything right of the table region as is, the
        table region moved by the nudge offset (FUN_01013a8f). Screen pixels
        the shifted table no longer covers keep what they last showed, as
        the original never repaints them."""
        table_w = self.table.frames[0].pixels.shape[1]
        self.screen[:, table_w:] = vscreen[:, table_w:]
        dx, dy = self.shift
        region = _clip(dx, dy, self.height, table_w, *self.screen.shape)
        if region is not None:
            x0, y0, x1, y1 = region
            self.screen[y0:y1, x0:x1] = vscreen[y0 - dy : y1 - dy, x0 - dx : x1 - dx]
        pygame.surfarray.blit_array(self.surface, self.screen.T)

    def draw_fallback_text(self, target: pygame.Surface, texts: dict[str, str | None]) -> None:
        """FUN_01003803: without the bitmap font the original draws with GDI
        DrawTextA (DT_WORDBREAK | DT_NOPREFIX, transparent background) in the
        colour of string 189. The face is the window DC's default font, which
        is not in the data; pygame's default font stands in for it."""
        if self.font is not None:
            return
        if self._fallback_font is None:
            self._fallback_font = pygame.font.Font(None, 18)
        for name, text in texts.items():
            if not text:
                continue
            x, y, w, h = self.text_boxes[name]
            line_y = y
            for line in _wrap(self._fallback_font, text, w):
                if line_y + self._fallback_font.get_linesize() > y + h:
                    break
                target.blit(self._fallback_font.render(line, True, TEXT_COLOR_DEFAULT), (x, line_y))
                line_y += self._fallback_font.get_linesize()


def _wrap(font: pygame.font.Font, text: str, width: int) -> list[str]:
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if line and font.size(candidate)[0] > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def _tag10(entry: partout.Entry) -> list[int]:
    raw = next(v.raw for v in entry.variants if v.type_tag == 10)
    return list(struct.unpack(f"<{len(raw) // 2}h", raw))


def _floats(entry: partout.Entry) -> tuple[float, ...]:
    raw = next(v.raw for v in entry.variants if v.type_tag == 11)
    return struct.unpack(f"<{len(raw) // 4}f", raw)


def _manifest(pf: partout.PartoutFile) -> list[tuple[int, int]]:
    """`table_objects` tag 0x401: (type, entry index) pairs, in construction
    order (FUN_0101aaf3)."""
    values = _tag10(pf.find("table_objects"))
    return list(zip(values[1::2], values[2::2]))
