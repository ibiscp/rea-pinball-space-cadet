// Port of resources.py (minus pygame surfaces): the screen palette and the
// table's named sprite objects (origin / size / category), which table_data
// and the game look up by category.

import { BITMAP_TYPE } from './partout.js';

// FUN_010043b9 on a true-color display: entries 10..245 from PINBALL.DAT,
// the other 20 black, entry 255 white.
function screenPalette(dataPalette) {
  const colors = new Array(256).fill(null).map(() => [0, 0, 0]);
  for (let i = 10; i < 246; i++) colors[i] = dataPalette[i];
  colors[255] = [255, 255, 255];
  return colors;
}

// WinMain's gradient for the "hidden test" H strip (FUN_0100833a).
function debugStripPalette() {
  const colors = new Array(256).fill(null).map(() => [0, 0, 0]);
  for (let i = 0; i < 246; i++) {
    const ramp = 8 * i;
    const grey = (ramp <= 0xff ? ramp : i) & 0xff;
    colors[10 + i] = [Math.min(ramp, 0xff), grey, grey];
  }
  return screenPalette(colors);
}

function categoryOf(name) {
  let i = name.length;
  while (i > 0 && name[i - 1] >= '0' && name[i - 1] <= '9') i -= 1;
  return name.slice(0, i) || name;
}

class SpriteObject {
  constructor(name, originX, originY, width, height) {
    this.name = name;
    this.category = categoryOf(name);
    this.origin_x = originX;
    this.origin_y = originY;
    this.width = width;
    this.height = height;
  }

  get center() {
    return [this.origin_x + this.width / 2.0, this.origin_y + this.height / 2.0];
  }
}

class TableResources {
  constructor(tableSize, objects, palette) {
    this.table_size = tableSize;
    this.objects = objects;
    this.palette = palette;
  }

  byCategory(prefix) {
    return [...this.objects.values()].filter((o) => o.category === prefix);
  }
}

function loadTableResources(pf) {
  const background = pf.find('background');
  let palette = new Array(256).fill(null).map(() => [0, 0, 0]);
  if (background !== null) {
    const v = background.variants.find((x) => x.type_tag === 5);
    if (v) palette = screenPalette(v.decoded);
  }
  const sizeEntry = pf.find('table_size');
  const tableSize = sizeEntry ? sizeEntry.variants[sizeEntry.variants.length - 1].decoded : [600, 416];
  const objects = new Map();
  for (const entry of pf.entries) {
    const name = entry.name;
    if (!name) continue;
    const bv = entry.variants.find((v) => v.type_tag === BITMAP_TYPE);
    if (!bv) continue;
    if (name === 'table' || name === 'background') continue;
    const b = bv.decoded;
    objects.set(name, new SpriteObject(name, b.origin_x, b.origin_y, b.width, b.height));
  }
  return new TableResources([Math.trunc(tableSize[0]), Math.trunc(tableSize[1])], objects, palette);
}

export { screenPalette, debugStripPalette, SpriteObject, TableResources, loadTableResources };
