"""Regenerates src/space_cadet_pinball/data/ from an original copy of
3D Pinball for Windows (dev-only; the game itself never reads the original).

    uv run python tools/convert_original.py   (from python/) <folder with PINBALL.DAT, Pinball.exe, *.WAV, PINBALL.MID | archive.7z>

Ports:
- PINBALL.DAT -> data/pinball/: manifest.json (every entry and variant in
  file order; numbers, strings, the palette as JSON), bitmaps/*.png (8-bit
  indexed, original palette indices, top row first), depth/*.npy (uint16
  depth maps, top row first).
- Pinball.exe RCDATA "PBMSG_FT" -> data/pbmsg_ft.png (glyph atlas) + .json.
- Pinball.exe RT_BITMAP "SPLASH_BITMAP" -> data/splash.png.
- The WAVs PINBALL.DAT names, and PINBALL.MID -> data/sounds/.

Then rebuilds everything through the game's own loaders and checks it
byte-for-byte against the originals (the whole PINBALL.DAT included);
exits non-zero on any difference.
"""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from space_cadet_pinball import assets, partout, pngio

MUSIC = ("PINBALL.MID",)
RT_BITMAP, RT_RCDATA = 2, 10


def pe_resource(data: bytes, type_id: int, name: str) -> bytes | None:
    """A named resource of the given type from a PE image."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    sections, opt_size = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
    rsrc_rva = struct.unpack_from("<I", data, pe + 24 + (opt_size - 16 * 8) + 2 * 8)[0]
    rsrc_off = None
    for i in range(sections):
        o = pe + 24 + opt_size + i * 40
        size, va, raw_size, raw_ptr = struct.unpack_from("<IIII", data, o + 8)
        if va <= rsrc_rva < va + max(size, raw_size):
            rsrc_off = raw_ptr + (rsrc_rva - va)
    if rsrc_off is None:
        return None

    def entries(directory: int):
        named, ids = struct.unpack_from("<HH", data, rsrc_off + directory + 12)
        for k in range(named + ids):
            key, child = struct.unpack_from("<II", data, rsrc_off + directory + 16 + 8 * k)
            if key & 0x80000000:
                at = rsrc_off + (key & 0x7FFFFFFF)
                length = struct.unpack_from("<H", data, at)[0]
                key = data[at + 2 : at + 2 + 2 * length].decode("utf-16le")
            yield key, child

    def leaf(child: int) -> bytes:
        while child & 0x80000000:
            child = next(iter(entries(child & 0x7FFFFFFF)))[1]
        rva, size = struct.unpack_from("<II", data, rsrc_off + child)
        start = rsrc_off + (rva - rsrc_rva)
        return data[start : start + size]

    for key, child in entries(0):
        if key == type_id and child & 0x80000000:
            for key2, child2 in entries(child & 0x7FFFFFFF):
                if key2 == name:
                    return leaf(child2)
    return None


def find_file(folder: Path, name: str) -> Path | None:
    return next((p for p in folder.rglob("*") if p.name.lower() == name.lower()), None)


def unpack_archive(archive: Path, into: Path) -> None:
    import py7zr

    with py7zr.SevenZipFile(archive, mode="r") as z:
        # py7zr can't undo the BCJ2 filter on Pinball.exe; a system 7-Zip or
        # bsdtar extracts that one below.
        z.extract(path=into, targets=[n for n in z.getnames() if not n.lower().endswith(".exe")])
    for command in (
        *([tool, "x", "-y", f"-o{into}", str(archive), "*.exe", "-r"] for tool in ("7zz", "7z", "7za")),
        *([tool, "-xf", str(archive), "-C", str(into)] for tool in ("bsdtar", "tar")),
    ):
        if (
            shutil.which(command[0])
            and subprocess.run(command, check=False, capture_output=True).returncode == 0
            and find_file(into, "Pinball.exe")
        ):
            return


def _safe(name: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name) if name else "unnamed"


def port_variant(v: partout.Variant, stem: str, out: Path, palette: list) -> dict:
    """The ported form of one variant (files written under `out`); falls
    back to base64 if a readable form wouldn't rebuild the exact bytes."""
    spec: dict = {"type": v.type_tag, "size": v.size, "offset": v.offset}
    raw = v.raw
    if v.type_tag == partout.BITMAP_TYPE:
        d = v.decoded
        pixels = np.frombuffer(d["pixel_data"], np.uint8).reshape(d["height"], d["stride"])[::-1, : d["width"]]
        png = f"bitmaps/{stem}.png"
        pngio.write_indexed(out / png, np.ascontiguousarray(pixels), palette)
        spec.update(kind="bitmap", png=png, reserved=d["reserved"], origin_x=d["origin_x"],
                    origin_y=d["origin_y"], flags=d["flags"])
    elif v.type_tag == 12 and len(raw) >= 14:
        header = list(struct.unpack_from("<7H", raw, 0))
        _w, h, stride = header[:3]
        if h and stride and len(raw) == 14 + 2 * h * stride:
            npy = f"depth/{stem}.npy"
            rows = np.frombuffer(raw, "<u2", offset=14).reshape(h, stride)[::-1]
            np.save(out / npy, np.ascontiguousarray(rows, dtype=np.uint16))
            spec.update(kind="depth", npy=npy, header=header)
    elif v.type_tag in (partout.NAME_TYPE, 9) and raw.endswith(b"\0"):
        spec.update(kind="text", value=raw[:-1].decode("latin-1"))
    elif v.type_tag == 0 and len(raw) == 2:
        spec.update(kind="int16", value=struct.unpack("<h", raw)[0])
    elif v.type_tag == 10 and len(raw) % 2 == 0:
        spec.update(kind="int16s", value=list(struct.unpack(f"<{len(raw) // 2}h", raw)))
    elif v.type_tag == 11 and len(raw) % 4 == 0:
        spec.update(kind="float32s", value=list(struct.unpack(f"<{len(raw) // 4}f", raw)))
    elif v.type_tag == 5 and len(raw) == 1024:
        spec.update(kind="palette", value=[[raw[i + 2], raw[i + 1], raw[i], raw[i + 3]] for i in range(0, 1024, 4)])
    if "kind" not in spec or partout.variant_raw(spec, out) != raw:
        for key in ("png", "npy"):
            if key in spec:
                (out / spec[key]).unlink()
        spec = {"type": v.type_tag, "size": v.size, "offset": v.offset, "kind": "base64",
                "value": base64.b64encode(raw).decode()}
    return spec


