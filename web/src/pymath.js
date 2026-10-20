// Numeric primitives that behave exactly like the Python port's:
// - sin / cos / acos: fdlibm (the same code as web/test/fdlibm.py, which the
//   Python parity trace installs), so results don't depend on the browser's
//   libm;
// - hypot: CPython 3.12's math.hypot algorithm (vector_norm), which
//   Vec2.length uses;
// - pyRound / pyFloorDiv / pyMod: Python's round(), // and % on numbers;
// - PyRandom: CPython's random module (MT19937, seed / random / randrange),
//   so a seeded run draws the same numbers as the Python game.

const _buf = new DataView(new ArrayBuffer(8));

function hiWord(x) {
  _buf.setFloat64(0, x);
  return _buf.getUint32(0);
}

function loWord(x) {
  _buf.setFloat64(0, x);
  return _buf.getUint32(4);
}

function fromWords(hi, lo) {
  _buf.setUint32(0, hi >>> 0);
  _buf.setUint32(4, lo >>> 0);
  return _buf.getFloat64(0);
}

const S1 = -1.66666666666666324348e-1;
const S2 = 8.33333333332248946124e-3;
const S3 = -1.98412698298579493134e-4;
const S4 = 2.75573137070700676789e-6;
const S5 = -2.50507602534068634195e-8;
const S6 = 1.58969099521155010221e-10;
const C1 = 4.16666666666666019037e-2;
const C2 = -1.38888888888741095749e-3;
const C3 = 2.48015872894767294178e-5;
const C4 = -2.75573143513906633035e-7;
const C5 = 2.08757232129817482790e-9;
const C6 = -1.13596475577881948265e-11;

const NPIO2_HW = [
  0x3ff921fb, 0x400921fb, 0x4012d97c, 0x401921fb, 0x401f6a7a, 0x4022d97c, 0x4025fdbb, 0x402921fb,
  0x402c463a, 0x402f6a7a, 0x4031475c, 0x4032d97c, 0x40346ac5, 0x4035fdbb, 0x40378fba, 0x403921fb,
  0x403ab41b, 0x403c463a, 0x403dd85a, 0x403f6a7a, 0x40407e4c, 0x4041475c, 0x4042106c, 0x4042d97c,
  0x4043a28c, 0x40446ac5, 0x404533a5, 0x4045fdbb, 0x4046c6cb, 0x40478fba, 0x404858eb, 0x404921fb,
];
const INVPIO2 = 6.36619772367581382433e-1;
const PIO2_1 = 1.57079632673412561417e0;
const PIO2_1T = 6.07710050650619224932e-11;
const PIO2_2 = 6.07710050630396597660e-11;
const PIO2_2T = 2.02226624879595063154e-21;
const PIO2_3 = 2.02226624871116645580e-21;
const PIO2_3T = 8.47842766036889956997e-32;

function kernelSin(x, y, iy) {
  const ix = hiWord(x) & 0x7fffffff;
  if (ix < 0x3e400000 && Math.trunc(x) === 0) return x;
  const z = x * x;
  const v = z * x;
  const r = S2 + z * (S3 + z * (S4 + z * (S5 + z * S6)));
  if (iy === 0) return x + v * (S1 + z * r);
  return x - ((z * (0.5 * y - v * r) - y) - v * S1);
}

function kernelCos(x, y) {
  const ix = hiWord(x) & 0x7fffffff;
  if (ix < 0x3e400000 && Math.trunc(x) === 0) return 1.0;
  const z = x * x;
  const r = z * (C1 + z * (C2 + z * (C3 + z * (C4 + z * (C5 + z * C6)))));
  if (ix < 0x3fd33333) return 1.0 - (0.5 * z - (z * r - x * y));
  const qx = ix > 0x3fe90000 ? 0.28125 : fromWords(ix - 0x00200000, 0);
  const hz = 0.5 * z - qx;
  const a = 1.0 - qx;
  return a - (hz - (z * r - x * y));
}

