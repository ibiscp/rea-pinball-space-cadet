// Port of menu.py: the original's menu (MENU_1) and the modal "High
// Scores" (DLG_HIGHSCORES) and "Player Controls" (KEYMAPPER) dialogs. Item
// ids, captions, accelerators and controls are the original's resources;
// the look is the Windows UI of the day, approximated (as in the Python
// port). Drawing uses a canvas 2D context; hit rectangles come from the
// last draw, as in the Python version.

import { DEFAULT_KEYS, keyList } from './controls.js';
import { ENTRIES, NAME_LIMIT, formatScore } from './highscores.js';
import { STRINGS } from './strings.js';

const MENU_HEIGHT = 20;
const FACE = '#c0c0c0';
const SHADOW = '#808080';
const HILITE = '#000080';
const TEXT = '#000000';
const GREY_TEXT = '#808080';
const WHITE = '#ffffff';
const FONT = '12px Tahoma, "MS Sans Serif", "Segoe UI", Arial, sans-serif';

const NEW_GAME = 101;
const ABOUT = 102;
const HIGH_SCORES = 103;
const EXIT = 105;
const SOUNDS = 201;
const MUSIC = 202;
const HELP_TOPICS = 301;
const LAUNCH_BALL = 401;
const PAUSE = 402;
const FULL_SCREEN = 403;
const DEMO = 404;
const PLAYER_CONTROLS = 406;
const PLAYERS_1 = 408;
const PLAYERS_4 = 411;

class Rect {
  constructor(x, y, w, h) {
    this.x = x;
    this.y = y;
    this.w = w;
    this.h = h;
  }

  contains(p) {
    return p[0] >= this.x && p[0] < this.x + this.w && p[1] >= this.y && p[1] < this.y + this.h;
  }

  get right() {
    return this.x + this.w;
  }

  get bottom() {
    return this.y + this.h;
  }
}

class Item {
  constructor(command, caption, accel = '', o = {}) {
    this.command = command;
    this.caption = caption;
    this.accel = accel;
    this.submenu = o.submenu ?? null;
    this.enabled = o.enabled ?? true;
    this.checked = false;
  }

  get separator() {
    return this.command === 0 && this.submenu === null;
  }
}

function sep() {
  return new Item(0, '');
}

function buildMenu() {
  const players = [0, 1, 2, 3].map((i) => new Item(PLAYERS_1 + i, `${i + 1} Player${i ? 's' : ''}`));
  return [
    ['Game', [
      new Item(NEW_GAME, 'New Game', 'F2'),
      new Item(LAUNCH_BALL, 'Launch Ball'),
      new Item(PAUSE, 'Pause/Resume Game', 'F3'),
      sep(),
      new Item(HIGH_SCORES, 'High Scores...'),
      new Item(DEMO, 'Demo'),
      new Item(EXIT, 'Exit'),
    ]],
    ['Options', [
      new Item(FULL_SCREEN, 'Full Screen', 'F4'),
      new Item(-1, 'Select Players', '', { submenu: players }),
      sep(),
      new Item(SOUNDS, 'Sounds'),
      new Item(MUSIC, 'Music'),
      sep(),
      new Item(PLAYER_CONTROLS, 'Player Controls...', 'F8'),
    ]],
    ['Help', [
      new Item(HELP_TOPICS, 'Help Topics', 'F1', { enabled: false }),
      sep(),
      new Item(ABOUT, 'About Pinball'),
    ]],
  ];
}

function textWidth(ctx, text) {
  ctx.font = FONT;
  return Math.ceil(ctx.measureText(text).width);
}

function drawText(ctx, text, x, y, color) {
  ctx.font = FONT;
  ctx.fillStyle = color;
  ctx.textBaseline = 'top';
  ctx.fillText(text, x, y);
}

function fillRect(ctx, color, x, y, w, h) {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
}

function strokeRect(ctx, color, x, y, w, h) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
}

