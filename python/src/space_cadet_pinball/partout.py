#!/usr/bin/env python3
"""
Parser for the "PARTOUT(4.0)RESOURCE" file format used by 3D Pinball: Space
Cadet (Pinball.exe) for PINBALL.DAT and FONT.DAT.

Format reverse-engineered via REA (https://github.com/morluto/rea) driving a
natively-built arm64 Ghidra decompiler against Pinball.exe:
  - FUN_010064e2  : on-disk file loader / deserializer (this module mirrors it)
  - FUN_01006369  : FindEntryIndexByName (linear scan, matches via each
                     entry's type==3 "name" variant)
  - FUN_01006270  : GetVariantValue(obj, index, type) - in-memory accessor
  - DAT_010235d0  : per-type fixed-size lookup table (negative = variable,
                     read an explicit uint32 size from the file instead)

Validated by parsing both PINBALL.DAT (928,700 bytes, 541 entries) and
FONT.DAT (3,947 bytes, 10 entries) with zero leftover/misaligned bytes.

Type tag 5 (confirmed): the game's single shared 256-color palette, found as
a variant on the "background" entry. Traced via `FUN_01015424` (loads the
table) -> `FUN_010043b9` -> `CreatePalette`/`RealizePalette` (GDI32). Each
4-byte record is a Windows RGBQUAD, i.e. stored blue, green, red, reserved:
`FUN_010043b9` copies byte +2 into peRed, +1 into peGreen and +0 into
peBlue. Every game-object bitmap is indexed into this same shared palette
(see resources.screen_palette for the colors the original actually shows).
"""
from __future__ import annotations

import base64
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# DAT_010235d0, read directly out of Pinball.exe via `rea read-bytes` at
# 0x010235d0 (80 bytes = 40 int16 slots; only indices 0-18 are confirmed
# meaningful - beyond that the read runs into unrelated adjacent data).
# value >= 0  -> fixed size in bytes for this type tag
# value == -1 -> variable size: an explicit uint32 size precedes the value
TYPE_SIZE_TABLE = {
    0: 2,
    1: -1,   # bitmap (special-cased below)
    2: 2,
    3: -1,   # string
    4: -1,
    5: -1,   # confirmed: the shared 256-color palette (1024 bytes = 256 x RGB+flag)
    6: -1,
    7: -1,
    8: -1,
    9: -1,   # observed: free-text comment/description string
    10: -1,  # observed: POINT16 (two little-endian int16, e.g. table_size)
    11: -1,  # observed: camera_info block (>= 48 bytes: floats)
    12: -1,
    13: 0,   # valueless/marker type (never observed with data)
    14: -1,
    15: -1,
    16: -1,
    17: -1,
    18: 1,   # single byte (bool/flag?), never observed with data
}

BITMAP_TYPE = 1
NAME_TYPE = 3


@dataclass
class Variant:
    type_tag: int
    size: int
    offset: int  # file offset of the raw value bytes
    raw: bytes
    decoded: Any = None


@dataclass
class Entry:
    index: int
    offset: int  # file offset where this entry's variant-count byte lives
    variants: list[Variant] = field(default_factory=list)

    @property
    def name(self) -> str | None:
        for v in self.variants:
            if v.type_tag == NAME_TYPE:
                return v.decoded
        return None


@dataclass
class PartoutFile:
    path: str
    signature: str
    resource_class: str      # e.g. "3D-Pinball"
    group_name: str          # e.g. "Space Cadet Table"
    header_field_a: int      # unidentified uint16 at file offset 0xAF (local_11 use: entry count)
    header_unknown_u32: int  # unidentified uint32 at file offset 0xB1
    header_field_b: int      # unidentified uint16 at file offset 0xB5 (0 => per-entry stream; nonzero => single blob, not observed in our files)
    entries: list[Entry] = field(default_factory=list)
    total_bytes: int = 0
    consumed_bytes: int = 0

    def find(self, name: str) -> Entry | None:
        for e in self.entries:
            if e.name == name:
                return e
        return None


def _decode_bitmap(buf: bytes, off: int) -> tuple[dict, int]:
    """Decode a type==1 (bitmap) variant's payload, starting right after the
    4-byte generic explicit size that FUN_010064e2 reads unconditionally for
    every variable-size type (including type 1, even though the value is not
    used for the pixel read itself).

    Sub-header layout (14 bytes), confirmed against real file bytes by
    checking stride*height == data_size:
        +0      u8   reserved (meaning not identified)
        +1:+3   i16  width
        +3:+5   i16  height
        +5:+7   i16  origin_x
        +7:+9   i16  origin_y
        +9:+13  u32  data_size
        +13     u8   flags (bit0: row stride padded up to a multiple of 4)
    """
    start = off
    reserved = buf[off]
    off += 1
    width, height, origin_x, origin_y = struct.unpack_from('<hhhh', buf, off)
    off += 8
    data_size = struct.unpack_from('<I', buf, off)[0]
    off += 4
    flags = buf[off]
    off += 1
    stride = width
    if flags & 1 and stride % 4 != 0:
        stride = stride - (stride % 4) + 4
    pixels = buf[off:off + data_size]
    off += data_size
    info = {
        'reserved': reserved,
        'width': width,
        'height': height,
        'origin_x': origin_x,
        'origin_y': origin_y,
        'data_size': data_size,
        'flags': flags,
        'stride': stride,
        'stride_x_height_matches_data_size': stride * height == data_size,
        'pixel_data': pixels,
    }
    return info, off - start


