// Port of game.py: the score object and the control-table handlers
// ("listeners"), plus the text boxes, bumpers, bargraph, plunger and drain
// controls. Every handler follows the Python (and through it the decompiled
// code) line by line.

import { Sink, WallTarget } from './entities.js';
import { HighScores } from './highscores.js';
import { Bus, Light, LightGroup, Timers } from './logic.js';
import { Missions, RANKS } from './missions.js';
import { floatArrays, int16At, tag10, taggedFloats } from './partout.js';
import { pyFloorDiv, pyMod } from './pymath.js';
import { SCORES } from './scoring.js';
import { STRINGS } from './strings.js';

const LIGHT_TYPE = 0x3ea;
const LIGHT_GROUP_TYPE = 0x402;
const BUMPER_GROUP_TYPE = 0x404;
const BARGRAPH_TYPE = 0x406;
const MULTIPLIERS = [1, 2, 3, 5, 10];
const SCORE_CAP = 5000000;
const SERVE_DELAY = 0.96;
const NO_TIMER = 0;
const FOREVER = -1;

function spriteFramesAt(pf, index) {
  let frames = 1;
  for (const following of pf.entries.slice(index + 1)) {
    const marker = following.variants.find((v) => v.type_tag === 0);
    if (!marker || int16At(marker.raw) !== 201) break;
    frames += 1;
  }
  return frames;
}

// PINBALL.DAT entry index -> wav file name for every sound entry.
function soundFiles(pf) {
  const files = new Map();
  pf.entries.forEach((entry, index) => {
    const marker = entry.variants.find((v) => v.type_tag === 0);
    const path = entry.variants.find((v) => v.type_tag === 9);
    if (!marker || !path || int16At(marker.raw) !== 202) return;
    files.set(index, path.decoded);
  });
  return files;
}

// Python's "%d / %s" formatting of a message.
function pyFormat(message, args) {
  if (!args.length) return message;
  let k = 0;
  return message.replace(/%(%|ld|d|i|s)/g, (m, kind) => {
    if (kind === '%') return '%';
    const v = args[k++];
    return kind === 's' ? String(v) : String(Math.trunc(Number(v)));
  });
}

class Bargraph extends LightGroup {
  constructor(name, timers, bus, lights, o = {}) {
    super(name, timers, bus, lights, o);
    this.step_times = o.step_times ?? [];
    this.level = 0;
    this._decay = 0;
  }

  message(code, value = 0.0) {
    if (code === 0x25) return this.level;
    if (code === 0x2d) {
      if (this._decay) {
        this.timers.cancel(this._decay);
        this._decay = 0;
      }
      const level = Math.min(Math.floor(value), this.lights.length * 2 - 1);
      if (level < 0) {
        super.message(0x14);
        this.level = 0;
      } else {
        super.message(0x2d, pyFloorDiv(level, 2));
        if (pyMod(level, 2) === 0) super.message(0x2e);
        if (this.step_times.length) this._decay = this.timers.schedule(this.step_times[level], () => this._decayStep());
        this.level = level;
      }
      return 0;
    }
    if (code === 0x3f3) {
      this.reset();
      return 0;
    }
    if (code === 0x400) {
      this.reset();
      return super.message(0x400);
    }
    return super.message(code, value);
  }

  reset() {
    if (this._decay) {
      this.timers.cancel(this._decay);
      this._decay = 0;
    }
    this.level = 0;
    super.reset();
  }

  _decayStep() {
    this._decay = 0;
    if (this.level) {
      this.message(0x2d, this.level - 1);
      this.bus.notify(0x3c, this);
    } else {
      this.message(0x14);
      this.bus.notify(0x2f, this);
    }
  }
}

class Bumper {
  constructor(name, frames, bus) {
    this.name = name;
    this.frames = frames;
    this.bus = bus;
    this.level = 0;
    this.data = 0;
    this.lit_frame = false;
    this.on_sound = null;
    this.on_flash = null;
  }

  get frame() {
    return this.level * 2 + (this.lit_frame ? 1 : 0);
  }

  message(code, value = 0.0) {
    const top = pyFloorDiv(this.frames - 1, 2);
    if (code === 0xb) {
      let level = Math.floor(value);
      if (this.frames - 1 < level * 2) level = top;
      level = Math.max(level, 0);
      if (level !== this.level) {
        if (this.on_sound) this.on_sound(this.level <= level ? 'up' : 'down');
        this.level = level;
        if (this.on_flash) this.on_flash(this);
        this.bus.notify(0xb, this);
      }
    } else if (code === 0xc) {
      this.message(0xb, Math.min(this.level + 1, top));
    } else if (code === 0xd) {
      this.message(0xb, Math.max(this.level - 1, 0));
    } else if (code === 0x400) {
      this.level = 0;
      this.data = 0;
      this.lit_frame = false;
    }
    return 0;
  }
}

class BumperGroup {
  constructor(name, timers, bus, members) {
    this.name = name;
    this.timers = timers;
    this.bus = bus;
    this.members = members;
    this.data = 0;
    this._timer = 0;
  }

  message(code, value = 0.0) {
    if (code === 0x30) {
      if (this._timer) {
        this.timers.cancel(this._timer);
        this._timer = 0;
      }
      if (value > 0.0) this._timer = this.timers.schedule(value, () => this._expire());
    } else if (code < 0x3f0 || (code > 0x3f3 && code !== 0x3fc && code !== 0x3fe)) {
      for (let i = this.members.length - 1; i >= 0; i--) this.members[i].message(code, value);
    }
    return 0;
  }

  _expire() {
    this._timer = 0;
    this.bus.notify(0x3d, this);
  }

  get level() {
    return this.members.length ? this.members[0].level : 0;
  }
}

class PlungerControl {
  constructor(name, timers, bus, serve, sound = null) {
    this.name = name;
    this.timers = timers;
    this.bus = bus;
    this.serve = serve;
    this.sound = sound;
    this.data = 0;
    this._timer = 0;
  }

  message(code, value = 0.0) {
    if (code === 0x3f8) {
      if (this._timer) this.timers.cancel(this._timer);
      this._timer = this.timers.schedule(SERVE_DELAY, () => this.message(0x3f7));
      if (this.sound) this.sound();
      this.bus.notify(0x3f8, this);
    } else if (code === 0x3f7) {
      this._timer = 0;
      this.serve();
      this.bus.notify(0x3f7, this);
    } else if (code === 0x400) {
      if (this._timer) this.timers.cancel(this._timer);
      this._timer = 0;
    }
    return 0;
  }
}

class DrainControl {
  constructor(name, timers, bus, delay) {
    this.name = name;
    this.timers = timers;
    this.bus = bus;
    this.delay = delay;
    this.data = 0;
    this._timer = 0;
  }

  hit() {
    this._timer = this.timers.schedule(this.delay, () => this._expire());
    this.bus.notify(0x3f, this);
  }

  _expire() {
    this._timer = 0;
    this.bus.notify(0x3c, this);
  }

  message(code, value = 0.0) {
    if (code === 0x400 && this._timer) {
      this.timers.cancel(this._timer);
      this._timer = 0;
    }
    return 0;
  }
}

class PlayerRecord {
  constructor() {
    this.score = 0;
    this.billions = 0;
    this.jackpot = 0;
    this.balls = 0;
    this.extra_balls = 0;
    this.locked_balls = 0;
  }
}

const ord = (ch) => ch.charCodeAt(0);
const CODE_STEPS = new Map([
  [ord('M'), [4, 0x3d, 0x51, 0x65, 0x79]],
  [ord('D'), [0x16, 0x17]],
  [ord('A'), [5, 0x3e, 0x52, 0x66, 0x7a]],
  [ord('E'), [3, 0x18, 0x1c, 0x2c]],
  [ord('I'), [1, 10, 0x15]],
  [ord('S'), [0xc, 0x1d, 0x2d]],
  [ord('N'), [2, 9, 0x19]],
  [ord('O'), [8, 0x2a]],
  [ord('T'), [0x1b, 6, 0x2b]],
]);
const CODE_JUMPS = new Map([
  [ord(' '), [[0x1a, 0x1b]]],
  [ord('1'), [[0, 0x3d]]],
  [ord('B'), [[0, 0x51]]],
  [ord('C'), [[0, 1], [0xb, 0xc]]],
  [ord('G'), [[0, 0x65]]],
  [ord('H'), [[0, 0x15]]],
  [ord('Q'), [[0, 0x29]]],
  [ord('R'), [[0, 0x79], [7, 8]]],
  [ord('U'), [[0x29, 0x2a]]],
]);