class MenuBar {
  constructor(onCommand) {
    this.menus = buildMenu();
    this.on_command = onCommand;
    this.open_index = null;
    this.sub_open = false;
    this._title_rects = [];
    this._item_rects = [];
    this._sub_rects = [];
    this.mouse = [-1, -1];
  }

  get is_open() {
    return this.open_index !== null;
  }

  item(command) {
    for (const [, items] of this.menus) {
      for (const it of items) {
        if (it.command === command) return it;
        for (const sub of it.submenu || []) if (sub.command === command) return sub;
      }
    }
    return null;
  }

  set(command, { enabled = null, checked = null } = {}) {
    const it = this.item(command);
    if (it === null) return;
    if (enabled !== null) it.enabled = enabled;
    if (checked !== null) it.checked = checked;
  }

  close() {
    this.open_index = null;
    this.sub_open = false;
  }

  click(pos) {
    for (let i = 0; i < this._title_rects.length; i++) {
      if (this._title_rects[i].contains(pos)) {
        this.open_index = this.open_index === i ? null : i;
        this.sub_open = false;
        return true;
      }
    }
    if (this.open_index === null) return false;
    for (const [rect, it] of [...this._sub_rects, ...this._item_rects]) {
      if (rect.contains(pos)) {
        if (it.submenu !== null) {
          this.sub_open = true;
          return true;
        }
        if (it.separator || !it.enabled) return true;
        this.close();
        this.on_command(it.command);
        return true;
      }
    }
    this.close();
    return true;
  }

  hover(pos) {
    this.mouse = pos;
    if (this.open_index === null) return;
    this._title_rects.forEach((rect, i) => {
      if (rect.contains(pos) && i !== this.open_index) {
        this.open_index = i;
        this.sub_open = false;
      }
    });
    for (const [rect, it] of this._item_rects) if (rect.contains(pos)) this.sub_open = it.submenu !== null;
  }

  draw(ctx, width) {
    fillRect(ctx, FACE, 0, 0, width, MENU_HEIGHT);
    this._title_rects = [];
    let x = 6;
    this.menus.forEach(([title], i) => {
      const w = textWidth(ctx, title);
      const rect = new Rect(x - 4, 1, w + 8, MENU_HEIGHT - 2);
      let color = TEXT;
      if (i === this.open_index) {
        fillRect(ctx, HILITE, rect.x, rect.y, rect.w, rect.h);
        color = WHITE;
      }
      drawText(ctx, title, x, 4, color);
      this._title_rects.push(rect);
      x += w + 14;
    });
    this._item_rects = [];
    this._sub_rects = [];
    if (this.open_index === null) return;
    const anchor = this._title_rects[this.open_index];
    const items = this.menus[this.open_index][1];
    const box = this._drawList(ctx, items, anchor.x, MENU_HEIGHT, this._item_rects);
    if (this.sub_open) {
      const parent = this._item_rects.find(([, it]) => it.submenu !== null);
      if (parent) this._drawList(ctx, parent[1].submenu, box.right - 2, parent[0].y - 3, this._sub_rects);
    }
  }

  _drawList(ctx, items, x, y, rects) {
    const row = 18;
    const widths = items.map((it) => textWidth(ctx, it.caption) + (it.accel ? textWidth(ctx, it.accel) + 30 : 0));
    const width = Math.max(...widths) + 50;
    const height = items.reduce((s, it) => s + (it.separator ? 6 : row), 0) + 6;
    const box = new Rect(x, y, width, height);
    fillRect(ctx, FACE, x, y, width, height);
    strokeRect(ctx, SHADOW, x, y, width, height);
    let cy = y + 3;
    for (const it of items) {
      if (it.separator) {
        fillRect(ctx, SHADOW, x + 3, cy + 3, width - 7, 1);
        cy += 6;
        continue;
      }
      const rect = new Rect(x + 3, cy, width - 6, row);
      const hot = rect.contains(this.mouse) && it.enabled;
      if (hot) fillRect(ctx, HILITE, rect.x, rect.y, rect.w, rect.h);
      const colour = hot ? WHITE : it.enabled ? TEXT : GREY_TEXT;
      if (it.checked) {
        ctx.strokeStyle = colour;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x + 7, cy + 9);
        ctx.lineTo(x + 10, cy + 12);
        ctx.lineTo(x + 15, cy + 5);
        ctx.stroke();
      }
      drawText(ctx, it.caption, x + 20, cy + 3, colour);
      if (it.accel) drawText(ctx, it.accel, x + width - textWidth(ctx, it.accel) - 14, cy + 3, colour);
      if (it.submenu !== null) drawText(ctx, '>', x + width - 14, cy + 3, colour);
      rects.push([rect, it]);
      cy += row;
    }
    return box;
  }
}

