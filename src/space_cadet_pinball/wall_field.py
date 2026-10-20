"""Parser for the "table" entry's type-12 variant in PINBALL.DAT: a
per-pixel raster aligned with the table's own background bitmap.

CORRECTION (11th RE pass, PHYSICS_SPEC_11.md): this raster is the
background's **z-buffer depth map**, not collision data. FUN_0100950a stores
the type-12 blob as the visual's zmap (visual+0x44, next to the bitmap at
+0x40), and the table constructor FUN_0101a5ab passes it to
render::create_sprite (FUN_0101385c) and render::set_background_zmap
(FUN_0101394e), which use it to hide the ball behind raised parts of the
art. That is why it is smooth, like a distance field, with 0xFFFF for
"far". Its depth edges still outline the raised rails and lane guides, so
this module's edge extraction remains a useful stand-in for the internal
walls, whose real collision objects aren't decoded yet. The notes below are
from the earlier passes that took it for a collision field.

Reverse-engineered via REA + Ghidra against Pinball.exe. Summary (full
writeup kept outside this repo alongside the other RE spec files -- see the
README's "Reverse-engineering methodology" section):

  offset 0   u16 width   (confirmed == the table bitmap's own width, 365)
  offset 2   u16 height  (confirmed == the table bitmap's own height, 470)
  offset 4   u16 stride  (confirmed == width rounded up to a multiple of 4,
                          same convention as the type-1 bitmap sub-header)
  offset 6   u16 0       (unidentified, observed always 0)
  offset 8   u16 0       (unidentified, observed always 0)
  offset 10  u16 0       (unidentified, observed always 0)
  offset 12  u16 0x50    (unidentified, observed always 0x50/80 across every
                          object's type-12 blob checked, not just "table")
  offset 14  i16[stride*height]  the field itself, row-major, same stride
                                 convention as the bitmap (confirmed: body
                                 length == stride*height*2 exactly)

Value semantics: the field is smooth/continuous (neighboring cells differ by
small amounts almost everywhere) -- i.e. NOT a simple category/material-ID
mask, it behaves like a distance or potential field. The sentinel -1
(0xFFFF) marks cells outside the table's silhouette entirely. The *exact*
formula (what the magnitude/sign means, how the original physics code
thresholds it) was not recovered -- the real-time consumer lives behind the
same undecompiled vtable flagged in constants.py's docstring. What *is*
confirmed empirically: the gradient magnitude of this field has sharp ridges
that line up exactly with the table's real internal walls (lane guides, the
hyperspace tube, the gravity-well ring, bumper banks). `extract_wall_mask`
exploits exactly that to produce a usable wall mask without the original
algorithm, and `extract_wall_polylines` vectorizes it into line segments
directly usable as table collision geometry (see table_data.py).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from . import partout


@dataclass
class WallField:
    width: int
    height: int
    stride: int
    origin_x: int  # table-space pixel position of field[0,0]
    origin_y: int
    field: np.ndarray  # shape (height, width), dtype int16, -1 = outside table


def parse_wall_field(raw: bytes, origin_x: int, origin_y: int) -> WallField:
    width, height, stride = struct.unpack_from("<HHH", raw, 0)
    body = raw[14:]
    expected = stride * height * 2
    if len(body) != expected:
        raise ValueError(f"size mismatch: body={len(body)} expected={expected}")
    arr = np.frombuffer(body, dtype="<i2").reshape(height, stride)[:, :width]
    # Same bottom-up row order as the type-1 bitmaps (see resources.py's
    # _rows_to_buffer) -- without this flip, the extracted walls end up
    # vertically mirrored relative to the (correctly oriented) table art.
    arr = arr[::-1, :]
    return WallField(width=width, height=height, stride=stride, origin_x=origin_x, origin_y=origin_y, field=arr)


def extract_wall_mask(wf: WallField, gradient_percentile: float = 97.0) -> np.ndarray:
    """Boolean (height, width) array, True where a wall edge is present, by
    thresholding the field's gradient magnitude (see module docstring)."""
    arr = wf.field.astype(np.float64)
    empty = wf.field == -1
    gy, gx = np.gradient(arr)
    gmag = np.sqrt(gx**2 + gy**2)
    gmag[empty] = 0
    thresh = np.percentile(gmag[~empty], gradient_percentile)
    return gmag > thresh


def extract_wall_polylines(
    wf: WallField, mask: np.ndarray, min_points: int = 6, simplify_tolerance: float = 1.0
) -> list[list[tuple[float, float]]]:
    """Vectorizes the boolean edge mask into polylines in table-space pixel
    coordinates, each directly usable as a chain of Segments. Contours
    shorter than `min_points` raw pixels are dropped as noise (isolated
    gradient speckles, not real wall edges)."""
    from skimage import measure

    contours = measure.find_contours(mask.astype(float), level=0.5)
    polylines = []
    for contour in contours:
        if len(contour) < min_points:
            continue
        simplified = measure.approximate_polygon(contour, tolerance=simplify_tolerance)
        pts = [(float(wf.origin_x + x), float(wf.origin_y + y)) for y, x in simplified]
        polylines.append(pts)
    return polylines


def extract_entry_wall_polylines(
    pf: partout.PartoutFile, entry_name: str, **kwargs: float
) -> list[list[tuple[float, float]]] | None:
    """Same decode as `load_table_wall_polylines`, generalized to any named
    entry: every game object carries a type-12 field in this identical
    format, at that object's own sprite resolution (confirmed during the
    REA pass -- see this module's docstring and WALL_GEOMETRY.md). Returns
    None if the entry doesn't exist or has no type-1/type-12 pair (e.g. it's
    a purely logical trigger with no sprite, like the drain)."""
    entry = pf.find(entry_name)
    if entry is None:
        return None
    bmp_variant = next((v for v in entry.variants if v.type_tag == partout.BITMAP_TYPE), None)
    blob_variant = next((v for v in entry.variants if v.type_tag == 12), None)
    if bmp_variant is None or blob_variant is None:
        return None
    wf = parse_wall_field(blob_variant.raw, bmp_variant.decoded["origin_x"], bmp_variant.decoded["origin_y"])
    mask = extract_wall_mask(wf, **{k: v for k, v in kwargs.items() if k == "gradient_percentile"})
    return extract_wall_polylines(wf, mask, **{k: v for k, v in kwargs.items() if k != "gradient_percentile"})


def load_table_wall_polylines() -> list[list[tuple[float, float]]]:
    """Convenience one-call loader: the "table" entry's wall field,
    vectorized into polylines ready to become collision Segments."""
    from .assets import pinball_data

    return extract_entry_wall_polylines(pinball_data(), "table") or []