class Message {
  constructor(text, seconds, expireMs) {
    this.text = text;
    this.seconds = seconds;
    this.expire_ms = expireMs;
  }
}

class TextBox {
  constructor(name, timers, bus) {
    this.name = name;
    this.timers = timers;
    this.bus = bus;
    this.data = 0;
    this.queue = [];
    this.shown = null;
    this._timer = NO_TIMER;
  }

  get now_ms() {
    return this.timers.now * 1000.0;
  }

  get message_text() {
    return this.shown;
  }

  _cancel() {
    if (this._timer !== NO_TIMER && this._timer !== FOREVER) this.timers.cancel(this._timer);
  }

  show(text, seconds) {
    if (text === null || text === undefined) return;
    if (this.queue.length && text === this.queue[this.queue.length - 1].text) {
      const tail = this.queue[this.queue.length - 1];
      tail.seconds = seconds;
      tail.expire_ms = this.now_ms + Math.trunc(seconds * 1000.0);
      if (tail !== this.queue[0]) return;
      this._cancel();
      this._timer = seconds !== -1.0 ? this.timers.schedule(seconds, () => this._expire()) : FOREVER;
      return;
    }
    if (this._timer === FOREVER) this.clear();
    this.queue.push(new Message(text, seconds, this.now_ms + Math.trunc(seconds * 1000.0)));
    if (this._timer === NO_TIMER) this._draw();
  }

  clear() {
    this.shown = null;
    this._cancel();
    this._timer = NO_TIMER;
    this.queue.length = 0;
  }

  _draw() {
    this.shown = null;
    while (this.queue.length) {
      const head = this.queue[0];
      if (head.seconds === -1.0) {
        if (this.queue.length === 1) {
          this._timer = FOREVER;
          this.shown = head.text;
          return;
        }
      } else {
        const remaining = (head.expire_ms - this.now_ms) * 0.001;
        if (remaining >= -2.0) {
          this._timer = this.timers.schedule(Math.max(remaining, 0.25), () => this._expire());
          this.shown = head.text;
          return;
        }
      }
      this.queue.shift();
    }
  }

  _expire() {
    this._timer = NO_TIMER;
    if (this.queue.length) {
      this.queue.shift();
      this._draw();
      this.bus.notify(0x3c, this);
    }
  }
}

class Named {
  constructor(name) {
    this.name = name;
  }
}

class Game extends Missions {
  constructor(pf, layout, playFile = null) {
    super();
    this.pf = pf;
    this.layout = layout;
    this.timers = new Timers();
    this.bus = new Bus();
    this.bus.mission = (code, obj) => this._mission(code, obj);
    this._play_file = playFile;
    this.sound_files = soundFiles(pf);
    this.objects = new Map();
    this.score = 0;
    this.score_billions = 0;
    this.multiplier = 0;
    this.score_offset = 0;
    this.reflex_value = 25000;
    this.bonus = 25000;
    this.bonus_on = 0;
    this.jackpot = 20000;
    this.jackpot_on = 0;
    this.balls = 3;
    this.extra_balls = 0;
    this.multiball_balls = 0;
    this.locked_balls = 0;
    this.multiball = 0;
    this.replay_balls = 0;
    this.tilted = 0;
    this.ball_lost = 0;
    this.ball_save_window = 0;
    this.rollover_bonus_lit = 0;
    this.balls_per_game = 3;
    this.player_count = 1;
    this.current_player = 0;
    this.player_number = 1;
    this.boxes = [0, -1, -1, -1];
    this.records = [new PlayerRecord(), new PlayerRecord(), new PlayerRecord(), new PlayerRecord()];
    this.cheated = 0;
    this.code_state = 0;
    this.debug_mode = 0;
    this.mode = 0;
    this.demo = 0;
    this.paused = 0;
    this._start_timer = 0;
    this._game_over_timer = 0;
    this._tilt_timer = 0;
    this.on_input = null;
    this.on_flipper_message = null;
    this.on_hide_ball = null;
    this.on_force_drain = null;
    this.on_broadcast = null;
    this.demo_player = null;
    this.high_scores = new HighScores();
    this.pending_entries = [];
    this.after_entries = null;
    this._slots = new Map();
    this.info_box = new TextBox('info_text_box', this.timers, this.bus);
    this.mission_box = new TextBox('mission_text_box', this.timers, this.bus);
    this.ball = null;
    this.on_serve = null;
    this._buildLights();
    this._buildBumpers();
    this._registerListeners();
  }

  _manifest() {
    const stream = tag10(this.pf.find('table_objects'));
    const out = [];
    for (let i = 1; i + 1 < stream.length; i += 2) out.push([stream[i], stream[i + 1]]);
    return out;
  }

  _buildLights() {
    const pf = this.pf;
    this.lights = new Map();
    this.groups = new Map();
    const byIndex = new Map();
    const manifest = this._manifest();
    for (const [typeId, index] of manifest) {
      if (typeId !== LIGHT_TYPE) continue;
      const entry = pf.entries[index];
      const on = taggedFloats(entry, 900);
      const off = taggedFloats(entry, 901);
      const light = new Light(entry.name, this.timers, this.bus, {
        frames: spriteFramesAt(pf, index),
        base_times: [on ? on[0] : 0.1, off ? off[0] : 0.1],
      });
      this.lights.set(entry.name, light);
      byIndex.set(index, light);
    }
    for (const [typeId, index] of manifest) {
      if (typeId !== LIGHT_GROUP_TYPE && typeId !== BARGRAPH_TYPE) continue;
      const entry = pf.entries[index];
      const stream = tag10(entry);
      const members = stream.length && stream[0] === 1027
        ? stream.slice(1).filter((i) => byIndex.has(i)).map((i) => byIndex.get(i)) : [];
      const interval = taggedFloats(entry, 903);
      let group;
      if (typeId === BARGRAPH_TYPE) {
        const times = taggedFloats(entry, 904);
        group = new Bargraph(entry.name, this.timers, this.bus, members, {
          interval: interval ? interval[0] : 0.1,
          step_times: times ? times.slice(0, members.length * 2) : [],
        });
      } else {
        group = new LightGroup(entry.name, this.timers, this.bus, members, { interval: interval ? interval[0] : 0.1 });
      }
      group.reset();
      this.groups.set(entry.name, group);
    }
    for (const [k, v] of this.lights) this.objects.set(k, v);
    for (const [k, v] of this.groups) this.objects.set(k, v);
    this.all_lights = new LightGroup('', this.timers, this.bus, [...this.lights.values()], { interval: 0.0 });
  }

  _buildBumpers() {
    const pf = this.pf;
    this.bumpers = new Map();
    const byIndex = new Map();
    const manifest = this._manifest();
    for (const [typeId, index] of manifest) {
      const entry = pf.entries[index];
      if (typeId === 0x3ed) {
        const bumper = new Bumper(entry.name, spriteFramesAt(pf, index), this.bus);
        bumper.on_sound = (which) => this._entrySound(entry, which === 'up' ? 1100 : 1101);
        bumper.on_flash = (b) => this._bumperFlash(b);
        this.bumpers.set(entry.name, bumper);
        byIndex.set(index, bumper);
      }
    }
    for (const [k, v] of this.bumpers) this.objects.set(k, v);
    for (const [typeId, index] of manifest) {
      if (typeId !== BUMPER_GROUP_TYPE) continue;
      const entry = pf.entries[index];
      const stream = tag10(entry);
      const members = stream.length && stream[0] === 1027
        ? stream.slice(1).filter((i) => byIndex.has(i)).map((i) => byIndex.get(i)) : [];
      this.objects.set(entry.name, new BumperGroup(entry.name, this.timers, this.bus, members));
    }
  }

  register(obj, soundTag = null) {
    this.objects.set(obj.name, obj);
    if ('notify' in obj) obj.notify = (code, o) => this.bus.notify(code, o);
    if (soundTag !== null && 'sound' in obj) {
      const ref = this.soundRef(obj.name, soundTag);
      obj.sound = ref !== null ? () => this.playEntry(ref) : null;
    }
  }