function button(ctx, label, rect) {
  fillRect(ctx, FACE, rect.x, rect.y, rect.w, rect.h);
  strokeRect(ctx, SHADOW, rect.x, rect.y, rect.w, rect.h);
  const w = textWidth(ctx, label);
  drawText(ctx, label, rect.x + Math.floor((rect.w - w) / 2), rect.y + Math.floor((rect.h - 13) / 2), TEXT);
}

function titleBar(ctx, text, x, y, w) {
  fillRect(ctx, HILITE, x + 2, y + 2, w - 4, 18);
  drawText(ctx, text, x + 8, y + 5, WHITE);
}

// Key events reaching a dialog: { vk, char } (vk = Windows virtual key).
const VK_RETURN = 0x0d;
const VK_ESCAPE = 0x1b;
const VK_BACK = 0x08;
const VK_SPACE = 0x20;
const VK_UP = 0x26;
const VK_DOWN = 0x28;

class HighScoreDialog {
  constructor(table, o = {}) {
    this.table = table;
    this.score = o.score ?? null;
    this.rank = o.rank ?? -1;
    this.name = o.name ?? '';
    this.confirming = false;
    this.done = false;
    this._buttons = new Map();
  }

  get entering() {
    return this.score !== null && this.rank >= 0;
  }

  rows() {
    const rows = [];
    let inserted = 0;
    for (let i = 0; i < ENTRIES; i++) {
      if (this.entering && this.rank === i) {
        rows.push([this.name, formatScore(this.score)]);
        inserted = 1;
      }
      if (i + inserted < ENTRIES) {
        const entry = this.table.entries[i];
        rows.push([entry.name, formatScore(entry.score)]);
      }
    }
    return rows.slice(0, ENTRIES);
  }

  key(ev) {
    if (this.confirming) {
      if (ev.vk === VK_RETURN) this._clearConfirmed();
      else if (ev.vk === VK_ESCAPE) this.confirming = false;
      return;
    }
    if (ev.vk === VK_RETURN) this.ok();
    else if (ev.vk === VK_ESCAPE) this.done = true;
    else if (this.entering && ev.vk === VK_BACK) this.name = this.name.slice(0, -1);
    else if (this.entering && ev.char && ev.char.length === 1 && ev.char >= ' ' && this.name.length < NAME_LIMIT) {
      this.name += ev.char;
    }
  }

  click(pos) {
    for (const [label, rect] of this._buttons) {
      if (!rect.contains(pos)) continue;
      if (label === 'OK') {
        if (this.confirming) this._clearConfirmed();
        else this.ok();
      } else if (label === 'Cancel') {
        if (this.confirming) this.confirming = false;
        else this.done = true;
      } else if (label === 'Clear') {
        this.confirming = true;
      }
      return;
    }
  }

  ok() {
    if (this.entering) this.table.insert(this.score, this.name, this.rank);
    this.done = true;
  }

  _clearConfirmed() {
    this.confirming = false;
    this.table.clear();
    if (!this.entering) this.done = true;
  }

