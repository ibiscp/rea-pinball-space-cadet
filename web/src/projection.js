// Port of projection.py: the original's world -> screen camera
// (camera_info + the table's tag-700 centre; FUN_01008f03).

import { BITMAP_TYPE, floatArrays, taggedFloats } from './partout.js';
import { Vec2 } from './vec2.js';

class Camera {
  constructor(o) {
    this.matrix = o.matrix;
    this.d = o.d;
    this.center_x = o.center_x;
    this.center_y = o.center_y;
    this.offset_x = o.offset_x ?? 0.0;
    this.offset_y = o.offset_y ?? 0.0;
    this.identity = o.identity ?? false;
  }

  withOffset(x, y) {
    return new Camera({ ...this, offset_x: x, offset_y: y });
  }

  _view(x, y, z) {
    const m = this.matrix;
    return [
      m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
      m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
      m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
    ];
  }

  toScreen(p, z = 0.0) {
    if (this.identity) return new Vec2(p.x, p.y);
    const [vx, vy, vz] = this._view(p.x, p.y, z);
    const k = vz !== 0 ? this.d / vz : 999999.875;
    return new Vec2(vx * k + this.center_x + this.offset_x, vy * k + this.center_y + this.offset_y);
  }

  pxPerUnit(p, z = 0.0) {
    if (this.identity) return 1.0;
    return Math.abs(this.d / this._view(p.x, p.y, z)[2]);
  }
}

function loadCamera(pf) {
  const cameraInfo = pf.find('camera_info');
  const table = pf.find('table');
  if (cameraInfo === null || table === null) throw new Error('PINBALL.DAT has no camera_info/table entry');
  const cam = floatArrays(cameraInfo)[0];
  const center = taggedFloats(table, 700);
  const tableBitmap = table.variants.find((v) => v.type_tag === BITMAP_TYPE).decoded;
  if (center === null) throw new Error('table entry has no tag 700 projection centre');
  return new Camera({
    matrix: [cam.slice(0, 4), cam.slice(4, 8), cam.slice(8, 12)],
    d: cam[12],
    center_x: center[0],
    center_y: center[1],
    offset_x: tableBitmap.origin_x,
    offset_y: tableBitmap.origin_y,
  });
}

export { Camera, loadCamera };