def _decode_generic(type_tag: int, raw: bytes) -> Any:
    if type_tag == NAME_TYPE or type_tag == 9:
        # NUL-terminated ASCII string; size includes the trailing NUL.
        try:
            return raw.split(b'\x00', 1)[0].decode('latin-1')
        except Exception:
            return raw
    if type_tag == 10 and len(raw) == 4:
        a, b = struct.unpack_from('<hh', raw, 0)
        return [a, b]
    if type_tag == 5 and len(raw) == 1024:
        # The shared 256-color palette: 256 RGBQUADs (b, g, r, reserved),
        # returned as (r, g, b).
        return [(raw[i + 2], raw[i + 1], raw[i]) for i in range(0, 1024, 4)]
    if type_tag == 11:
        # camera_info: sequence of little-endian floats (observed >=48 bytes
        # consumed by caller as 12 x float32, i.e. 3 groups of 4-vectors).
        n = len(raw) // 4
        if n * 4 == len(raw):
            return list(struct.unpack_from('<%df' % n, raw, 0))
        return raw
    if type_tag == 0 and len(raw) == 2:
        return struct.unpack_from('<h', raw, 0)[0]
    if type_tag == 18 and len(raw) == 1:
        return raw[0]
    if type_tag == 13:
        return None
    # Unknown/opaque type: try a couple of cheap generic decodings so the
    # spec JSON is more readable, but keep raw bytes available too.
    if len(raw) == 4:
        try:
            f = struct.unpack_from('<f', raw, 0)[0]
            i = struct.unpack_from('<i', raw, 0)[0]
            return {'as_i32': i, 'as_f32': f}
        except Exception:
            pass
    return raw


def parse(path: str) -> PartoutFile:
    with open(path, 'rb') as fh:
        buf = fh.read()
    total = len(buf)

    sig = buf[0:21].split(b'\x00', 1)[0].decode('latin-1')
    if sig != 'PARTOUT(4.0)RESOURCE':
        raise ValueError(f'{path}: bad signature {sig!r}')

    resource_class = buf[21:71].split(b'\x00', 1)[0].decode('latin-1')
    group_name = buf[71:175].split(b'\x00', 1)[0].decode('latin-1')

    header_field_a = struct.unpack_from('<H', buf, 175)[0]
    header_unknown_u32 = struct.unpack_from('<I', buf, 177)[0]
    header_field_b = struct.unpack_from('<H', buf, 181)[0]

    off = 183
    entries: list[Entry] = []

    if header_field_b != 0:
        # Not observed in PINBALL.DAT / FONT.DAT; the loader takes a
        # different branch here (reads one flat blob of header_field_b
        # bytes). Left unimplemented since we never hit it in practice.
        raise NotImplementedError(
            f'{path}: header_field_b={header_field_b} (single-blob branch) '
            'not implemented - not observed in known files')

    n_entries = header_field_a
    for i in range(n_entries):
        entry_off = off
        n_variants = buf[off]
        off += 1
        variants: list[Variant] = []
        for _ in range(n_variants):
            type_tag = buf[off]
            off += 1
            fixed = TYPE_SIZE_TABLE.get(type_tag, -1)
            if fixed is not None and fixed >= 0:
                size = fixed
            else:
                size = struct.unpack_from('<I', buf, off)[0]
                off += 4
            value_off = off
            if type_tag == BITMAP_TYPE:
                info, consumed = _decode_bitmap(buf, off)
                raw = buf[off:off + consumed]
                off += consumed
                decoded = info
            else:
                raw = buf[off:off + size]
                off += size
                decoded = _decode_generic(type_tag, raw)
            variants.append(Variant(type_tag=type_tag, size=size,
                                     offset=value_off, raw=raw, decoded=decoded))
        entries.append(Entry(index=i, offset=entry_off, variants=variants))

    pf = PartoutFile(
        path=path, signature=sig, resource_class=resource_class,
        group_name=group_name, header_field_a=header_field_a,
        header_unknown_u32=header_unknown_u32, header_field_b=header_field_b,
        entries=entries, total_bytes=total, consumed_bytes=off,
    )
    return pf