  draw(ctx, width, height) {
    const w = 420;
    const h = 230;
    const x = Math.floor((width - w) / 2);
    const y = Math.floor((height - h) / 2);
    fillRect(ctx, FACE, x, y, w, h);
    strokeRect(ctx, SHADOW, x, y, w, h);
    titleBar(ctx, 'High Scores', x, y, w);
    const top = y + 30;
    drawText(ctx, 'Rank', x + 18, top, TEXT);
    drawText(ctx, 'Name', x + 70, top, TEXT);
    drawText(ctx, 'Score', x + 300, top, TEXT);
    this.rows().forEach(([name, score], i) => {
      const ry = top + 26 + i * 24;
      drawText(ctx, String(i + 1), x + 26, ry, TEXT);
      if (this.entering && i === this.rank) {
        fillRect(ctx, WHITE, x + 66, ry - 3, 190, 20);
        strokeRect(ctx, SHADOW, x + 66, ry - 3, 190, 20);
        drawText(ctx, `${name}|`, x + 70, ry, TEXT);
      } else {
        drawText(ctx, name, x + 70, ry, TEXT);
      }
      drawText(ctx, score, x + 390 - textWidth(ctx, score), ry, TEXT);
    });
    this._buttons = new Map();
    ['OK', 'Cancel', 'Clear'].forEach((label, j) => {
      const rect = new Rect(x + 150 + j * 90, y + h - 34, 80, 24);
      button(ctx, label, rect);
      this._buttons.set(label, rect);
    });
    if (this.confirming) {
      const cw = 220;
      const ch = 90;
      const cx = Math.floor((width - cw) / 2);
      const cy = Math.floor((height - ch) / 2);
      fillRect(ctx, FACE, cx, cy, cw, ch);
      strokeRect(ctx, SHADOW, cx, cy, cw, ch);
      titleBar(ctx, STRINGS.get(41), cx, cy, cw);
      drawText(ctx, STRINGS.get(40), cx + 20, cy + 34, TEXT);
      this._buttons = new Map();
      ['OK', 'Cancel'].forEach((label, j) => {
        const rect = new Rect(cx + 30 + j * 90, cy + ch - 30, 70, 22);
        button(ctx, label, rect);
        this._buttons.set(label, rect);
      });
    }
  }
}

const DLU_X = 1.5;
const DLU_Y = 1.625;
const KEYMAPPER_SIZE = [284, 183];
const KEYMAPPER_STATICS = [
  ['Instructions', [7, 5, 269, 61], 'group'],
  ['To change game controls, choose the control options you want, click the Arrow buttons to change specific keys, '
    + 'and then choose OK.', [14, 17, 249, 18], 'text'],
  ['To restore 3D Pinball to its original settings, choose Default, and then choose OK. To use the Arrow keys on the '
    + 'numeric keypad, make sure NUMLOCK is off.', [14, 38, 256, 25], 'text'],
  ['Control Options', [7, 71, 269, 87], 'group'],
  ['Left Flipper', [20, 87, 39, 10], 'text'],
  ['Right Flipper', [146, 87, 44, 10], 'text'],
  ['Left Table Bump', [20, 107, 34, 17], 'text'],
  ['Right Table Bump', [146, 107, 38, 19], 'text'],
  ['BottomTable Bump', [20, 131, 41, 18], 'text'],
  ['Plunger', [146, 136, 39, 8], 'text'],
];
const KEYMAPPER_COMBOS = [[66, 85, 53, 70], [192, 85, 53, 70], [192, 133, 53, 70], [66, 108, 53, 70],
  [192, 108, 53, 70], [66, 133, 53, 70]];
const KEYMAPPER_BUTTONS = [['OK', [119, 163, 50, 14]], ['Cancel', [173, 163, 50, 14]], ['Default', [227, 163, 50, 14]]];

class KeyMapperDialog {
  constructor(keys, onOk) {
    this.keys = keys;
    this.on_ok = onOk;
    this.done = false;
    this.warning = false;
    this.open_combo = null;
    this.scroll = 0;
    this._choices = keyList();
    this._selected = keys.map((vk) => this._indexOf(vk));
    this._rects = new Map();
    this._list_rects = [];
  }

  _indexOf(vk) {
    return this._choices.findIndex(([code]) => code === vk);
  }

