"""Minimal 8-bit indexed PNG reader/writer for the ported game data.

The ported bitmaps keep the original palette *indices* (the renderer and the
depth/colour-key logic work on indices, not RGB), so they are stored as
colour-type-3 PNGs whose PLTE is the game's screen palette: they open as
normal pictures in any viewer, and reading them back gives the exact index
bytes.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_indexed(path: Path, pixels: np.ndarray, palette: list[tuple[int, int, int]]) -> None:
    """`pixels` is (height, width) uint8, top row first."""
    height, width = pixels.shape
    rows = np.zeros((height, width + 1), dtype=np.uint8)  # filter byte 0 per row
    rows[:, 1:] = pixels
    plte = bytes(channel for colour in palette for channel in colour)
    path.write_bytes(
        _SIGNATURE
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
        + _chunk(b"PLTE", plte)
        + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 9))
        + _chunk(b"IEND", b"")
    )


def read_indexed(path: Path) -> np.ndarray:
    """(height, width) uint8 index array, top row first."""
    data = path.read_bytes()
    if not data.startswith(_SIGNATURE):
        raise ValueError(f"{path}: not a PNG")
    pos, idat, header = len(_SIGNATURE), [], None
    while pos < len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if header is None or header[2:5] != (8, 3, 0) or header[6] != 0:
        raise ValueError(f"{path}: expected an 8-bit indexed, non-interlaced PNG")
    width, height = header[0], header[1]
    raw = np.frombuffer(zlib.decompress(b"".join(idat)), dtype=np.uint8).reshape(height, width + 1)
    out = np.zeros((height, width), dtype=np.uint8)
    prev = np.zeros(width, dtype=np.int32)
    for y in range(height):
        kind, line = raw[y, 0], raw[y, 1:].astype(np.int32)
        if kind == 0:
            row = line
        elif kind == 2:
            row = (line + prev) & 0xFF
        else:  # Sub / Average / Paeth depend on the previous pixel: go byte by byte
            row = np.zeros(width, dtype=np.int32)
            for x in range(width):
                a = row[x - 1] if x else 0
                b = prev[x]
                c = prev[x - 1] if x else 0
                if kind == 1:
                    pred = a
                elif kind == 3:
                    pred = (a + b) // 2
                else:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[x] = (line[x] + pred) & 0xFF
        out[y] = row
        prev = row
    return out