def variant_raw(spec: dict, directory: Path) -> bytes:
    """Rebuilds a variant's raw value bytes from its ported form (see
    tools/convert_original.py and data/pinball/manifest.json)."""
    from . import pngio

    kind = spec['kind']
    if kind == 'text':
        return spec['value'].encode('latin-1') + b'\x00'
    if kind == 'int16':
        return struct.pack('<h', spec['value'])
    if kind == 'int16s':
        return struct.pack('<%dh' % len(spec['value']), *spec['value'])
    if kind == 'float32s':
        return struct.pack('<%df' % len(spec['value']), *spec['value'])
    if kind == 'palette':
        return b''.join(bytes((b, g, r, reserved)) for r, g, b, reserved in spec['value'])
    if kind == 'bitmap':
        # Rows are stored top-down in the PNG; the original keeps them
        # bottom-up, each padded with zeros to the stride.
        pixels = pngio.read_indexed(directory / spec['png'])
        height, width = pixels.shape
        stride = width + (-width % 4 if spec['flags'] & 1 else 0)
        rows = np.zeros((height, stride), dtype=np.uint8)
        rows[:, :width] = pixels[::-1]
        header = struct.pack('<BhhhhIB', spec['reserved'], width, height, spec['origin_x'],
                             spec['origin_y'], rows.size, spec['flags'])
        return header + rows.tobytes()
    if kind == 'depth':
        # Header of seven u16 (width, height, stride, 0, 0, 0, 0x50), then
        # u16 depth rows bottom-up (0xffff = nothing); the .npy holds them
        # top-down, all `stride` columns.
        field_rows = np.load(directory / spec['npy'])
        return struct.pack('<7H', *spec['header']) + field_rows[::-1].astype('<u2').tobytes()
    if kind == 'base64':
        return base64.b64decode(spec['value'])
    raise ValueError(f'unknown ported variant kind {kind!r}')


def load_ported(directory: Path) -> PartoutFile:
    """The PartoutFile `parse` would return for the original file, rebuilt
    from its ported form: same entries, variants, raw bytes and decoded
    values."""
    manifest = json.loads((directory / 'manifest.json').read_text())
    entries = []
    for ent in manifest['entries']:
        variants = []
        for spec in ent['variants']:
            raw = variant_raw(spec, directory)
            if spec['type'] == BITMAP_TYPE:
                decoded = _decode_bitmap(raw, 0)[0]
            else:
                decoded = _decode_generic(spec['type'], raw)
            variants.append(Variant(type_tag=spec['type'], size=spec['size'], offset=spec['offset'],
                                    raw=raw, decoded=decoded))
        entries.append(Entry(index=ent['index'], offset=ent['offset'], variants=variants))
    head = manifest['header']
    return PartoutFile(
        path=str(directory), signature=head['signature'], resource_class=head['resource_class'],
        group_name=head['group_name'], header_field_a=head['header_field_a'],
        header_unknown_u32=head['header_unknown_u32'], header_field_b=head['header_field_b'],
        entries=entries, total_bytes=head['total_bytes'], consumed_bytes=head['total_bytes'],
    )


def _summarize_value(v: Variant, max_blob=64):
    if v.type_tag == BITMAP_TYPE:
        d = dict(v.decoded)
        px = d.pop('pixel_data')
        d['pixel_data_len'] = len(px)
        d['pixel_data_head_hex'] = px[:16].hex()
        return d
    if isinstance(v.decoded, (bytes, bytearray)):
        if len(v.decoded) > max_blob:
            return {'_blob_len': len(v.decoded), '_head_hex': v.decoded[:max_blob].hex()}
        return {'_blob_len': len(v.decoded), '_hex': v.decoded.hex()}
    return v.decoded


def to_jsonable(pf: PartoutFile) -> dict:
    out = {
        'path': pf.path,
        'signature': pf.signature,
        'resource_class': pf.resource_class,
        'group_name': pf.group_name,
        'header_field_a_entry_count': pf.header_field_a,
        'header_unknown_u32_at_0xB1': pf.header_unknown_u32,
        'header_field_b_at_0xB5': pf.header_field_b,
        'total_bytes': pf.total_bytes,
        'consumed_bytes': pf.consumed_bytes,
        'fully_consumed': pf.consumed_bytes == pf.total_bytes,
        'entry_count': len(pf.entries),
        'entries': [],
    }
    for e in pf.entries:
        ent = {
            'index': e.index,
            'file_offset': e.offset,
            'name': e.name,
            'variants': [
                {
                    'type_tag': v.type_tag,
                    'size': v.size,
                    'file_offset': v.offset,
                    'value': _summarize_value(v),
                }
                for v in e.variants
            ],
        }
        out['entries'].append(ent)
    return out


if __name__ == '__main__':
    import json
    target = sys.argv[1] if len(sys.argv) > 1 else 'PINBALL.DAT'
    pf = parse(target)
    print(f'{target}: signature={pf.signature!r} resource_class={pf.resource_class!r} '
          f'group_name={pf.group_name!r}', file=sys.stderr)
    print(f'  entries declared(header_field_a)={pf.header_field_a} parsed={len(pf.entries)}',
          file=sys.stderr)
    print(f'  total_bytes={pf.total_bytes} consumed_bytes={pf.consumed_bytes} '
          f'fully_consumed={pf.consumed_bytes == pf.total_bytes}', file=sys.stderr)
    named = [e for e in pf.entries if e.name]
    print(f'  named entries: {len(named)} / {len(pf.entries)}', file=sys.stderr)
    if len(sys.argv) > 2:
        with open(sys.argv[2], 'w') as out:
            json.dump(to_jsonable(pf), out, indent=1)
        print(f'  wrote {sys.argv[2]}', file=sys.stderr)