  soundRef(name, tag) {
    const entry = this.pf.find(name);
    if (entry === null) return null;
    const stream = tag10(entry);
    for (let i = 0; i < stream.length - 1; i += 2) if (stream[i] === tag) return stream[i + 1];
    if (tag === 406) {
      for (let i = 0; i < stream.length - 1; i += 2) {
        if (stream[i] !== 400) continue;
        const arrays = floatArrays(this.pf.entries[stream[i + 1]]);
        if (!arrays.length) return null;
        const values = arrays[0];
        let j = 0;
        while (j + 1 < values.length) {
          const key = Math.trunc(values[j]);
          if (key === 406) return Math.trunc(values[j + 1]);
          j += key === 404 ? 4 : 2;
        }
      }
    }
    return null;
  }

  playRef(name, tag) {
    const ref = this.soundRef(name, tag);
    return ref !== null ? this.playEntry(ref) : 0.0;
  }

  lit(name) {
    const obj = this.objects.get(name);
    return Boolean(obj !== undefined && obj.lit());
  }

  msg(name, code, value = 0.0) {
    const obj = this.objects.get(name);
    if (obj === undefined || typeof obj.message !== 'function') return 0;
    return obj.message(code, value) || 0;
  }

  data(name) {
    const obj = this.objects.get(name);
    return obj !== undefined && obj.data !== undefined ? obj.data : 0;
  }

  setData(name, value) {
    const obj = this.objects.get(name);
    if (obj !== undefined) obj.data = value;
  }

  static scoreOf(obj, index) {
    const scores = SCORES.get(obj && obj.name !== undefined ? obj.name : '') || [];
    return index >= 0 && index < scores.length ? scores[index] : 0;
  }

  scoreOf(obj, index) {
    return Game.scoreOf(obj, index);
  }

  addScore(points) {
    if (this.jackpot_on) this.jackpot = Math.min(this.jackpot + points, SCORE_CAP);
    if (this.bonus_on) this.bonus = Math.min(this.bonus + points, SCORE_CAP);
    const added = MULTIPLIERS[this.multiplier] * points + this.score_offset;
    this.score += added;
    if (this.score > 1000000000) {
      this.score_billions += 1;
      this.score -= 1000000000;
    }
    this.boxes[this.current_player] = this.score;
    return added;
  }

  award(points) {
    const saved = [this.jackpot_on, this.bonus_on, this.multiplier];
    this.jackpot_on = 0;
    this.bonus_on = 0;
    this.multiplier = 0;
    const added = this.addScore(points);
    [this.jackpot_on, this.bonus_on, this.multiplier] = saved;
    return added;
  }

  text(box, string, seconds, ...args) {
    let message = typeof string === 'number' ? (STRINGS.get(string) ?? '') : string;
    if (args.length) message = pyFormat(message.replaceAll('%ld', '%d'), args);
    (box === 'info' ? this.info_box : this.mission_box).show(message, seconds);
  }

  clearText(box) {
    (box === 'info' ? this.info_box : this.mission_box).clear();
  }

  get info_text() {
    return this.info_box.message_text;
  }

  get mission_text() {
    return this.mission_box.message_text;
  }

  play(wave) {
    const entry = this.pf.find(wave);
    if (entry === null) return 0.0;
    return this._entrySound(entry, 1100);
  }

  _entrySound(entry, tag) {
    const stream = tag10(entry);
    for (let i = 0; i < stream.length - 1; i += 2) if (stream[i] === tag) return this.playEntry(stream[i + 1]);
    return 0.0;
  }

  playEntry(index) {
    const name = this.sound_files.get(index);
    if (name === undefined) return 0.0;
    if (this._play_file !== null) return this._play_file(name);
    return 0.0;
  }

  update(dt) {
    this.timers.update(dt);
  }

  setupControls(serve, drainDelay) {
    this.objects.set('plunger', new PlungerControl('plunger', this.timers, this.bus, serve,
      () => this.playRef('plunger', 1100)));
    this.objects.set('drain', new DrainControl('drain', this.timers, this.bus, drainDelay));
  }

  drain() {
    this.ball_lost = 1;
    this.objects.get('drain').hit();
  }

  setMode(mode) {
    if (mode === 1 && this.demo_player !== null) this.demo_player.active = Boolean(this.demo);
    else if (mode === 2) this.all_lights.message(0x1d, 1.4);
    this.mode = mode;
  }

  newGame(demo, players) {
    this.demo = demo ? 1 : 0;
    this.setMode(1);
    this.scoreMessage(0x3f6, players);
  }

  toggleDemo(players) {
    if (this.demo) {
      this.demo = 0;
      this.scoreMessage(0x400);
      this.setMode(2);
      this.clearText('mission');
      this.text('info', 24, -1.0);
      return;
    }
    this.newGame(true, players);
  }

  togglePause() {
    this.paused = this.paused ? 0 : 1;
    this.clearText('info');
    this.clearText('mission');
    if (this.paused) {
      this.scoreMessage(0x3f0);
      this.text('info', 22, -1.0);
      return;
    }
    this.scoreMessage(0x3f1);
    if (!this.demo) {
      if (this.mode === 2) this.text('info', 24, -1.0);
      else this.text('info', 23, 5.0);
    }
  }

  focusLost() {
    this.scoreMessage(0x3f2);
  }

  broadcast(code, value = 0.0, forward = false) {
    const objects = [...this.objects.values()];
    if (!forward) objects.reverse();
    for (const obj of objects) {
      if (code === 0x3fc && this._swapPlayer(obj, Math.trunc(value))) continue;
      if (code === 0x400) this._clearPlayerSlots(obj);
      if (typeof obj.message === 'function') obj.message(code, value);
    }
    if (this.on_broadcast !== null) this.on_broadcast(code, value);
  }

  // FUN_010187d6.
  scoreMessage(code, value = 0.0) {
    if (code === 1000 || code === 0x3e9 || code === 0x3ea || code === 0x3eb) {
      if (!this.tilted && this.on_input !== null) this.on_input(code);
    } else if (code === 0x3ec || code === 0x3ed) {
      if (this.on_input !== null) this.on_input(code);
    } else if (code === 0x3f0 || code === 0x3f1 || code === 0x3f2) {
      this.broadcast(code, value);
    } else if (code === 0x3f4) {
      this.all_lights.message(0xe, 0.0);
      if (this.tilted) {
        this.tilted = 0;
        if (this._tilt_timer) this.timers.cancel(this._tilt_timer);
        this._tilt_timer = 0;
      }
    } else if (code === 0x3f5) {
      this.all_lights.message(0x22, 0.0);
      this.all_lights.message(0x14, 0.0);
      this.msg('plunger', 0x3f8);
      this.text('info', this.demo ? 30 : 26, -1.0);
      if (this.demo_player !== null) this.demo_player.message(0x3f6);
    } else if (code === 0x3f6) {
      this._newGame(value);
    } else if (code === 0x3fa) {
      // a timer nothing reads (FUN_010175ef)
    } else if (code === 0x3fd) {
      this._nextPlayer();
    } else if (code === 0x3fe) {
      this.playRef('table', 1101);
      this.clearText('mission');
      this.text('info', 34, -1.0);
      this._game_over_timer = this.timers.schedule(3.0, () => this._gameOverEnd());
    } else if (code === 0x400) {
      this.broadcast(0x400);
      if (this._start_timer) {
        this.timers.cancel(this._start_timer);
        this.all_lights.message(0x22, 0.0);
      }
      this._start_timer = 0;
      this.multiplier = 0;
      this.score_offset = 0;
      this.reflex_value = 0;
      this.bonus = 10000;
      this.bonus_on = 0;
      this.jackpot = 20000;
      this.jackpot_on = 0;
      this.extra_balls = 0;
      this.multiball_balls = 0;
      this.locked_balls = 0;
      this.multiball = 0;
      this.replay_balls = 0;
      this.tilted = 0;
    }
    if (code === 0x3f3) this._tiltSideEffect();
    return 0;
  }