def port_pinball_dat(dat: Path, out: Path) -> None:
    pf = partout.parse(str(dat))
    if out.exists():
        shutil.rmtree(out)
    (out / "bitmaps").mkdir(parents=True)
    (out / "depth").mkdir()
    from space_cadet_pinball.resources import screen_palette

    palette = screen_palette(next(v.decoded for v in pf.find("background").variants if v.type_tag == 5))
    data = dat.read_bytes()
    header = {
        "source": "PINBALL.DAT",
        "signature": pf.signature,
        "resource_class": pf.resource_class,
        "group_name": pf.group_name,
        "header_field_a": pf.header_field_a,
        "header_unknown_u32": pf.header_unknown_u32,
        "header_field_b": pf.header_field_b,
        "total_bytes": pf.total_bytes,
        "header_hex": data[:183].hex(),
    }
    lines = []
    for e in pf.entries:
        stem = f"{e.index:03d}_{_safe(e.name)}"
        variants = [port_variant(v, f"{stem}_{k}", out, palette) for k, v in enumerate(e.variants)]
        lines.append(json.dumps({"index": e.index, "offset": e.offset, "name": e.name, "variants": variants}))
    text = '{\n"format": "space-cadet-partout-port/1",\n"header": ' + json.dumps(header, indent=1)
    text += ',\n"entries": [\n' + ",\n".join(lines) + "\n]\n}\n"
    (out / "manifest.json").write_text(text)


def rebuild_file(pf: partout.PartoutFile, header_hex: str) -> bytes:
    """The whole PARTOUT file from a loaded PartoutFile."""
    out = bytearray(bytes.fromhex(header_hex))
    for e in pf.entries:
        out.append(len(e.variants))
        for v in e.variants:
            out.append(v.type_tag)
            if partout.TYPE_SIZE_TABLE.get(v.type_tag, -1) < 0:
                out += struct.pack("<I", v.size)
            out += v.raw
    return bytes(out)