  key(ev) {
    if (this.warning) {
      if ([VK_RETURN, VK_ESCAPE, VK_SPACE].includes(ev.vk)) this.warning = false;
      return;
    }
    if (this.open_combo !== null) {
      const sel = this._selected[this.open_combo];
      if (ev.vk === VK_UP) this._selected[this.open_combo] = Math.max(0, sel - 1);
      else if (ev.vk === VK_DOWN) this._selected[this.open_combo] = Math.min(this._choices.length - 1, sel + 1);
      else if (ev.vk === VK_RETURN || ev.vk === VK_ESCAPE) this.open_combo = null;
      return;
    }
    if (ev.vk === VK_RETURN) this.ok();
    else if (ev.vk === VK_ESCAPE) this.done = true;
  }

  wheel(dy) {
    if (this.open_combo !== null) this.scroll = Math.max(0, Math.min(this._choices.length - 7, this.scroll - dy));
  }

  click(pos) {
    if (this.warning) {
      const rect = this._rects.get('warning_ok');
      if (rect !== undefined && rect.contains(pos)) this.warning = false;
      return;
    }
    if (this.open_combo !== null) {
      for (const [rect, index] of this._list_rects) {
        if (rect.contains(pos)) {
          this._selected[this.open_combo] = index;
          break;
        }
      }
      this.open_combo = null;
      return;
    }
    for (const [name, rect] of this._rects) {
      if (!rect.contains(pos)) continue;
      if (name.startsWith('combo')) {
        this.open_combo = Number(name.slice(5));
        const sel = Math.max(0, this._selected[this.open_combo]);
        this.scroll = Math.max(0, Math.min(this._choices.length - 7, sel - 3));
      } else if (name === 'OK') {
        this.ok();
      } else if (name === 'Cancel') {
        this.done = true;
      } else if (name === 'Default') {
        this._selected = DEFAULT_KEYS.map((vk) => this._indexOf(vk));
      }
      return;
    }
  }

  ok() {
    const chosen = this._selected.map((i) => (i >= 0 ? this._choices[i][0] : 0));
    if (new Set(chosen).size < chosen.length) {
      this.warning = true;
      return;
    }
    this.on_ok(chosen);
    this.done = true;
  }

  draw(ctx, width, height) {
    const w = Math.trunc(KEYMAPPER_SIZE[0] * DLU_X);
    const h = Math.trunc(KEYMAPPER_SIZE[1] * DLU_Y) + 20;
    const x0 = Math.floor((width - w) / 2);
    const y0 = Math.floor((height - h) / 2);
    fillRect(ctx, FACE, x0, y0, w, h);
    strokeRect(ctx, SHADOW, x0, y0, w, h);
    titleBar(ctx, '3D Pinball: Player Controls', x0, y0, w);
    const top = y0 + 20;
    const rect = ([bx, by, bw, bh]) => new Rect(x0 + Math.round(bx * DLU_X), top + Math.round(by * DLU_Y),
      Math.round(bw * DLU_X), Math.round(bh * DLU_Y));
    for (const [caption, box, kind] of KEYMAPPER_STATICS) {
      const r = rect(box);
      if (kind === 'group') {
        strokeRect(ctx, SHADOW, r.x, r.y, r.w, r.h);
        const lw = textWidth(ctx, caption);
        fillRect(ctx, FACE, r.x + 6, r.y - 6, lw + 4, 12);
        drawText(ctx, caption, r.x + 8, r.y - 6, TEXT);
      } else {
        this._wrap(ctx, caption, r);
      }
    }
    this._rects = new Map();
    KEYMAPPER_COMBOS.forEach((box, i) => {
      const r = rect([box[0], box[1], box[2], 12]);
      fillRect(ctx, WHITE, r.x, r.y, r.w, r.h);
      strokeRect(ctx, SHADOW, r.x, r.y, r.w, r.h);
      const sel = this._selected[i];
      if (sel >= 0) drawText(ctx, this._choices[sel][1], r.x + 3, r.y + 3, TEXT);
      fillRect(ctx, FACE, r.right - 16, r.y + 1, 15, r.h - 2);
      ctx.fillStyle = TEXT;
      ctx.beginPath();
      ctx.moveTo(r.right - 12, r.y + 8);
      ctx.lineTo(r.right - 5, r.y + 8);
      ctx.lineTo(r.right - 9, r.y + 12);
      ctx.fill();
      this._rects.set(`combo${i}`, r);
    });
    for (const [label, box] of KEYMAPPER_BUTTONS) {
      const r = rect(box);
      button(ctx, label, r);
      this._rects.set(label, r);
    }
    this._list_rects = [];
    if (this.open_combo !== null) {
      const anchor = this._rects.get(`combo${this.open_combo}`);
      const rows = Math.min(7, this._choices.length);
      const rowH = anchor.h;
      const box = new Rect(anchor.x, anchor.bottom, anchor.w, rows * rowH + 2);
      fillRect(ctx, WHITE, box.x, box.y, box.w, box.h);
      strokeRect(ctx, TEXT, box.x, box.y, box.w, box.h);
      for (let k = 0; k < rows; k++) {
        const index = this.scroll + k;
        if (index >= this._choices.length) break;
        const r = new Rect(box.x + 1, box.y + 1 + k * rowH, box.w - 2, rowH);
        const hot = index === this._selected[this.open_combo];
        if (hot) fillRect(ctx, HILITE, r.x, r.y, r.w, r.h);
        drawText(ctx, this._choices[index][1], r.x + 2, r.y + 3, hot ? WHITE : TEXT);
        this._list_rects.push([r, index]);
      }
    }
    if (this.warning) this._drawWarning(ctx, width, height);
  }