  // FUN_0100e1b0.
  typeKey(vk) {
    if (this.data('lite198') !== 0) return;
    const state = this.code_state;
    if (vk === ord('X')) {
      if (state === 0x3f) this._extraBall(2.0);
      else if (state === 0x53) this.ball_save_window = 1;
      else if (state === 0x67) this._gravityWell(0x40, null);
      else if (state === 0x7b) this.cheatRank();
      else {
        this.code_state = 0;
        return;
      }
      this.cheated = 1;
      this.code_state = 0;
      return;
    }
    if (vk === ord('T') && state === 0x1e) {
      this.debug_mode = 1;
      this.cheated = 1;
      this.code_state = 0;
      return;
    }
    if ((CODE_STEPS.get(vk) || []).includes(state)) {
      this.code_state = state + 1;
      return;
    }
    for (const [need, nw] of CODE_JUMPS.get(vk) || []) {
      if (state === need) {
        this.code_state = nw;
        return;
      }
    }
    this.code_state = 0;
  }

  cheatRank() {
    const middle = this.objects.get('middle_circle');
    if (middle === undefined) return;
    const rank = middle.message(0x25);
    if (rank < 9) {
      middle.message(0x29, 2.0);
      this.text('mission', 83, 8.0, STRINGS.get(RANKS[rank]));
      this.play('soundwave10');
    }
  }

  flipperMessage(code) {
    if (this.on_flipper_message !== null) this.on_flipper_message(code);
  }

  _tiltSideEffect() {
    this.ball_save_window = 0;
    this.msg('lite77', 7);
  }

  _newGame(players) {
    if (this._game_over_timer) {
      this.timers.cancel(this._game_over_timer);
      this._gameOverEnd();
      this.setMode(1);
    }
    if (this._start_timer) {
      this.timers.cancel(this._start_timer);
      this._start_timer = 0;
      this.scoreMessage(0x3f5);
      return;
    }
    this.cheated = 0;
    this.scoreMessage(0x400);
    if (this.on_hide_ball !== null) this.on_hide_ball();
    this.player_count = Math.max(1, Math.min(4, Math.floor(players)));
    this.current_player = 0;
    this.score = 0;
    this.boxes[0] = 0;
    this.multiplier = 0;
    for (const record of this.records.slice(1, this.player_count)) {
      record.score = 0;
      record.billions = 0;
      record.balls = this.balls_per_game;
      record.extra_balls = this.extra_balls;
      record.locked_balls = this.locked_balls;
      record.jackpot = this.jackpot;
    }
    for (let i = 1; i < this.player_count; i++) this.boxes[i] = 0;
    this.balls = this.balls_per_game;
    this.player_number = 1;
    for (let i = this.player_count; i < 4; i++) this.boxes[i] = -1;
    this.jackpot_on = 0;
    this.bonus_on = 0;
    this.clearText('info');
    this.clearText('mission');
    this.all_lights.message(0x1c, 0.2);
    const length = this.playRef('table', 1100);
    this._start_timer = this.timers.schedule(length, () => this._start());
  }

  _start() {
    this._start_timer = 0;
    this.scoreMessage(0x3f5);
  }

  _nextPlayer() {
    if (this.player_count < 2) {
      this.text('info', this.demo ? 30 : 26, -1.0);
      return;
    }
    const nxt = pyMod(this.current_player + 1, this.player_count);
    if (this.records[nxt].balls <= 0) return;
    const mine = this.records[this.current_player];
    mine.score = this.score;
    mine.billions = this.score_billions;
    mine.balls = this.balls;
    mine.extra_balls = this.extra_balls;
    mine.locked_balls = this.locked_balls;
    mine.jackpot = this.jackpot;
    const theirs = this.records[nxt];
    this.score = theirs.score;
    this.score_billions = theirs.billions;
    this.balls = theirs.balls;
    this.extra_balls = theirs.extra_balls;
    this.locked_balls = theirs.locked_balls;
    this.jackpot = theirs.jackpot;
    this.boxes[nxt] = this.score;
    this.player_number = nxt + 1;
    this.broadcast(0x3fc, nxt, true);
    this.text('info', (this.demo ? 30 : 26) + nxt, -1.0);
    this.jackpot_on = 0;
    this.bonus_on = 0;
    this.current_player = nxt;
  }

  _gameOverEnd() {
    this._game_over_timer = 0;
    this._recordHighScores();
    if (this.pending_entries.length) {
      this.after_entries = () => this._gameOverFinish();
      return;
    }
    this._gameOverFinish();
  }

  _gameOverFinish() {
    this.after_entries = null;
    this.broadcast(0x3fe);
    if (this.demo_player !== null) this.demo_player.message(0x3fe);
    this.bus.notify(0x43, this.mission_box);
    this.text('info', 24, -1.0);
  }

  _recordHighScores() {
    this.setMode(2);
    const scores = [];
    for (let i = 0; i < this.player_count; i++) scores.push([this.boxes[i], i]);
    scores.sort((a, b) => (b[0] >>> 0) - (a[0] >>> 0));
    if (this.demo || this.cheated) return;
    for (const [score, player] of scores) {
      if (this.high_scores.rank(score) >= 0) this.pending_entries.push([score, STRINGS.get(26 + player)]);
    }
  }

  hasHighScore() {
    if (this.demo) return false;
    for (let i = this.player_count - 1; i >= 0; i--) if (this.high_scores.rank(this.boxes[i]) >= 0) return true;
    return false;
  }

  _playerSlots(obj) {
    let slots = this._slots.get(obj);
    if (slots === undefined) {
      let empty;
      if (obj instanceof Bargraph) empty = 0;
      else if (obj instanceof Light) empty = [0, 0, 0, 0];
      else if (obj instanceof LightGroup) empty = [0, 0, 0.0];
      else if (obj instanceof Bumper) empty = [0, 0];
      else empty = 0;
      slots = [empty, empty, empty, empty];
      this._slots.set(obj, slots);
    }
    return slots;
  }

  _swapPlayer(obj, nxt) {
    const cur = this.current_player;
    const slots = this._playerSlots(obj);
    if (obj instanceof Bargraph) {
      slots[cur] = obj.level;
      obj.reset();
      obj.level = slots[nxt];
      if (obj.level) obj.message(0x2d, obj.level);
      return true;
    }
    if (obj instanceof Light) {
      slots[cur] = [obj.flashing, obj.frame, obj.state, obj.data];
      obj.reset();
      [obj.flashing, obj.frame, obj.state, obj.data] = slots[nxt];
      if (obj.frame) obj.message(0xb, obj.frame);
      if (obj.state) obj.message(1);
      if (obj.flashing) obj.message(4);
      return true;
    }
    if (obj instanceof LightGroup) {
      slots[cur] = [obj.data, obj.animation, obj._step];
      obj.reset();
      [obj.data, obj.animation, obj._step] = slots[nxt];
      if (obj.data) obj._animate();
      return true;
    }
    if (obj instanceof Bumper) {
      slots[cur] = [obj.level, obj.data];
      [obj.level, obj.data] = slots[nxt];
      return true;
    }
    if (obj instanceof WallTarget && obj.drop_time === 0.0) {
      slots[cur] = obj.data;
      obj.data = slots[nxt];
      obj.message(obj.data ? 0x31 : 0x32);
      return true;
    }
    if (obj instanceof Sink) {
      slots[cur] = obj.data;
      obj.data = slots[nxt];
      return true;
    }
    return false;
  }

  _clearPlayerSlots(obj) {
    if (!(obj instanceof Light || obj instanceof LightGroup || obj instanceof Bumper || obj instanceof Sink)
      && !(obj instanceof WallTarget && obj.drop_time === 0.0)) return;
    const slots = this._playerSlots(obj);
    for (let i = 0; i < this.player_count; i++) {
      if (obj instanceof Bargraph) slots[i] = 0;
      else if (obj instanceof Light) slots[i] = [0, 0, 0, 0];
      else if (obj instanceof LightGroup) slots[i] = [obj.data, 0, obj.interval];
      else if (obj instanceof Bumper) slots[i] = [0, 0];
      else slots[i] = 0;
    }
  }

  bumperHit(name, lockout) {
    const bumper = this.bumpers.get(name);
    if (bumper === undefined) return;
    this.playRef(name, 406);
    this._bumperFlash(bumper, lockout);
    this.bus.notify(0x3f, bumper);
  }

  _bumperFlash(bumper, lockout = null) {
    const circle = this.layout.bumpers.find((ci) => ci.name === bumper.name) || null;
    if (lockout === null) {
      lockout = circle !== null ? circle.cooldown : 0.1;
      if (circle !== null) circle._cooldown_remaining = lockout;
    }
    bumper.lit_frame = true;
    this.timers.schedule(lockout, () => {
      bumper.lit_frame = false;
    });
  }

