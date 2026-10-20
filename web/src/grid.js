// Port of grid.py: the original's 10 x 15 spatial grid (FUN_0100b883).
// Cells are keyed "col,row".

const COLUMNS = 10;
const ROWS = 15;

function cellKey(c, r) {
  return `${c},${r}`;
}

class Grid {
  constructor(x0, y0, width, height) {
    this.x0 = x0;
    this.y0 = y0;
    this.cell_w = width * 0.1;
    this.cell_h = height * 0.06666667;
    this.inv_w = 1.0 / this.cell_w;
    this.inv_h = 1.0 / this.cell_h;
  }

  col(x) {
    return Math.min(Math.max(Math.floor((x - this.x0) * this.inv_w), 0), COLUMNS - 1);
  }

  row(y) {
    return Math.min(Math.max(Math.floor((y - this.y0) * this.inv_h), 0), ROWS - 1);
  }

  cellOf(p) {
    return cellKey(this.col(p.x), this.row(p.y));
  }

  // FUN_0100be21: every cell whose closed rectangle overlaps the box.
  cellsInBox(minX, minY, maxX, maxY) {
    const mx = Math.trunc(this.cell_w * 0.001);
    const my = Math.trunc(this.cell_h * 0.001);
    const xLo = minX - mx;
    const xHi = mx + maxX;
    const yLo = minY - my;
    const yHi = my + maxY;
    const cells = new Set();
    for (let col = this.col(xLo); col < this.col(xHi) + 1; col++) {
      const left = col * this.cell_w + this.x0;
      for (let r = this.row(yLo); r < this.row(yHi) + 1; r++) {
        const top = r * this.cell_h + this.y0;
        if (left <= xHi && xLo <= left + this.cell_w && top <= yHi && yLo <= top + this.cell_h) {
          cells.add(cellKey(col, r));
        }
      }
    }
    return cells;
  }

  // FUN_0100b486's cell walk along the ray, as a list of keys.
  walk(origin, direction, length) {
    const out = [];
    const x0 = origin.x;
    const y0 = origin.y;
    const c0 = this.col(x0);
    const r0 = this.row(y0);
    const x1 = direction.x * length + x0;
    const y1 = direction.y * length + y0;
    const c1 = this.col(x1);
    const r1 = this.row(y1);
    const sx = x1 > x0 ? 1 : -1;
    const sy = y1 > y0 ? 1 : -1;
    const w = this.cell_w;
    const h = this.cell_h;
    const gx = this.x0;
    const gy = this.y0;
    if (r0 === r1) {
      if ((c1 - c0) * sx >= 0) for (let col = c0; col !== c1 + sx; col += sx) out.push(cellKey(col, r0));
      return out;
    }
    if (c0 === c1) {
      if ((r1 - r0) * sy >= 0) for (let r = r0; r !== r1 + sy; r += sy) out.push(cellKey(c0, r));
      return out;
    }
    const slope = (y0 - y1) / (x0 - x1);
    const intercept = y0 - slope * x0;
    out.push(cellKey(c0, r0));
    let col = c0;
    let r = r0;
    if (sx === 1) {
      let nextCol = c0 + 1;
      if (sy === 1) {
        let nextRow = r0 + 1;
        for (;;) {
          const yb = nextRow * h + gy;
          const yl = (nextCol * w + gx) * slope + intercept;
          if (yb <= yl) {
            if (yl === yb) {
              col += 1;
              nextCol += 1;
            }
            r += 1;
            nextRow += 1;
          } else {
            col += 1;
            nextCol += 1;
          }
          out.push(cellKey(col, r));
          if (!(col < c1 || r < r1)) return out;
        }
      }
      for (;;) {
        const yb = r * h + gy;
        const yl = (nextCol * w + gx) * slope + intercept;
        if (yl <= yb) {
          if (yl === yb) {
            col += 1;
            nextCol += 1;
          }
          r -= 1;
        } else {
          col += 1;
          nextCol += 1;
        }
        out.push(cellKey(col, r));
        if (!(col < c1 || r1 < r)) return out;
      }
    }
    if (sy === 1) {
      let nextRow = r0 + 1;
      for (;;) {
        const yb = nextRow * h + gy;
        const yl = (col * w + gx) * slope + intercept;
        if (yb <= yl) {
          if (yl === yb) col -= 1;
          r += 1;
          nextRow += 1;
        } else {
          col -= 1;
        }
        out.push(cellKey(col, r));
        if (!(c1 < col || r < r1)) return out;
      }
    }
    for (;;) {
      const yb = r * h + gy;
      const yl = (col * w + gx) * slope + intercept;
      if (yl <= yb) {
        if (yl === yb) col -= 1;
        r -= 1;
      } else {
        col -= 1;
      }
      out.push(cellKey(col, r));
      if (!(c1 < col || r1 < r)) return out;
    }
  }
}

export { Grid, cellKey };