  _wrap(ctx, text, r) {
    let line = '';
    let y = r.y;
    for (const word of text.split(/\s+/)) {
      const trial = `${line} ${word}`.trim();
      if (textWidth(ctx, trial) > r.w && line) {
        drawText(ctx, line, r.x, y, TEXT);
        y += 14;
        line = word;
      } else {
        line = trial;
      }
    }
    if (line) drawText(ctx, line, r.x, y, TEXT);
  }

  _drawWarning(ctx, width, height) {
    const lines = STRINGS.get(39).split('\n');
    const cw = Math.max(...lines.map((t) => textWidth(ctx, t))) + 40;
    const ch = 30 + 18 * lines.length + 40;
    const cx = Math.floor((width - cw) / 2);
    const cy = Math.floor((height - ch) / 2);
    fillRect(ctx, FACE, cx, cy, cw, ch);
    strokeRect(ctx, SHADOW, cx, cy, cw, ch);
    titleBar(ctx, STRINGS.get(43), cx, cy, cw);
    lines.forEach((t, i) => drawText(ctx, t, cx + 20, cy + 30 + 18 * i, TEXT));
    const r = new Rect(cx + Math.floor(cw / 2) - 35, cy + ch - 30, 70, 22);
    button(ctx, 'OK', r);
    this._rects.set('warning_ok', r);
  }
}

function drawAbout(ctx, width, height) {
  const lines = ['3D-Pinball for Windows', 'Version 1.0', '', ...STRINGS.get(101).split('\n'), '', 'OK'];
  const w = Math.max(...lines.map((line) => textWidth(ctx, line))) + 40;
  const h = 22 * lines.length + 20;
  const x = Math.floor((width - w) / 2);
  const y = Math.floor((height - h) / 2);
  fillRect(ctx, FACE, x, y, w, h);
  strokeRect(ctx, SHADOW, x, y, w, h);
  lines.forEach((line, i) => drawText(ctx, line, x + Math.floor((w - textWidth(ctx, line)) / 2), y + 10 + 22 * i, TEXT));
}

export {
  MenuBar, HighScoreDialog, KeyMapperDialog, drawAbout, MENU_HEIGHT, NEW_GAME, ABOUT, HIGH_SCORES, EXIT, SOUNDS, MUSIC,
  LAUNCH_BALL, PAUSE, FULL_SCREEN, DEMO, PLAYER_CONTROLS, PLAYERS_1, PLAYERS_4,
};