  flipper(name, pressed) {
    if (pressed) {
      this.bus.notify(1, new Named(name));
      this.playRef(name, 1100);
    } else {
      this.playRef(name, 1101);
    }
  }

  tilt() {
    if (this.tilted || this.ball_lost) return false;
    this.clearText('info');
    this.clearText('mission');
    this.text('info', 35, -1.0);
    this.playRef('table', 406);
    this._tilt_timer = this.timers.schedule(30.0, () => this._tiltExpired());
    this.scoreMessage(0x3f3, -1.0);
    this.broadcast(0x3f3, 0.0, true);
    this.all_lights.message(8, 0.0);
    this.tilted = 1;
    this._tiltSideEffect();
    return true;
  }

  _tiltExpired() {
    this._tilt_timer = 0;
    if (this.tilted && this.on_force_drain !== null) this.on_force_drain();
  }

  // -- the listeners --------------------------------------------------------
  _registerListeners() {
    const reg = this.bus.listeners;
    const on = (name, fn) => reg.set(name, fn);
    for (const name of ['a_bump1', 'a_bump2', 'a_bump3', 'a_bump4', 'a_bump5', 'a_bump6', 'a_bump7']) {
      on(name, (code, obj) => this._bumper(code, obj));
    }
    for (const name of ['a_roll1', 'a_roll2', 'a_roll3']) on(name, (code, obj) => this._attackRollover(code, obj));
    for (const name of ['a_roll110', 'a_roll111', 'a_roll112']) on(name, (code, obj) => this._launchRollover(code, obj));
    on('attack_bumpers', (code, obj) => this._bumperGroupDecay(code, obj));
    on('launch_bumpers', (code, obj) => this._bumperGroupDecay(code, obj));
    on('v_rebo1', (code, obj) => this._rebound(code, obj, 'lite84'));
    on('v_rebo2', (code, obj) => this._rebound(code, obj, 'lite85'));
    on('v_rebo3', (code, obj) => this._rebound(code, obj, null));
    on('v_rebo4', (code, obj) => this._rebound(code, obj, null));
    on('a_kick1', (code) => code === 0x3c && this.msg('v_gate1', 0x36));
    on('a_kick2', (code) => code === 0x3c && this.msg('v_gate2', 0x36));
    on('v_gate1', (code) => this._gate(code, 'lite30', 'lite196'));
    on('v_gate2', (code) => this._gate(code, 'lite29', 'lite195'));
    on('s_onewy4', (code, obj) => this._skillShot(code, obj));
    on('s_onewy10', (code) => code === 0x3f && this.msg('skill_shot_lights', 0x14));
    on('v_bloc1', (code, obj) => this._centerPost(code, obj));
    on('ramp', (code, obj) => this._ramp(code, obj));
    on('ramp_hole', (code) => code === 0x3a && this.msg('lite54', 7, 5.0));
    on('a_roll4', (code, obj) => this._outlane(code, obj));
    on('a_roll8', (code, obj) => this._outlane(code, obj));
    on('lite17', (code, obj) => this._lite17(code, obj));
    on('a_roll6', (code, obj) => this._inlane(code, obj));
    on('a_roll7', (code, obj) => this._inlane(code, obj));
    on('a_roll5', (code, obj) => this._fuelRollover(code, obj));
    ['a_roll179', 'a_roll180', 'a_roll181', 'a_roll182', 'a_roll183', 'a_roll184'].forEach((name, i) => {
      on(name, (code, obj) => this._fuelLane(code, obj, i));
    });
    on('a_flag1', (code, obj) => this._flag(code, obj));
    on('a_flag2', (code, obj) => this._flag(code, obj));
    on('a_kout2', (code, obj) => this._hyperspace(code, obj));
    on('hyperspace_lights', (code, obj) => this._decayingGroup(code, obj, 60.0));
    for (const name of ['v_sink1', 'v_sink2', 'v_sink3']) on(name, (code, obj) => this._wormhole(code, obj));
    on('a_flip1', (code) => code === 1 && this._laneChange(0x18));
    on('a_flip2', (code) => code === 1 && this._laneChange(0x19));
    on('plunger', (code, obj) => this._plunger(code, obj));
    for (const name of ['a_targ1', 'a_targ2', 'a_targ3']) on(name, (code, obj) => this._boosterTargets(code, obj));
    on('lite60', (code) => {
      if (code === 0x3c) this.jackpot_on = 0;
    });
    on('lite59', (code) => {
      if (code === 0x3c) this.bonus_on = 0;
    });
    for (const name of ['a_targ4', 'a_targ5', 'a_targ6']) on(name, (code, obj) => this._medalTargets(code, obj));
    on('bumper_target_lights', (code, obj) => this._decayingGroup(code, obj, 30.0));
    for (const name of ['a_targ7', 'a_targ8', 'a_targ9']) on(name, (code, obj) => this._multiplierTargets(code, obj));
    on('top_target_lights', (code, obj) => this._multiplierGroup(code, obj));
    for (const name of ['a_targ10', 'a_targ11', 'a_targ12']) on(name, (code, obj) => this._fuelTargets(code, obj));
    for (const name of ['a_targ13', 'a_targ14', 'a_targ15']) on(name, (code, obj) => this._missionTargets(code, obj));
    for (const name of ['a_targ16', 'a_targ17', 'a_targ18']) {
      on(name, (code, obj) => this._gateTargets(code, obj, ['a_targ16', 'a_targ17'], ['lite104', 'lite105', 'lite106'],
        'lchute_tgt_lights', 'v_gate1'));
    }
    for (const name of ['a_targ19', 'a_targ20', 'a_targ21']) {
      on(name, (code, obj) => this._gateTargets(code, obj, ['a_targ19', 'a_targ20'], ['lite107', 'lite108', 'lite109'],
        'bpr_solotgt_lights', 'v_gate2'));
    }
    on('a_targ22', (code, obj) => this._wormholeTarget(code, obj));
    on('a_roll9', (code) => {
      if (code === 0x3f) {
        this.msg('lite27', 0x13);
        this.msg('lite28', 0x13);
      }
    });
    on('a_kout3', (code, obj) => this._blackHole(code, obj));
    on('a_kout1', (code, obj) => this._gravityWell(code, obj));
    on('drain', (code, obj) => this._drain(code, obj));
    on('s_onewy1', (code, obj) => this._launchLane(code, obj));
    on('s_trip1', (code) => this._skillTrip(code, 'lite68'));
    on('s_trip2', (code) => this._skillTrip(code, 'lite69'));
    on('s_trip3', (code) => this._skillTrip(code, 'lite131'));
    on('s_trip4', (code) => this._skillTrip(code, 'lite132'));
    on('s_trip5', (code) => this._skillTrip(code, 'lite133'));
    on('lite200', (code, obj) => this._redeployLight(code, obj));
    on('v_sink7', (code, obj) => code === 0x3f && obj.message(0x38, obj.eject_delay));
  }

  _bumper(code, obj) {
    if (code === 0x3f) this.addScore(this.scoreOf(obj, obj.level));
  }

  _rolloverBank(obj, lights, names, bank, firstBumper, group, text) {
    let light;
    if (obj === this.objects.get(names[0])) light = lights[0];
    else if (obj === this.objects.get(names[1])) light = lights[1];
    else light = lights[2];
    const lamp = this.objects.get(light);
    if (!lamp.flashing) {
      if (!lamp.state) {
        lamp.message(0x13);
        if (this.msg(bank, 0x25) === this.msg(bank, 0x26)) {
          this.msg(bank, 7, 5.0);
          this.msg(bank, 0);
          if (this.bumpers.get(firstBumper).level < 3) {
            this.msg(group, 0xc);
            this.text('info', text, 2.0);
          }
          this.msg(group, 0x30, 60.0);
        }
      } else {
        lamp.message(0x14);
      }
    }
    this.addScore(this.scoreOf(obj, 0));
  }

