"""fdlibm's sin / cos / acos in pure Python -- the same algorithm (and
operation order) as web/src/pymath.js and V8's Math.sin/cos/acos -- plus a
check of CPython's math.hypot algorithm.

The platform libm behind Python's math module differs from fdlibm in the
last bit for a few percent of inputs (and differs between platforms: glibc
vs Apple). trace_python.py installs these into the `math` module so the
Python and JS ports compute bit-identical primitives and the parity test
compares the game logic itself."""

from __future__ import annotations

import math
import struct


def _hi(x: float) -> int:
    return struct.unpack("<q", struct.pack("<d", x))[0] >> 32 & 0xFFFFFFFF


def _lo(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", x))[0] & 0xFFFFFFFF


def _from_words(hi: int, lo: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", (hi & 0xFFFFFFFF) << 32 | (lo & 0xFFFFFFFF)))[0]


def _signed(word: int) -> int:
    return word - (1 << 32) if word & 0x80000000 else word


S1 = -1.66666666666666324348e-01
S2 = 8.33333333332248946124e-03
S3 = -1.98412698298579493134e-04
S4 = 2.75573137070700676789e-06
S5 = -2.50507602534068634195e-08
S6 = 1.58969099521155010221e-10
C1 = 4.16666666666666019037e-02
C2 = -1.38888888888741095749e-03
C3 = 2.48015872894767294178e-05
C4 = -2.75573143513906633035e-07
C5 = 2.08757232129817482790e-09
C6 = -1.13596475577881948265e-11

NPIO2_HW = (
    0x3FF921FB, 0x400921FB, 0x4012D97C, 0x401921FB, 0x401F6A7A, 0x4022D97C, 0x4025FDBB, 0x402921FB,
    0x402C463A, 0x402F6A7A, 0x4031475C, 0x4032D97C, 0x40346AC5, 0x4035FDBB, 0x40378FBA, 0x403921FB,
    0x403AB41B, 0x403C463A, 0x403DD85A, 0x403F6A7A, 0x40407E4C, 0x4041475C, 0x4042106C, 0x4042D97C,
    0x4043A28C, 0x40446AC5, 0x404533A5, 0x4045FDBB, 0x4046C6CB, 0x40478FBA, 0x404858EB, 0x404921FB,
)
INVPIO2 = 6.36619772367581382433e-01
PIO2_1 = 1.57079632673412561417e00
PIO2_1T = 6.07710050650619224932e-11
PIO2_2 = 6.07710050630396597660e-11
PIO2_2T = 2.02226624879595063154e-21
PIO2_3 = 2.02226624871116645580e-21
PIO2_3T = 8.47842766036889956997e-32


def _kernel_sin(x: float, y: float, iy: int) -> float:
    ix = _hi(x) & 0x7FFFFFFF
    if ix < 0x3E400000 and int(x) == 0:
        return x
    z = x * x
    v = z * x
    r = S2 + z * (S3 + z * (S4 + z * (S5 + z * S6)))
    if iy == 0:
        return x + v * (S1 + z * r)
    return x - ((z * (0.5 * y - v * r) - y) - v * S1)


def _kernel_cos(x: float, y: float) -> float:
    ix = _hi(x) & 0x7FFFFFFF
    if ix < 0x3E400000 and int(x) == 0:
        return 1.0
    z = x * x
    r = z * (C1 + z * (C2 + z * (C3 + z * (C4 + z * (C5 + z * C6)))))
    if ix < 0x3FD33333:
        return 1.0 - (0.5 * z - (z * r - x * y))
    qx = 0.28125 if ix > 0x3FE90000 else _from_words(ix - 0x00200000, 0)
    hz = 0.5 * z - qx
    a = 1.0 - qx
    return a - (hz - (z * r - x * y))


def _rem_pio2(x: float) -> tuple[int, float, float]:
    hx = _signed(_hi(x))
    ix = hx & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        return 0, x, 0.0
    if ix < 0x4002D97C:
        if hx > 0:
            z = x - PIO2_1
            if ix != 0x3FF921FB:
                y0 = z - PIO2_1T
                return 1, y0, (z - y0) - PIO2_1T
            z -= PIO2_2
            y0 = z - PIO2_2T
            return 1, y0, (z - y0) - PIO2_2T
        z = x + PIO2_1
        if ix != 0x3FF921FB:
            y0 = z + PIO2_1T
            return -1, y0, (z - y0) + PIO2_1T
        z += PIO2_2
        y0 = z + PIO2_2T
        return -1, y0, (z - y0) + PIO2_2T
    if ix <= 0x413921FB:
        t = abs(x)
        n = int(t * INVPIO2 + 0.5)
        fn = float(n)
        r = t - fn * PIO2_1
        w = fn * PIO2_1T
        if n < 32 and ix != NPIO2_HW[n - 1]:
            y0 = r - w
        else:
            j = ix >> 20
            y0 = r - w
            i = j - ((_hi(y0) >> 20) & 0x7FF)
            if i > 16:
                t = r
                w = fn * PIO2_2
                r = t - w
                w = fn * PIO2_2T - ((t - r) - w)
                y0 = r - w
                i = j - ((_hi(y0) >> 20) & 0x7FF)
                if i > 49:
                    t = r
                    w = fn * PIO2_3
                    r = t - w
                    w = fn * PIO2_3T - ((t - r) - w)
                    y0 = r - w
        y1 = (r - y0) - w
        if hx < 0:
            return -n, -y0, -y1
        return n, y0, y1
    raise ValueError("argument too large for this fdlibm port")


def sin(x: float) -> float:
    ix = _hi(x) & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        return _kernel_sin(x, 0.0, 0)
    if ix >= 0x7FF00000:
        return x - x
    n, y0, y1 = _rem_pio2(x)
    k = n & 3
    if k == 0:
        return _kernel_sin(y0, y1, 1)
    if k == 1:
        return _kernel_cos(y0, y1)
    if k == 2:
        return -_kernel_sin(y0, y1, 1)
    return -_kernel_cos(y0, y1)


def cos(x: float) -> float:
    ix = _hi(x) & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        return _kernel_cos(x, 0.0)
    if ix >= 0x7FF00000:
        return x - x
    n, y0, y1 = _rem_pio2(x)
    k = n & 3
    if k == 0:
        return _kernel_cos(y0, y1)
    if k == 1:
        return -_kernel_sin(y0, y1, 1)
    if k == 2:
        return -_kernel_cos(y0, y1)
    return _kernel_sin(y0, y1, 1)


PI = 3.14159265358979311600e00
PIO2_HI = 1.57079632679489655800e00
PIO2_LO = 6.12323399573676603587e-17
PS0 = 1.66666666666666657415e-01
PS1 = -3.25565818622400915405e-01
PS2 = 2.01212532134862925881e-01
PS3 = -4.00555345006794114027e-02
PS4 = 7.91534994289814532176e-04
PS5 = 3.47933107596021167570e-05
QS1 = -2.40339491173441421878e00
QS2 = 2.02094576023350569471e00
QS3 = -6.88283971605453293030e-01
QS4 = 7.70381505559019352791e-02


def acos(x: float) -> float:
    hx = _signed(_hi(x))
    ix = hx & 0x7FFFFFFF
    if ix >= 0x3FF00000:
        if ((ix - 0x3FF00000) | _lo(x)) == 0:
            return 0.0 if hx > 0 else PI + 2.0 * PIO2_LO
        return math.nan
    if ix < 0x3FE00000:
        if ix <= 0x3C600000:
            return PIO2_HI + PIO2_LO
        z = x * x
        p = z * (PS0 + z * (PS1 + z * (PS2 + z * (PS3 + z * (PS4 + z * PS5)))))
        q = 1.0 + z * (QS1 + z * (QS2 + z * (QS3 + z * QS4)))
        r = p / q
        return PIO2_HI - (x - (PIO2_LO - x * r))
    if hx < 0:
        z = (1.0 + x) * 0.5
        p = z * (PS0 + z * (PS1 + z * (PS2 + z * (PS3 + z * (PS4 + z * PS5)))))
        q = 1.0 + z * (QS1 + z * (QS2 + z * (QS3 + z * QS4)))
        s = math.sqrt(z)
        r = p / q
        w = r * s - PIO2_LO
        return PI - 2.0 * (s + w)
    z = (1.0 - x) * 0.5
    s = math.sqrt(z)
    df = _from_words(_hi(s), 0)
    c = (z - df * df) / (s + df)
    p = z * (PS0 + z * (PS1 + z * (PS2 + z * (PS3 + z * (PS4 + z * PS5)))))
    q = 1.0 + z * (QS1 + z * (QS2 + z * (QS3 + z * QS4)))
    r = p / q
    w = r * s + c
    return 2.0 * (df + w)


def _two_product(a: float, b: float) -> tuple[float, float]:
    """Dekker: a*b as hi + lo exactly (what CPython's dl_mul computes)."""
    p = a * b
    split = 134217729.0
    t = split * a
    ah = t - (t - a)
    al = a - ah
    t = split * b
    bh = t - (t - b)
    bl = b - bh
    return p, ((ah * bh - p) + ah * bl + al * bh) + al * bl


def hypot(x: float, y: float) -> float:
    """CPython 3.12's math.hypot for two finite arguments (vector_norm)."""
    x, y = abs(x), abs(y)
    mx = max(x, y)
    if mx == 0.0:
        return mx
    _, e = math.frexp(mx)
    scale = math.ldexp(1.0, -e)
    csum, frac1, frac2 = 1.0, 0.0, 0.0
    for v in (x, y):
        v *= scale
        hi, lo = _two_product(v, v)
        s = csum + hi
        frac2 += (csum - s) + hi
        csum = s
        frac1 += lo
    h = math.sqrt(csum - 1.0 + (frac1 + frac2))
    hi, lo = _two_product(-h, h)
    s = csum + hi
    frac2 += (csum - s) + hi
    csum = s
    frac1 += lo
    v = csum - 1.0 + (frac1 + frac2)
    h += v / (2.0 * h)
    return h / scale


def install() -> None:
    """Route math.sin / cos / acos through fdlibm (as V8 does)."""
    math.sin = sin
    math.cos = cos
    math.acos = acos