// Returns [n, y0, y1].
function remPio2(x) {
  const hx = hiWord(x) | 0;
  const ix = hx & 0x7fffffff;
  if (ix <= 0x3fe921fb) return [0, x, 0.0];
  if (ix < 0x4002d97c) {
    if (hx > 0) {
      let z = x - PIO2_1;
      if (ix !== 0x3ff921fb) {
        const y0 = z - PIO2_1T;
        return [1, y0, (z - y0) - PIO2_1T];
      }
      z -= PIO2_2;
      const y0 = z - PIO2_2T;
      return [1, y0, (z - y0) - PIO2_2T];
    }
    let z = x + PIO2_1;
    if (ix !== 0x3ff921fb) {
      const y0 = z + PIO2_1T;
      return [-1, y0, (z - y0) + PIO2_1T];
    }
    z += PIO2_2;
    const y0 = z + PIO2_2T;
    return [-1, y0, (z - y0) + PIO2_2T];
  }
  if (ix <= 0x413921fb) {
    let t = Math.abs(x);
    const n = Math.trunc(t * INVPIO2 + 0.5);
    const fn = n;
    let r = t - fn * PIO2_1;
    let w = fn * PIO2_1T;
    let y0;
    if (n < 32 && ix !== NPIO2_HW[n - 1]) {
      y0 = r - w;
    } else {
      const j = ix >> 20;
      y0 = r - w;
      let i = j - ((hiWord(y0) >>> 20) & 0x7ff);
      if (i > 16) {
        t = r;
        w = fn * PIO2_2;
        r = t - w;
        w = fn * PIO2_2T - ((t - r) - w);
        y0 = r - w;
        i = j - ((hiWord(y0) >>> 20) & 0x7ff);
        if (i > 49) {
          t = r;
          w = fn * PIO2_3;
          r = t - w;
          w = fn * PIO2_3T - ((t - r) - w);
          y0 = r - w;
        }
      }
    }
    const y1 = (r - y0) - w;
    if (hx < 0) return [-n, -y0, -y1];
    return [n, y0, y1];
  }
  throw new Error('fdlibm: argument too large');
}

function sin(x) {
  const ix = hiWord(x) & 0x7fffffff;
  if (ix <= 0x3fe921fb) return kernelSin(x, 0.0, 0);
  if (ix >= 0x7ff00000) return x - x;
  const [n, y0, y1] = remPio2(x);
  switch (n & 3) {
    case 0: return kernelSin(y0, y1, 1);
    case 1: return kernelCos(y0, y1);
    case 2: return -kernelSin(y0, y1, 1);
    default: return -kernelCos(y0, y1);
  }
}

function cos(x) {
  const ix = hiWord(x) & 0x7fffffff;
  if (ix <= 0x3fe921fb) return kernelCos(x, 0.0);
  if (ix >= 0x7ff00000) return x - x;
  const [n, y0, y1] = remPio2(x);
  switch (n & 3) {
    case 0: return kernelCos(y0, y1);
    case 1: return -kernelSin(y0, y1, 1);
    case 2: return -kernelCos(y0, y1);
    default: return kernelSin(y0, y1, 1);
  }
}

const PI = 3.14159265358979311600e0;
const PIO2_HI = 1.57079632679489655800e0;
const PIO2_LO = 6.12323399573676603587e-17;
const PS0 = 1.66666666666666657415e-1;
const PS1 = -3.25565818622400915405e-1;
const PS2 = 2.01212532134862925881e-1;
const PS3 = -4.00555345006794114027e-2;
const PS4 = 7.91534994289814532176e-4;
const PS5 = 3.47933107596021167570e-5;
const QS1 = -2.40339491173441421878e0;
const QS2 = 2.02094576023350569471e0;
const QS3 = -6.88283971605453293030e-1;
const QS4 = 7.70381505559019352791e-2;

function acos(x) {
  const hx = hiWord(x) | 0;
  const ix = hx & 0x7fffffff;
  if (ix >= 0x3ff00000) {
    if (((ix - 0x3ff00000) | loWord(x)) === 0) return hx > 0 ? 0.0 : PI + 2.0 * PIO2_LO;
    return NaN;
  }
  if (ix < 0x3fe00000) {
    if (ix <= 0x3c600000) return PIO2_HI + PIO2_LO;
    const z = x * x;
    const p = z * (PS0 + z * (PS1 + z * (PS2 + z * (PS3 + z * (PS4 + z * PS5)))));
    const q = 1.0 + z * (QS1 + z * (QS2 + z * (QS3 + z * QS4)));
    const r = p / q;
    return PIO2_HI - (x - (PIO2_LO - x * r));
  }
  if (hx < 0) {
    const z = (1.0 + x) * 0.5;
    const p = z * (PS0 + z * (PS1 + z * (PS2 + z * (PS3 + z * (PS4 + z * PS5)))));
    const q = 1.0 + z * (QS1 + z * (QS2 + z * (QS3 + z * QS4)));
    const s = Math.sqrt(z);
    const r = p / q;
    const w = r * s - PIO2_LO;
    return PI - 2.0 * (s + w);
  }
  const z = (1.0 - x) * 0.5;
  const s = Math.sqrt(z);
  const df = fromWords(hiWord(s), 0);
  const c = (z - df * df) / (s + df);
  const p = z * (PS0 + z * (PS1 + z * (PS2 + z * (PS3 + z * (PS4 + z * PS5)))));
  const q = 1.0 + z * (QS1 + z * (QS2 + z * (QS3 + z * QS4)));
  const r = p / q;
  const w = r * s + c;
  return 2.0 * (df + w);
}

// Dekker's exact product: a*b == hi + lo.
function twoProduct(a, b) {
  const p = a * b;
  let t = 134217729.0 * a;
  const ah = t - (t - a);
  const al = a - ah;
  t = 134217729.0 * b;
  const bh = t - (t - b);
  const bl = b - bh;
  return [p, ((ah * bh - p) + ah * bl + al * bh) + al * bl];
}