  _attackRollover(code, obj) {
    if (code !== 0x3f) return;
    if (!this.lit('lite56') && this.msg('l_trek_lights', 0x27)) {
      for (const group of ['l_trek_lights', 'r_trek_lights']) {
        this.msg(group, 0x22);
        this.msg(group, 0x14);
      }
    }
    this._rolloverBank(obj, ['lite8', 'lite9', 'lite10'], ['a_roll3', 'a_roll2'], 'bmpr_inc_lights', 'a_bump1',
      'attack_bumpers', 5);
  }

  _launchRollover(code, obj) {
    if (code === 0x3f) {
      this._rolloverBank(obj, ['lite171', 'lite170', 'lite169'], ['a_roll112', 'a_roll111'], 'ramp_bmpr_inc_lights',
        'a_bump5', 'launch_bumpers', 6);
    }
  }

  _bumperGroupDecay(code, obj) {
    if (code === 0x3d && obj.level !== 0) {
      obj.message(0x30, 60.0);
      obj.message(0xd);
    }
  }

  _rebound(code, obj, light) {
    if (code === 0x3f) {
      if (light !== null) this.msg(light, 9, 0.1);
      this.addScore(this.scoreOf(obj, 0));
    }
  }

  _gate(code, light, arrow) {
    if (code === 0x35) {
      this.msg(light, 0xf, 5.0);
      this.msg(arrow, 7, 5.0);
    } else if (code === 0x36) {
      this.msg(light, 0x14);
      this.msg(arrow, 0x14);
    }
  }

  _skillShot(code, obj) {
    if (code !== 0x3f) return;
    const lit = this.msg('skill_shot_lights', 0x25);
    if (!lit) return;
    this.play('soundwave3');
    const added = this.addScore(this.scoreOf(obj, lit - 1));
    this.text('info', 21, 2.0, added);
    if (!this.lit('lite56')) {
      for (const group of ['l_trek_lights', 'r_trek_lights']) {
        this.msg(group, 0x22);
        this.msg(group, 0x14);
      }
    }
    this.msg('skill_shot_lights', 0x2c, 1.0);
  }

  _centerPost(code, obj) {
    if (code === 0x34) {
      obj.data = 1;
      obj.message(0x34, obj.up_time);
      this.msg('lite1', 9, obj.up_time);
    } else if (code === 0x3c) {
      if (obj.data !== 1) {
        obj.data = 0;
        obj.message(0x33);
        return;
      }
      obj.data = 2;
      obj.message(0x3b, obj.warn_time);
      this.msg('lite1', 7, obj.warn_time);
    }
  }

  _ramp(code, obj) {
    if (code !== 0x3f) return;
    let m = 0;
    if (this.lit('lite54')) {
      m = 1;
      const added = this.award(this.reflex_value);
      this.text('info', 10, 2.0, added);
    }
    if (this.lit('lite55')) m |= 2;
    if (this.lit('lite56')) m |= 4;
    let wave;
    if (m === 0) {
      this.addScore(this.scoreOf(obj, 0));
      wave = 'soundwave30';
    } else if (m === 1) {
      wave = 'soundwave21';
    } else if (m < 4) {
      wave = 'soundwave23';
    } else {
      wave = 'soundwave24';
    }
    this.play(wave);
  }

  _outlane(code, obj) {
    if (code !== 0x3f) return;
    if (!this.lit('lite17') && !this.lit('lite18')) {
      this.play('soundwave26');
    } else {
      this._extraBall(2.0);
      this.msg('lite17', 0x14);
      this.msg('lite18', 0x14);
    }
    if (obj === this.objects.get('a_roll4')) {
      if (this.lit('lite30')) {
        this.msg('lite30', 4);
        this.msg('lite196', 4);
      }
    } else if (this.lit('lite29')) {
      this.msg('lite29', 4);
      this.msg('lite195', 4);
    }
    this.addScore(this.scoreOf(obj, 0));
  }

  _lite17(code, obj) {
    if (code === 0x13) {
      this.msg('lite17', 9, 55.0);
      this.msg('lite18', 9, 55.0);
      this.rollover_bonus_lit = 1;
    } else if (code === 0x3c && this.rollover_bonus_lit) {
      this.msg('lite17', 7, 5.0);
      this.msg('lite18', 7, 5.0);
      this.rollover_bonus_lit = 0;
    }
  }

  _inlane(code, obj) {
    if (code !== 0x3f) return;
    const light = obj === this.objects.get('a_roll6') ? 'lite27' : 'lite28';
    let index = 0;
    if (this.lit(light)) {
      this.msg('lite59', 0x14);
      this.msg(light, 0x14);
      index = 1;
    }
    this.addScore(this.scoreOf(obj, index));
  }

  _fuelRollover(code, obj) {
    if (code !== 0x3f) return;
    if (!this.lit('lite16')) {
      this.addScore(this.scoreOf(obj, 0));
      this.play('soundwave25');
      this.text('info', 44, 2.0);
    } else {
      const added = this.award(this.bonus);
      this.text('info', 3, 2.0, added);
      this.msg('lite16', 0x14);
      this.play('soundwave50');
    }
    this.msg('fuel_bargraph', 0x2d, 11.0);
  }

  _fuelLane(code, obj, index) {
    if (code !== 0x3f) return;
    const target = 2 * index + 1;
    if (this.msg('fuel_bargraph', 0x25) < target + 1) {
      this.msg('fuel_bargraph', 0x2d, target);
      this.text('info', 44, 2.0);
    } else {
      this.msg(`literoll${179 + index}`, 8, 0.05);
    }
    this.addScore(this.scoreOf(obj, 0));
  }

  _flag(code, obj) {
    if (code === 0x3e) this._advanceWormhole(0);
    else if (code === 0x3f) this.addScore(this.scoreOf(obj, this.lit('lite20') ? 1 : 0));
  }

  _hyperspace(code, obj) {
    if (code !== 0x3f) return;
    const level = this.msg('hyperspace_lights', 0x25);
    this._decayingGroup(0x29, this.objects.get('hyperspace_lights'), 60.0);
    if (level === 0) {
      const added = this.addScore(this.scoreOf(obj, 0));
      this.text('info', 12, 2.0, added);
    } else if (level === 1) {
      const added = this.award(this.jackpot);
      this.text('info', 14, 2.0, added);
      this.jackpot = 20000;
    } else if (level === 2) {
      this._centerPost(0x34, this.objects.get('v_bloc1'));
      const added = this.addScore(this.scoreOf(obj, 2));
      this.text('info', 2, 2.0, added);
    } else if (level === 3) {
      this._lite17(0x13, null);
      const added = this.addScore(this.scoreOf(obj, 3));
      this.text('info', 8, 2.0, added);
    } else if (level === 4) {
      this.msg('hyperspace_lights', 0);
      const added = this.addScore(this.scoreOf(obj, 4));
      this._gravityWell(0x40, null, added);
    }
    let m = 0;
    if (this.lit('lite25')) {
      m = 1;
      const added = this.award(this.reflex_value);
      this.text('info', 10, 2.0, added);
    }
    if (this.lit('lite26')) m |= 2;
    if (this.lit('lite130')) {
      m |= 4;
      this.msg('lite130', 0x14);
      this._multiplierGroup(0x40, this.objects.get('top_target_lights'));
      this.msg('bumper_target_lights', 0x13);
      this._jackpotOn();
      this._bonusOn();
      this._flagsUpgrade();
      this._bonusHold();
      this.msg('lite27', 0x13);
      this.msg('lite28', 0x13);
      this._lite17(0x13, null);
      this._centerPost(0x34, this.objects.get('v_bloc1'));
      if (this.multiball) this.text('info', 16, 2.0);
      this.jackpot = Math.max(this.jackpot, 100000);
      this.bonus = Math.max(this.bonus, 100000);
      this._gravityWell(0x40, null);
    }
    let duration;
    if (m === 0) {
      const waves = { 1: 'soundwave36', 2: 'soundwave35', 3: 'soundwave38', 4: 'soundwave39' };
      duration = this.play(waves[level] ?? 'soundwave35');
    } else if (m === 1 || m === 2 || m === 3) {
      duration = this.play(m === 1 ? 'soundwave21' : 'soundwave40');
    } else {
      duration = this.play('soundwave41');
      this.play('soundwave36');
      this.play('soundwave50');
    }
    this.msg('lite25', 7, 5.0);
    obj.message(0x37, duration);
  }