def port_font(exe: bytes, data_dir: Path, palette: list) -> bytes:
    font = pe_resource(exe, RT_RCDATA, "PBMSG_FT")
    gap, unused, height = struct.unpack_from("<hhh", font, 0)
    widths = list(font[6:134])
    lead, glyphs, offset = {}, [], 134
    for code, width in enumerate(widths):
        if not width:
            continue
        lead[str(code)] = font[offset]
        glyphs.append(np.frombuffer(font, np.uint8, count=width * height, offset=offset + 1).reshape(height, width))
        offset += width * height + 1
    if offset != len(font):
        raise SystemExit(f"PBMSG_FT has {len(font) - offset} unexpected trailing bytes")
    pngio.write_indexed(assets.FONT_PNG, np.ascontiguousarray(np.hstack(glyphs)), palette)
    meta = {"gap": gap, "unused": unused, "height": height, "widths": widths, "lead": lead}
    assets.FONT_JSON.write_text(json.dumps(meta, indent=1) + "\n")
    return font


def port_splash(exe: bytes) -> None:
    import pygame

    dib = pe_resource(exe, RT_BITMAP, "SPLASH_BITMAP")
    header_size, _w, _h, _planes, bits, _comp, _size, _xr, _yr, used = struct.unpack_from("<IiiHHIIiiI", dib, 0)
    colours = used or (1 << bits if bits <= 8 else 0)
    bmp = b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, 14 + header_size + 4 * colours) + dib
    image = pygame.image.load(io.BytesIO(bmp))
    pygame.image.save(image, str(assets.SPLASH_PATH))
    back = pygame.image.load(str(assets.SPLASH_PATH))
    same = image.get_size() == back.get_size() and all(
        image.get_at((x, y))[:3] == back.get_at((x, y))[:3]
        for x in range(image.get_width())
        for y in range(image.get_height())
    )
    if not same:
        raise SystemExit("splash.png doesn't match the original bitmap")


def port_sounds(src: Path, pf: partout.PartoutFile) -> list[str]:
    wanted = sorted(
        {v.decoded for e in pf.entries for v in e.variants
         if v.type_tag in (3, 9) and isinstance(v.decoded, str) and v.decoded.lower().endswith(".wav")}
        | set(MUSIC),
        key=str.lower,
    )
    if assets.SOUNDS_DIR.exists():
        shutil.rmtree(assets.SOUNDS_DIR)
    assets.SOUNDS_DIR.mkdir(parents=True)
    missing = []
    for name in wanted:
        found = find_file(src, name)
        if found is None:
            missing.append(name)  # absent from the shipped game too
            continue
        shutil.copyfile(found, assets.SOUNDS_DIR / found.name)
        if (assets.SOUNDS_DIR / found.name).read_bytes() != found.read_bytes():
            raise SystemExit(f"copy of {found.name} differs")
    return missing


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    source = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        if source.is_file():
            unpack_archive(source, Path(tmp))
            source = Path(tmp)
        dat, exe_path = find_file(source, "PINBALL.DAT"), find_file(source, "Pinball.exe")
        if dat is None or exe_path is None:
            raise SystemExit("need PINBALL.DAT and Pinball.exe")

        port_pinball_dat(dat, assets.PINBALL_DIR)
        manifest = json.loads((assets.PINBALL_DIR / "manifest.json").read_text())
        ported = partout.load_ported(assets.PINBALL_DIR)
        original = partout.parse(str(dat))
        for a, b in zip(original.entries, ported.entries, strict=True):
            for va, vb in zip(a.variants, b.variants, strict=True):
                if (va.type_tag, va.size, va.offset, va.raw) != (vb.type_tag, vb.size, vb.offset, vb.raw):
                    raise SystemExit(f"entry {a.index}: variant differs after the round trip")
        if rebuild_file(ported, manifest["header"]["header_hex"]) != dat.read_bytes():
            raise SystemExit("rebuilt PINBALL.DAT differs from the original")

        exe = exe_path.read_bytes()
        from space_cadet_pinball.resources import screen_palette

        palette = screen_palette(next(v.decoded for v in ported.find("background").variants if v.type_tag == 5))
        font = port_font(exe, assets.DATA_DIR, palette)
        if assets.font_data() != font:
            raise SystemExit("rebuilt PBMSG_FT differs from the original")
        port_splash(exe)
        missing = port_sounds(source, original)

    kinds: dict[str, int] = {}
    for entry in manifest["entries"]:
        for spec in entry["variants"]:
            kinds[spec["kind"]] = kinds.get(spec["kind"], 0) + 1
    print(f"PINBALL.DAT: {len(manifest['entries'])} entries, variants by kind {kinds}; whole file rebuilt byte-exact")
    print("PBMSG_FT font rebuilt byte-exact; splash.png pixel-exact")
    print(f"sounds: {len(list(assets.SOUNDS_DIR.iterdir()))} files; referenced but not in the original copy: {missing}")


if __name__ == "__main__":
    main()