function frexpExp(x) {
  // x > 0, finite, normal: the e of frexp (x = m * 2^e, m in [0.5, 1)).
  return ((hiWord(x) >>> 20) & 0x7ff) - 1022;
}

function ldexp1(e) {
  return fromWords(((e + 1023) & 0x7ff) << 20, 0);
}

// CPython 3.12 math.hypot(x, y) (vector_norm) for finite, normal inputs.
function hypot(x, y) {
  x = Math.abs(x);
  y = Math.abs(y);
  const mx = x > y ? x : y;
  if (mx === 0.0) return mx;
  if (mx < 2.2250738585072014e-308) return Math.hypot(x, y);
  const scale = ldexp1(-frexpExp(mx));
  let csum = 1.0;
  let frac1 = 0.0;
  let frac2 = 0.0;
  for (const value of [x, y]) {
    const v = value * scale;
    const [hi, lo] = twoProduct(v, v);
    const s = csum + hi;
    frac2 += (csum - s) + hi;
    csum = s;
    frac1 += lo;
  }
  let h = Math.sqrt(csum - 1.0 + (frac1 + frac2));
  const [hi, lo] = twoProduct(-h, h);
  const s = csum + hi;
  frac2 += (csum - s) + hi;
  csum = s;
  frac1 += lo;
  const v = csum - 1.0 + (frac1 + frac2);
  h += v / (2.0 * h);
  return h / scale;
}

// Python's round(x) for a float: nearest integer, ties to even.
function pyRound(x) {
  const f = Math.floor(x);
  const diff = x - f;
  if (diff > 0.5) return f + 1;
  if (diff < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

function pyFloorDiv(a, b) {
  return Math.floor(a / b);
}

function pyMod(a, b) {
  const r = a % b;
  return r !== 0 && (r < 0) !== (b < 0) ? r + b : r;
}

const f32 = Math.fround;

// CPython's random.Random (MT19937).
class PyRandom {
  constructor(seed = Date.now()) {
    this.mt = new Uint32Array(624);
    this.index = 624;
    this.seed(seed);
  }

  _initGenrand(s) {
    const mt = this.mt;
    mt[0] = s >>> 0;
    for (let i = 1; i < 624; i++) {
      const prev = mt[i - 1] ^ (mt[i - 1] >>> 30);
      mt[i] = (Math.imul(1812433253, prev) + i) >>> 0;
    }
    this.index = 624;
  }

  seed(n) {
    // int seed: its absolute value split into 32-bit words, low first.
    let big = BigInt(Math.trunc(Math.abs(n)));
    const key = [];
    if (big === 0n) key.push(0);
    while (big > 0n) {
      key.push(Number(big & 0xffffffffn));
      big >>= 32n;
    }
    const mt = this.mt;
    this._initGenrand(19650218);
    let i = 1;
    let j = 0;
    for (let k = Math.max(624, key.length); k; k--) {
      const prev = mt[i - 1] ^ (mt[i - 1] >>> 30);
      mt[i] = ((mt[i] ^ Math.imul(prev, 1664525)) + key[j] + j) >>> 0;
      i++;
      j++;
      if (i >= 624) {
        mt[0] = mt[623];
        i = 1;
      }
      if (j >= key.length) j = 0;
    }
    for (let k = 623; k; k--) {
      const prev = mt[i - 1] ^ (mt[i - 1] >>> 30);
      mt[i] = ((mt[i] ^ Math.imul(prev, 1566083941)) - i) >>> 0;
      i++;
      if (i >= 624) {
        mt[0] = mt[623];
        i = 1;
      }
    }
    mt[0] = 0x80000000;
    this.index = 624;
  }

  _uint32() {
    const mt = this.mt;
    if (this.index >= 624) {
      for (let kk = 0; kk < 624; kk++) {
        const y = (mt[kk] & 0x80000000) | (mt[(kk + 1) % 624] & 0x7fffffff);
        mt[kk] = mt[(kk + 397) % 624] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0);
      }
      this.index = 0;
    }
    let y = mt[this.index++];
    y ^= y >>> 11;
    y ^= (y << 7) & 0x9d2c5680;
    y ^= (y << 15) & 0xefc60000;
    y ^= y >>> 18;
    return y >>> 0;
  }

  random() {
    const a = this._uint32() >>> 5;
    const b = this._uint32() >>> 6;
    return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0);
  }

  getrandbits(k) {
    return this._uint32() >>> (32 - k);
  }

  randrange(n) {
    // _randbelow_with_getrandbits
    const k = Math.floor(Math.log2(n)) + 1;
    let r = this.getrandbits(k);
    while (r >= n) r = this.getrandbits(k);
    return r;
  }
}

export { sin, cos, acos, hypot, pyRound, pyFloorDiv, pyMod, f32, PyRandom };