  _decayingGroup(code, obj, period) {
    if (code === 0) {
      obj.message(0, 0.0);
      return;
    }
    if (code === 0x29) {
      obj.message(0x29, 2.0);
    } else if (code === 0x3d) {
      obj.message(0x21);
      if (obj.message(0x25) === 0) return;
    } else {
      return;
    }
    obj.message(0x2b, period);
  }

  _wormhole(code, obj) {
    if (code !== 0x3f) return;
    const sinks = ['v_sink1', 'v_sink2', 'v_sink3'];
    const arrows = ['lite5', 'lite6', 'lite7'];
    const frames = ['lite4', 'lite2', 'lite3'];
    let here = sinks.indexOf(obj.name);
    const target = this.data('lite4');
    if (target === 0) {
      this.addScore(this.scoreOf(obj, 0));
      this.msg(arrows[here], 0x10, obj.eject_delay);
    } else {
      this.setData('lite4', 0);
      this.msg('worm_hole_lights', 0x14);
      this.msg('bsink_arrow_lights', 0x14);
      this.msg('lite110', 0x14);
      if (target === here + 1) {
        if (this.multiball) {
          this._lockBall();
          this.addScore(10000);
          return;
        }
        this.text('info', 49, 2.0);
        this._replayBall(4.0);
        this.addScore(this.scoreOf(obj, 1));
        this.msg(arrows[here], 0x10, obj.eject_delay);
        this.msg(frames[here], 0xb, 2 - here);
        this.msg(frames[here], 0x10, obj.eject_delay);
        this.msg(sinks[here], 0x38, obj.eject_delay);
        return;
      }
      this.addScore(this.scoreOf(obj, 2));
      here = target - 1;
      this.msg(arrows[here], 0x10, obj.eject_delay);
    }
    this.msg(frames[here], 0xb, 2 - here);
    this.msg(frames[here], 0x10, obj.eject_delay);
    this.msg(sinks[here], 0x38, obj.eject_delay);
    this.text('info', 49, 2.0);
  }

  _laneChange(animation) {
    this.msg('bmpr_inc_lights', animation);
    this.msg('ramp_bmpr_inc_lights', animation);
    return true;
  }

  _plunger(code, obj) {
    if (code === 0x3f7) {
      this._mission(0x43, null);
    } else if (code === 0x3f8) {
      this.ball_save_window = 0;
      if (this.msg('middle_circle', 0x25) === 0) this.msg('middle_circle', 0x20);
      if (!this.lit('lite200')) {
        this.msg('skill_shot_lights', 0x14);
        this.msg('lite67', 0x13);
        this.msg('skill_shot_lights', 0x1a, 0.25);
        for (const group of ['l_trek_lights', 'r_trek_lights']) {
          this.msg(group, 0x14);
          this.msg(group, 0x20, 0.2);
          this.msg(group, 0x1a, 0.2);
        }
        this.reflex_value = 25000;
        this._multiplierGroup(0x41, this.objects.get('top_target_lights'));
        this.msg('fuel_bargraph', 0x13);
        this.msg('lite200', 0x13);
        this.msg('v_gate1', 0x35);
        this.msg('v_gate2', 0x35);
      }
      this.setData('lite200', 0);
    }
  }

  _threeBank(obj, names) {
    obj.data = 1;
    return names.reduce((sum, name) => sum + this.data(name), 0) === 3;
  }

  _resetBank(names) {
    for (let i = names.length - 1; i >= 0; i--) {
      this.setData(names[i], 0);
      this.msg(names[i], 0x32);
    }
  }

  _boosterTargets(code, obj) {
    if (code !== 0x3f || obj.data !== 0) return;
    const names = ['a_targ1', 'a_targ2', 'a_targ3'];
    if (!this._threeBank(obj, names)) {
      this.addScore(this.scoreOf(obj, 0));
      return;
    }
    if (!this.lit('lite61')) {
      if (this.data('lite198') !== 0xf && this.data('lite198') !== 0x1d) {
        this._flagsUpgrade();
        this.play('soundwave47');
      }
    } else if (!this.lit('lite60')) {
      this._jackpotOn();
      this.play('soundwave45');
    } else if (!this.lit('lite59')) {
      this._bonusOn();
      this.play('soundwave46');
    } else if (!this.lit('lite58')) {
      this._bonusHold();
      this.play('soundwave48');
    } else {
      this.addScore(this.scoreOf(obj, 1));
      this.play('soundwave48');
    }
    for (const name of ['a_targ1', 'a_targ2', 'a_targ3']) {
      this.setData(name, 0);
      this.msg(name, 0x32);
    }
    this.addScore(this.scoreOf(obj, 1));
  }

  _jackpotOn() {
    this.jackpot_on = 1;
    this.msg('lite60', 9, 60.0);
    this.text('info', 15, 2.0);
  }

  _bonusOn() {
    this.bonus_on = 1;
    this.msg('lite59', 9, 60.0);
    this.text('info', 4, 2.0);
  }

  _flagsUpgrade() {
    this.msg('lite20', 9, 60.0);
    this.msg('lite19', 9, 60.0);
    this.msg('lite61', 9, 60.0);
    this.text('info', 51, 2.0);
  }

  _bonusHold() {
    this.msg('lite58', 0x13);
    this.text('info', 52, 2.0);
  }

  _medalTargets(code, obj) {
    if (code !== 0x3f || obj.data !== 0) return;
    if (!this._threeBank(obj, ['a_targ4', 'a_targ5', 'a_targ6'])) {
      this.addScore(this.scoreOf(obj, 0));
      return;
    }
    this._decayingGroup(0x29, this.objects.get('bumper_target_lights'), 30.0);
    const count = this.msg('bumper_target_lights', 0x25);
    if (count === 1) {
      this.addScore(this.scoreOf(obj, 1));
      this.text('info', 53, 2.0);
    } else if (count === 2) {
      this.addScore(this.scoreOf(obj, 2));
      this.text('info', 54, 2.0);
    } else {
      this.text('info', 55, 2.0);
      this._extraBall(4.0);
    }
    this._resetBank(['a_targ4', 'a_targ5', 'a_targ6']);
  }

  _multiplierTargets(code, obj) {
    if (code !== 0x3f || obj.data !== 0) return;
    if (!this._threeBank(obj, ['a_targ7', 'a_targ8', 'a_targ9'])) {
      this.addScore(this.scoreOf(obj, 0));
      return;
    }
    this.addScore(this.scoreOf(obj, 1));
    this._multiplierGroup(0x29, this.objects.get('top_target_lights'));
    const count = this.msg('top_target_lights', 0x25);
    this.multiplier = [1, 2, 3].includes(count) ? count : 4;
    this.text('info', { 1: 56, 2: 57, 3: 58 }[count] ?? 59, 2.0);
    this._resetBank(['a_targ7', 'a_targ8', 'a_targ9']);
  }

  _multiplierGroup(code, obj) {
    if (code === 0) {
      obj.message(0, 0.0);
      return;
    }
    if (code === 0x29) {
      obj.message(0x29, 2.0);
      obj.message(0x2b, 30.0);
    } else if (code === 0x3d) {
      if (this.multiplier) this.multiplier -= 1;
      obj.message(0x21);
      if (obj.message(0x25)) obj.message(0x2b, 30.0);
    } else if (code === 0x40) {
      this.multiplier = 4;
      obj.message(0x13);
      obj.message(0x2b, 30.0);
      this.text('info', 59, 2.0);
    } else if (code === 0x41) {
      this.multiplier = 0;
      obj.message(0x14);
      obj.message(0x2b, -1.0);
    }
  }

  _fuelTargets(code, obj) {
    if (code !== 0x3f) return;
    const light = { a_targ10: 'lite70', a_targ11: 'lite71' }[obj.name] ?? 'lite72';
    this.msg(light, 0xf, 2.0);
    this.addScore(this.scoreOf(obj, 0));
    if (this.msg('top_circle_tgt_lights', 0x25) === 3) {
      this.msg('top_circle_tgt_lights', 0x10, 2.0);
      this.msg('fuel_bargraph', 0x2d, 11.0);
      this.play('soundwave25');
      this.text('info', 44, 2.0);
    } else {
      this.play('soundwave49D');
    }
  }

  _missionTargets(code, obj) {
    if (code !== 0x3f) return;
    const bits = { a_targ13: [1, 'lite101'], a_targ14: [2, 'lite102'] }[obj.name] ?? [4, 'lite103'];
    this.setData('lite101', this.data('lite101') | bits[0]);
    this.msg(bits[1], 0xf, 2.0);
    if (!this.lit('lite198') || this.objects.get('lite198').flashing) this.play('soundwave52');
    else this.play('soundwave49D');
    this.addScore(this.scoreOf(obj, 0));
    if (this.msg('ramp_tgt_lights', 0x25) === 3) this.msg('ramp_tgt_lights', 0x10, 2.0);
  }

  _gateTargets(code, obj, first, lights, bank, gate) {
    if (code !== 0x3f) return;
    let bit;
    let light;
    if (obj.name === first[0]) [bit, light] = [1, lights[0]];
    else if (obj.name === first[1]) [bit, light] = [2, lights[1]];
    else [bit, light] = [4, lights[2]];
    this.setData(lights[0], this.data(lights[0]) | bit);
    this.msg(light, 0xf, 2.0);
    this.addScore(this.scoreOf(obj, 0));
    if (this.msg(bank, 0x25) === 3) {
      this.play('soundwave14');
      this.msg(gate, 0x35);
      this.msg(bank, 0x10, 2.0);
    } else {
      this.play('soundwave49D');
    }
  }

  _wormholeTarget(code, obj) {
    if (code !== 0x3f) return;
    if (!this.lit('lite110')) {
      this.msg('lite110', 0xf, 3.0);
      this.text('info', 93, 2.0);
    }
    this.addScore(this.scoreOf(obj, 0));
    this._advanceWormhole(1);
  }

  _advanceWormhole(force) {
    const mission = this.data('lite198');
    if (mission === 0x10 || mission === 0x16 || mission === 0x17 || (force === 0 && this.data('lite4') === 0)) return;
    let target = this.data('lite4') + 1;
    if (target === 4) target = 1;
    this.msg('bsink_arrow_lights', 0x17, target);
    this.msg('bsink_arrow_lights', 0xb, 3 - target);
    if (!this.lit('lite4')) {
      this.msg('worm_hole_lights', 0x13);
      this.msg('bsink_arrow_lights', 0x13);
    }
  }

  _blackHole(code, obj) {
    if (code === 0x3f) {
      const added = this.addScore(this.scoreOf(obj, 0));
      this.text('info', 80, 2.0, added);
      obj.message(0x37, -1.0);
    }
  }

  _gravityWell(code, obj, value = 0) {
    const well = this.objects.get('a_kout1');
    if (code === 0x3f && obj !== null) {
      const added = this.addScore(this.scoreOf(obj, 0));
      this.text('info', 81, 2.0, added);
      this.msg('lite62', 0x14);
      obj.active = false;
      const duration = this.play('soundwave7');
      obj.message(0x37, duration);
    } else if (code === 0x40) {
      if (value) this.text('info', 82, 2.0, value);
      else this.text('info', 45, 2.0);
      this.msg('lite62', 4);
      if (well !== undefined) well.active = true;
    } else if (code === 0x400 && well !== undefined) {
      well.active = false;
    }
  }

  _launchLane(code, obj) {
    if (code !== 0x3f) return;
    this.msg('lite200', 9, 5.0);
    if (this.lit('lite67')) {
      this.msg('skill_shot_lights', 0x22);
      this.msg('skill_shot_lights', 0x14);
      this.msg('lite67', 0x13);
      this.msg('lite54', 7, 5.0);
      this.msg('lite25', 7, 5.0);
      this.msg('fuel_bargraph', 0x2d, 11.0);
      this.play('soundwave14');
    }
  }

  _skillTrip(code, light) {
    if (code === 0x3f && this.lit('lite67')) {
      this.msg(light, 0x13);
      this.play('soundwave14');
    }
  }

  _redeployLight(code, obj) {
    if (code === 0x3c) {
      if (obj.data === 0) {
        obj.message(0x10, 5.0);
        obj.data = 1;
      } else {
        obj.data = 0;
      }
    }
  }

  _extraBall(seconds) {
    this.extra_balls += 1;
    this.play('soundwave28');
    this.text('info', 9, seconds);
  }

  _replayBall(seconds) {
    this.msg('lite199', 0x13);
    this.text('info', 0, seconds);
  }

  _lockBall() {
    if (this.locked_balls === 2) {
      this.text('info', 16, 2.0);
      this.locked_balls = 0;
      return;
    }
    this.locked_balls += 1;
    this.play('soundwave44');
    this.text('info', 1, 2.0);
    this.msg('plunger', 0x3f8);
  }

  _drain(code, obj) {
    if (code === 0x3c) {
      if (this.data('lite199') !== 0) {
        this.scoreMessage(0x3fe);
        if (this.hasHighScore()) {
          this.play('soundwave3');
          this.all_lights.message(0x10, 3.0);
          this.text('mission', 177, -1.0);
        }
        return;
      }
      this.msg('plunger', 0x3f8);
      return;
    }
    if (code !== 0x3f) return;
    if (this.ball_save_window !== 0) {
      this.msg('drain', 0x400);
      this.msg('v_sink3', 0x38, 0.0);
      return;
    }
    if (this.tilted) {
      this.msg('lite200', 0x14);
      this.msg('lite199', 0x14);
    }
    if (this.lit('lite200')) {
      this.play('soundwave27');
      this.msg('lite200', 0x13);
      this.text('info', 96, -1.0);
      this.play('soundwave59');
      return;
    }
    if (this.lit('lite199')) {
      this.play('soundwave27');
      this.msg('lite199', 0x14);
      this.msg('lite200', 0x13);
      this.text('info', 95, 2.0);
      this.play('soundwave59');
      this.replay_balls -= 1;
      return;
    }
    if (this.multiball_balls !== 0) {
      this.play('soundwave27');
      this.multiball_balls -= 1;
      return;
    }
    if (!this.tilted) {
      const added = this.award(this.bonus);
      this.text('info', 94, 2.0, added);
    }
    if (this.extra_balls === 0) {
      this.balls -= 1;
      if (this.current_player + 1 === this.player_count && this.balls === 0) {
        this.setData('lite199', 1);
      } else {
        this.scoreMessage(0x3fd);
        this.setData('lite199', 0);
      }
      this.play('soundwave27');
    } else {
      this.extra_balls -= 1;
      this.play('soundwave59');
      this.text('info', 97 + Math.min(this.current_player, 3), -1.0);
    }
    for (const name of [
      'bmpr_inc_lights', 'ramp_bmpr_inc_lights', 'lite30', 'lite29', 'lite1', 'lite54', 'lite55', 'lite56',
      'lite17', 'lite18', 'lite27', 'lite28', 'lite16', 'lite20', 'hyperspace_lights', 'lite25', 'lite26',
      'lite130', 'lite19', 'worm_hole_lights', 'bsink_arrow_lights', 'l_trek_lights', 'r_trek_lights',
      'lite60', 'lite59', 'lite61', 'bumper_target_lights', 'top_target_lights', 'top_circle_tgt_lights',
      'ramp_tgt_lights', 'lchute_tgt_lights', 'bpr_solotgt_lights', 'lite110', 'skill_shot_lights',
      'lite77', 'lite198', 'lite196', 'lite195', 'fuel_bargraph',
    ]) this.msg(name, 0x14);
    this.msg('fuel_bargraph', 0x400);
    this._gravityWell(0x400, null);
    this.msg('lite62', 0x14);
    for (const name of ['lite4', 'lite101', 'lite102', 'lite103', 'ramp_tgt_lights']) this.setData(name, 0);
    this.msg('outer_circle', 0x22);
    this.msg('middle_circle', 0x22);
    for (const name of [
      'attack_bumpers', 'launch_bumpers', 'v_gate1', 'v_gate2', 'v_bloc1', 'a_targ1', 'a_targ2', 'a_targ3',
      'a_targ6', 'a_targ5', 'a_targ4', 'a_targ9', 'a_targ8', 'a_targ7',
    ]) this.msg(name, 0x400);
    this.setData('lite198', this.data('lite199') === 0 ? 0 : 0x20);
    this._mission(0x42, null);
    this.scoreMessage(0x3f4);
    if (!this.lit('lite58')) this.bonus = 25000;
    else this.msg('lite58', 0x14);
  }
}

export { Game, Bargraph, Bumper, BumperGroup, TextBox, soundFiles, pyFormat };
