// Port of app.py without pygame: the window procedure's input handling,
// the WinMain tick, the game-flow actions, and the frame composition. The
// browser shell (shell.js) feeds it keys / mouse / focus and real elapsed
// time, and draws `screen` plus the menu and dialogs; the parity test drives
// it the same way the Python trace drives app.App.

import { Ball } from './ball.js';
import * as c from './constants.js';
import {
  BUMP_BOTTOM, BUMP_LEFT, BUMP_RIGHT, DEFAULT_KEYS, LEFT_FLIPPER, OPTION_NAMES, PLUNGER, RIGHT_FLIPPER,
} from './controls.js';
import { buildDemo } from './demo.js';
import { Game } from './game.js';
import { loadOption, saveOptions } from './highscores.js';
import {
  DEMO, EXIT, FULL_SCREEN, HIGH_SCORES, HighScoreDialog, KeyMapperDialog, LAUNCH_BALL, MenuBar, MUSIC, NEW_GAME,
  PAUSE, PLAYER_CONTROLS, PLAYERS_1, PLAYERS_4, SOUNDS, ABOUT,
} from './menu.js';
import { taggedFloats } from './partout.js';
import { pyRound } from './pymath.js';
import { FlipperAnimation, Renderer, nudgeShift } from './render.js';
import { debugStripPalette } from './resources.js';
import { STRINGS } from './strings.js';
import { buildTable, mask } from './table_data.js';
import { Vec2 } from './vec2.js';

const DRAIN_DELAY = 1.82;
const STARTUP_WAIT_MS = 5000;
const FIRST_GAME_DELAY_MS = 2000;

const VK_D = 0x44;

class App {
  // data: { pf, font } ; audio: { playFile(name) -> seconds, playMusic(), stopMusic(), stopEffects(),
  // setEffectsEnabled(on) } ; options: { quick, demo, fullscreen } ; hooks (all optional):
  // { setTitle(text), fullScreen(on), minimize(), quit() }.
  constructor(data, audio, options = {}, hooks = {}) {
    this.frame = 0;
    this.audio = audio;
    this.options = options;
    this.hooks = hooks;
    this.voices = Math.min(8, loadOption('Voices', 8));
    this.music_device = !options.quick;
    this.sounds_on = loadOption('Sounds', 1);
    this.music_on = loadOption('Music', 1);
    this.full_screen = loadOption('FullScreen', 0);
    if (options.fullscreen) this.full_screen = 1;
    this.change_display = loadOption('Change Display', 1);
    this.players = Math.max(1, Math.min(4, loadOption('Players', 1)));
    this.keys = OPTION_NAMES.map((name, i) => loadOption(name, DEFAULT_KEYS[i]));
    this.audio.setEffectsEnabled(Boolean(this.sounds_on));
    this.running = true;
    this.focused = true;
    this.dragging = false;
    this.menu = new MenuBar((command) => this._command(command));
    this.dialog = null;
    this.about_open = false;

    const pf = data.pf;
    this.pf = pf;
    this.layout = buildTable(pf);
    this.world = this.layout.world;
    this.camera = this.layout.camera;
    [this.table_width, this.table_height] = this.layout.screen_size;
    this.left_flipper = this.layout.left_flipper;
    this.right_flipper = this.layout.right_flipper;
    this.plunger = this.layout.plunger;
    this.world.on_ball_drained = (ball) => this._onBallDrained(ball);
    this.ball = new Ball(this.layout.plunger_rest.copy(), { radius: this.layout.ball_radius, alive: false });

    this.game = new Game(pf, this.layout, (name) => this.audio.playFile(name));
    this._wireGame(this.game);
    this.renderer = new Renderer(pf, this.layout.resources.palette, this.camera, data.font);
    this.flipper_anims = new Map();
    for (const sprite of [this.layout.left_flipper_sprite, this.layout.right_flipper_sprite]) {
      if (sprite === null || !this.renderer.by_name.has(sprite.name)) continue;
      const entry = pf.find(sprite.name);
      this.flipper_anims.set(sprite.name, new FlipperAnimation(
        this.renderer.by_name.get(sprite.name), taggedFloats(entry, 804)[0], taggedFloats(entry, 805)[0],
        this.game.timers,
      ));
    }
    this.table_shift = [0, 0];

    this.tilt_heat = 0.0;
    this._nudge_active = new Map();
    this._nudge_timer = 0;
    this._startup_ms = STARTUP_WAIT_MS;
    this.debug_draw = false;
    this.fps_title = false;
    this.frame_graph = false;
    this.graph_palette = null;
    this._fps_frames = 0;
    this._fps_since = 0;
    this._first_game_ms = FIRST_GAME_DELAY_MS;
    this.game.high_scores.load();
    this.game.setMode(options.quick ? 1 : 3);
    this._updateMenu();
    if (this.full_screen) {
      this.full_screen = 0;
      this._toggleFullScreen();
    }
  }

  _startFirstGame() {
    if (this.options.demo) this._toggleDemo();
    else this._newGame(false);
  }

  _wireGame(game) {
    const layout = this.layout;
    const tilted = () => Boolean(this.world.tilted);
    for (const target of layout.wall_targets) game.register(target, 406);
    for (const rollover of layout.rollovers) {
      rollover.tilted = tilted;
      game.register(rollover, 304);
    }
    for (const flag of layout.flags) {
      flag.tilted = tilted;
      flag.schedule = (delay, cb) => game.timers.schedule(delay, cb);
      game.register(flag, 304);
    }
    for (const line of layout.passes) {
      line.tilted = tilted;
      game.register(line, line.name.startsWith('s_trip') ? 304 : 406);
    }
    for (const sw of layout.switches) {
      game.register(sw, 406);
      const ref = game.soundRef(sw.name, 304);
      sw.soft_sound = ref !== null ? () => game.playEntry(ref) : null;
    }
    for (const gate of layout.gates) game.register(gate);
    for (const kickback of layout.kickbacks) game.register(kickback, 406);
    for (const sink of layout.sinks) {
      sink.ball_source = () => this._sinkBall();
      sink.on_eject = () => {};
      game.register(sink, 1100);
    }
    for (const kickout of layout.kickouts) game.register(kickout, 304);
    for (const ramp of layout.ramps) {
      ramp.tilted = tilted;
      game.register(ramp);
    }
    for (const hole of layout.ramp_holes) game.register(hole);
    if (layout.center_post !== null) game.register(layout.center_post);
    for (const bumper of layout.bumpers) bumper.on_hit = (circle) => this._onBumperHit(circle);
    game.setupControls(() => this._serve(), DRAIN_DELAY);
    game.on_input = (code) => this._gameInput(code);
    game.on_flipper_message = (code) => this._flipperMessage(code);
    game.on_broadcast = (code, value) => this._onBroadcast(code, value);
    game.on_hide_ball = () => this._hideBall();
    game.on_force_drain = () => this._forceDrain();
    const entry = game.pf.find('demo');
    if (entry !== null) {
      const demo = buildDemo(entry, game.timers, (code) => game.scoreMessage(code), () => this._restartDemo(),
        mask(entry), this.layout.ball_radius);
      this.world.trip_lines.push(...demo.lines);
      game.demo_player = demo;
      game.objects.set(demo.name, demo);
    }
  }

  _gameInput(code) {
    if (code === 1000 || code === 0x3e9) {
      this._setFlipper(this.left_flipper, this.layout.left_flipper_sprite, code === 1000);
    } else if (code === 0x3ea || code === 0x3eb) {
      this._setFlipper(this.right_flipper, this.layout.right_flipper_sprite, code === 0x3ea);
    } else if (code === 0x3ec) {
      this._pressPlunger();
    } else if (code === 0x3ed) {
      this._releasePlunger();
    }
  }

  _flipperMessage(code) {
    for (const [flipper, sprite] of [[this.left_flipper, this.layout.left_flipper_sprite],
      [this.right_flipper, this.layout.right_flipper_sprite]]) {
      const anim = sprite !== null ? this.flipper_anims.get(sprite.name) : undefined;
      if (code === 0x3f1 || code === 0x3f2 || code === 0x3f3 || code === 0x3fe) {
        flipper.message(2, this.world.time);
        if (flipper.pressed) {
          flipper.pressed = false;
          if (anim !== undefined) anim.message(2);
        }
      } else if ((code === 0x3fc || code === 0x400) && anim !== undefined && anim.mode) {
        anim.reset();
        flipper.message(code, this.world.time);
        if (code === 0x400) flipper.pressed = false;
      }
    }
  }

  _onBroadcast(code, value) {
    this._flipperMessage(code);
    if ((code === 0x3f1 || code === 0x3f2 || code === 0x400) && this.plunger !== null && this.plunger.pulling) {
      this.plunger.release();
    }
  }

  _sinkBall() {
    if (!this.ball.alive) {
      this.ball.alive = true;
      this.ball.held = false;
      this.world.balls = [this.ball];
    }
    return this.ball;
  }

  _hideBall() {
    this.world.balls = [];
    this.ball.alive = false;
  }

  _forceDrain() {
    if (this.ball.alive && !this.ball.held) this._onBallDrained(this.ball);
  }

  _newGame(demo) {
    this._unpause();
    this._restartMusic();
    this.game.newGame(demo, this.players);
    this._updateMenu();
  }

  _restartDemo() {
    this._newGame(true);
    this.game.scoreMessage(0x3f6, this.game.player_count);
  }

  _toggleDemo() {
    this._unpause();
    if (!this.game.demo) this._restartMusic();
    this.game.toggleDemo(this.players);
    this._updateMenu();
  }

  _togglePause() {
    this.game.togglePause();
    if (this.game.paused) this.audio.stopMusic();
    else this._restartMusic();
  }

  _unpause() {
    if (this.game.paused) this._togglePause();
  }

  _restartMusic() {
    this.audio.stopMusic();
    if (this.music_on && this.music_device) this.audio.playMusic();
  }

  _updateMenu() {
    const { mode, demo } = this.game;
    if (mode === 1) {
      this.menu.set(HIGH_SCORES, { enabled: !demo });
      this.menu.set(LAUNCH_BALL, { enabled: !demo });
      this.menu.set(DEMO, { checked: Boolean(demo) });
    } else if (mode === 2) {
      this.menu.set(LAUNCH_BALL, { enabled: false });
      if (!demo) {
        this.menu.set(HIGH_SCORES, { enabled: true });
        this.menu.set(DEMO, { checked: false });
      }
    } else {
      this.menu.set(LAUNCH_BALL, { enabled: false });
      this.menu.set(HIGH_SCORES, { enabled: false });
    }
    for (let command = PLAYERS_1; command <= PLAYERS_4; command++) {
      this.menu.set(command, { checked: command - PLAYERS_1 + 1 === this.players });
    }
    this.menu.set(SOUNDS, { checked: Boolean(this.sounds_on) });
    this.menu.set(MUSIC, { checked: Boolean(this.music_on) });
    this.menu.set(FULL_SCREEN, { checked: Boolean(this.full_screen) });
  }

  _command(command) {
    if (command === NEW_GAME) {
      this._newGame(false);
    } else if (command === LAUNCH_BALL) {
      this._unpause();
      if (this.plunger !== null) this.plunger.autoLaunch();
    } else if (command === PAUSE) {
      this._togglePause();
    } else if (command === HIGH_SCORES) {
      if (!this.game.paused) this._togglePause();
      this.dialog = new HighScoreDialog(this.game.high_scores);
    } else if (command === DEMO) {
      this._toggleDemo();
    } else if (command === EXIT) {
      this.running = false;
      if (this.hooks.quit) this.hooks.quit();
    } else if (command === FULL_SCREEN) {
      this._toggleFullScreen();
    } else if (command >= PLAYERS_1 && command <= PLAYERS_4) {
      this.players = command - PLAYERS_1 + 1;
      this._newGame(false);
    } else if (command === SOUNDS) {
      this.sounds_on = this.sounds_on ? 0 : 1;
      this.audio.setEffectsEnabled(Boolean(this.sounds_on));
    } else if (command === MUSIC) {
      this.music_on = this.music_on ? 0 : 1;
      if (this.music_on) this._restartMusic();
      else this.audio.stopMusic();
    } else if (command === PLAYER_CONTROLS) {
      this._playerControls();
    } else if (command === ABOUT) {
      if (!this.game.paused) this._togglePause();
      this.about_open = true;
    }
    this._updateMenu();
  }

  _playerControls() {
    if (!this.game.paused) this._togglePause();
    this.dialog = new KeyMapperDialog([...this.keys], (keys) => {
      this.keys = keys;
    });
  }

  // Full screen: the menu goes away and the screen fills the display
  // (the shell scales it, as a monitor shows the original's 640x480 mode).
  _toggleFullScreen() {
    this.full_screen = this.full_screen ? 0 : 1;
    if (this.hooks.fullScreen) {
      const ok = this.hooks.fullScreen(Boolean(this.full_screen));
      if (ok === false) this.full_screen = 0;
    }
  }

  // Esc: the original minimizes; in the presentation it hands the keyboard
  // back to the slides.
  _minimize() {
    if (this.full_screen) this._toggleFullScreen();
    if (this.hooks.minimize) this.hooks.minimize();
  }

  modal() {
    return this.menu.is_open || this.dialog !== null || this.about_open;
  }

  nextHighScoreEntry() {
    if (this.dialog !== null) return;
    if (!this.game.pending_entries.length) {
      if (this.game.after_entries !== null) this.game.after_entries();
      return;
    }
    const [score, name] = this.game.pending_entries.shift();
    const rank = this.game.high_scores.rank(score);
    if (rank >= 0) this.dialog = new HighScoreDialog(this.game.high_scores, { score, rank, name });
  }

  saveSettings() {
    this.game.high_scores.save();
    const options = { Sounds: this.sounds_on, Music: this.music_on, FullScreen: this.full_screen, Players: this.players };
    OPTION_NAMES.forEach((name, i) => {
      options[name] = this.keys[i];
    });
    saveOptions(options);
  }

  _serve() {
    const ball = new Ball(this.layout.plunger_rest.copy(), { radius: this.layout.ball_radius });
    this.world.balls = [ball];
    this.ball = ball;
    this.game.ball_lost = 0;
    if (this.game.tilted) this.game.clearText('info');
    this.game.tilted = 0;
    this.tilt_heat = -2.0;
  }

  _onBumperHit(circle) {
    this.game.bumperHit(circle.name, circle.cooldown);
  }

  _onBallDrained(ball) {
    this.world.balls = [];
    this.game.drain();
  }

  get score() {
    return this.game.score;
  }

  get balls_left() {
    return this.game.balls;
  }

  set balls_left(value) {
    this.game.balls = value;
  }

  get tilted() {
    return Boolean(this.game.tilted);
  }

  // -- input (the window procedure) -----------------------------------------
  // ev: { vk, char } for dialogs; returns nothing.
  keyDown(ev) {
    if (this._first_game_ms > 0) return;
    if (this.dialog !== null) {
      this.dialog.key(ev);
      if (this.dialog.done) this.dialog = null;
      return;
    }
    if (this.about_open) {
      if (ev.vk === 0x0d || ev.vk === 0x1b || ev.vk === 0x20) this.about_open = false;
      return;
    }
    if (this.menu.is_open) {
      if (ev.vk === 0x1b) this.menu.close();
      return;
    }
    this._keyDown(ev.vk);
  }

  keyUp(ev) {
    if (this._first_game_ms > 0) return;
    if (!this.modal()) this._keyUp(ev.vk);
  }

  focusChanged(gained) {
    if (this._first_game_ms > 0) return;
    if (gained) {
      this.focused = true;
      if (!this.game.paused) this._restartMusic();
    } else {
      this.focused = false;
      this.game.focusLost();
      if (this.full_screen) this._toggleFullScreen();
      this.audio.stopEffects();
      this.audio.stopMusic();
    }
  }

  // pos in the 600 x (416 + menu) drawing surface's pixels.
  click(pos, menuShown = true) {
    if (this._first_game_ms > 0) return;
    if (this.dialog !== null) {
      this.dialog.click(pos);
      if (this.dialog.done) this.dialog = null;
      return;
    }
    if (this.about_open) {
      this.about_open = false;
      return;
    }
    if (menuShown && !this.full_screen && this.menu.click(pos)) return;
    if (this.game.mode === 0) {
      this._startupInput();
    } else if (this.game.debug_mode) {
      this.dragging = true;
    }
  }

  mouseUp() {
    this.dragging = false;
  }

  mouseMove(pos) {
    if (this._first_game_ms > 0) return;
    if (!this.full_screen) this.menu.hover(pos);
  }

  // FUN_01014d8e while dragging: (dx, dy) in screen pixels since the last loop.
  dragBall(dx, dy) {
    this.ball.velocity = new Vec2(-dx * 30.0, dy * 30.0);
  }

  wheel(dy) {
    if (this.dialog instanceof KeyMapperDialog) this.dialog.wheel(dy);
  }

  _keyDown(vk) {
    this._tableKeyDown(vk);
    if (vk === 0x1b) this._minimize();
    else if (vk === 0x71) this._newGame(false);
    else if (vk === 0x72) this._togglePause();
    else if (vk === 0x73) this._toggleFullScreen();
    else if (vk === 0x77) this._playerControls();
    else if (vk === VK_D && !this.keys.includes(vk)) this.debug_draw = !this.debug_draw;
    if (this.game.debug_mode) {
      if (vk === 0x48) {
        this.frame_graph = true;
      } else if (vk === 0x59) {
        if (this.hooks.setTitle) this.hooks.setTitle('Pinball');
        this.fps_title = !this.fps_title;
      } else if (vk === 0x70) {
        this.update(0.010, true);
      } else if (vk === 0x7e) {
        this.game.paused = this.game.paused ? 0 : 1;
      }
    }
  }

  _tableKeyDown(vk) {
    const game = this.game;
    if (game.paused || game.demo) return;
    if (game.mode !== 1) {
      this._startupInput();
      return;
    }
    game.typeKey(vk);
    const keys = this.keys;
    if (vk === keys[LEFT_FLIPPER]) {
      game.scoreMessage(1000);
      return;
    }
    if (vk === keys[RIGHT_FLIPPER]) {
      game.scoreMessage(0x3ea);
    } else if (vk === keys[PLUNGER]) {
      game.scoreMessage(0x3ec);
      return;
    } else if (vk === keys[BUMP_LEFT] || vk === keys[BUMP_RIGHT] || vk === keys[BUMP_BOTTOM]) {
      if (!game.tilted) this._nudge(vk);
      return;
    }
    if (game.debug_mode) this._debugKey(vk);
  }

  _debugKey(vk) {
    const game = this.game;
    if (vk === 0x42) {
      const ball = this.ball;
      ball.position = new Vec2(1.0, 1.0);
      ball.velocity = new Vec2(0.0, 0.0);
      ball.z = ball.radius;
      ball.alive = true;
      ball.held = false;
      this.world.balls = [ball];
    } else if (vk === 0x48) {
      this.dialog = new HighScoreDialog(game.high_scores, { score: 1000000000, rank: 1, name: STRINGS.get(26) });
    } else if (vk === 0x52) {
      game.cheatRank();
    }
  }

  _keyUp(vk) {
    const game = this.game;
    if (game.mode !== 1 || game.paused || game.demo) return;
    const keys = this.keys;
    if (vk === keys[LEFT_FLIPPER]) game.scoreMessage(0x3e9);
    else if (vk === keys[RIGHT_FLIPPER]) game.scoreMessage(0x3eb);
    else if (vk === keys[PLUNGER]) game.scoreMessage(0x3ed);
    else if (vk === keys[BUMP_LEFT] || vk === keys[BUMP_RIGHT] || vk === keys[BUMP_BOTTOM]) this._undoNudge(vk);
  }

  _startupInput(elapsedMs = -1) {
    const game = this.game;
    if (game.mode === 1 || game.mode === 2) return false;
    if (game.mode === 3 || game.mode === 4) {
      this._startup_ms -= elapsedMs;
      if (this._startup_ms >= 0 && elapsedMs >= 0) return true;
      game.setMode(game.mode === 3 ? 4 : 1);
      this._startup_ms = STARTUP_WAIT_MS;
      this._updateMenu();
    }
    return true;
  }

  _setFlipper(flipper, sprite, pressed) {
    if (flipper.pressed === pressed) return;
    flipper.pressed = pressed;
    flipper.message(pressed ? 1 : 2, this.world.time);
    if (sprite !== null) {
      this.game.flipper(sprite.name, pressed);
      const anim = this.flipper_anims.get(sprite.name);
      if (anim !== undefined) anim.message(pressed ? 1 : 2);
    }
  }

  _pressPlunger() {
    if (this.plunger === null || this.plunger.pulling) return;
    this.plunger.press();
    this.game.playRef('plunger', 406);
  }

  _releasePlunger() {
    if (this.plunger === null || !this.plunger.pulling) return;
    this.plunger.release();
    this.game.playRef('plunger', 1101);
  }

  _nudge(key) {
    const keys = this.keys;
    let call;
    if (key === keys[BUMP_LEFT]) call = c.NUDGE_CALL_LEFT;
    else if (key === keys[BUMP_RIGHT]) call = c.NUDGE_CALL_RIGHT;
    else call = c.NUDGE_CALL_BOTTOM;
    this._nudgeCall(call[0], call[1]);
    if (this._nudge_timer) this.game.timers.cancel(this._nudge_timer);
    this._nudge_timer = this.game.timers.schedule(c.NUDGE_AUTO_CANCEL_SECONDS, () => this._undoNudge(key));
    this._nudge_active.set(key, call);
  }

  _undoNudge(key) {
    const call = this._nudge_active.get(key);
    this._nudge_active.delete(key);
    if (call !== undefined) this._nudgeCall(-call[0], -call[1]);
  }

  _nudgeCall(x, y) {
    const ball = this.ball;
    if (ball.alive && !ball.held) ball.velocity = ball.velocity.add(new Vec2(x * 0.5, y * 0.5));
    const [dx, dy] = nudgeShift(x, y);
    this.table_shift = [this.table_shift[0] + dx, this.table_shift[1] + dy];
  }

  _countFrame(elapsedMs, nowMs) {
    if (!this.fps_title) {
      this._fps_frames = 0;
      this._fps_since = nowMs;
      return;
    }
    if (this.frame_graph && this.graph_palette === null) {
      this.graph_palette = debugStripPalette();
      this.renderer.setPalette(this.graph_palette);
    }
    this._fps_frames += 1;
    if (this._fps_frames >= 300) {
      const elapsed = Math.max(1, nowMs - this._fps_since);
      if (this.hooks.setTitle) this.hooks.setTitle(`Frames/sec = ${(300.0 / (elapsed * 0.001)).toFixed(2)}`);
      this._fps_since = nowMs;
      this._fps_frames = 0;
    }
  }

  _updateTiltHeat(dt) {
    if (this._nudge_active.size) this.tilt_heat += c.TILT_HEAT_RISE_RATE * dt;
    else this.tilt_heat = Math.max(0.0, this.tilt_heat - c.TILT_HEAT_DECAY_RATE * dt);
    if (this.game.tilted) return;
    if (this.tilt_heat > c.TILT_HEAT_WARN_THRESHOLD) this.game.text('info', 25, 2.0);
    if (this.tilt_heat > c.TILT_HEAT_TRIGGER_THRESHOLD) this.game.tilt();
  }

  // One WinMain tick of `dt` seconds (the real elapsed time).
  update(dt, forced = false, nowMs = 0) {
    if (this._first_game_ms > 0) {
      this._first_game_ms -= dt * 1000.0;
      if (this._first_game_ms <= 0) {
        this._first_game_ms = 0;
        this._startFirstGame();
      }
      return;
    }
    dt = Math.min(dt, 0.1);
    if ((this.game.paused && !forced) || this._startupInput(pyRound(dt * 1000))) return;
    this._countFrame(pyRound(dt * 1000), nowMs);
    this.world.tilted = this.tilted;
    this.world.step(dt);
    if (this.plunger !== null) this.plunger.update(dt);
    const layout = this.layout;
    for (const entity of [...layout.kickbacks, ...layout.sinks, ...layout.kickouts, ...layout.ramp_holes,
      ...layout.wall_targets, ...layout.rollovers, ...layout.switches]) entity.update(dt);
    if (layout.center_post !== null) layout.center_post.update(dt);
    this.game.update(dt);
    this._updateTiltHeat(dt);
    this.world.tilted = this.tilted;
    this.frame += 1;
  }

  // -- drawing --------------------------------------------------------------
  // Composes the 600x416 palette-index screen (renderer.screen).
  draw() {
    this.renderer.shift = this.table_shift;
    this._syncSprites();
    const game = this.game;
    const balls = game.balls;
    this.renderer.compose(
      this._visibleBall(),
      this.score,
      balls >= 1 ? game.balls_per_game - balls + 1 : null,
      game.player_number,
      this.texts(),
    );
    return this.renderer.screen;
  }

  texts() {
    return new Map([['info_text_box', this.game.info_text], ['mission_text_box', this.game.mission_text]]);
  }

  _visibleBall() {
    const inRampHole = this.layout.ramp_holes.some((hole) => hole.held_ball === this.ball);
    const inKickout = this.layout.kickouts.some((k) => k.held_ball === this.ball);
    if (this.ball.alive && (!this.ball.held || inRampHole || inKickout)) return [this.ball.position, this.ball.z];
    return null;
  }

  _syncSprites() {
    const sprites = this.renderer.by_name;
    const layout = this.layout;
    const show = (name, index) => {
      const sprite = sprites.get(name);
      if (sprite !== undefined) sprite.setBitmap(index === null ? null : Math.min(index, sprite.frames.length - 1));
    };
    const frame = (name, index) => {
      const sprite = sprites.get(name);
      if (sprite !== undefined) sprite.setFrame(Math.max(0, Math.min(index, sprite.frames.length - 1)));
    };
    for (const [name, light] of this.game.lights) show(name, light.shown);
    for (const [name, bumper] of this.game.bumpers) frame(name, bumper.frame);
    for (const flag of layout.flags) frame(flag.name, flag.frame);
    for (const target of layout.wall_targets) {
      if (target.drop_time > 0) frame(target.name, target.up ? 0 : 1);
      else show(target.name, target.up ? 0 : null);
    }
    for (const rollover of layout.rollovers) show(rollover.name, rollover.shown ? 0 : null);
    for (const sw of layout.switches) show(sw.name, sw.lit ? 0 : null);
    for (const gate of layout.gates) show(gate.name, gate.is_open ? null : 0);
    if (layout.center_post !== null) show(layout.center_post.name, layout.center_post.up ? 0 : null);
    for (const kickback of layout.kickbacks) {
      if (kickback.frame === null) show(kickback.name, null);
      else frame(kickback.name, kickback.frame);
    }
    const plunger = sprites.get('plunger');
    if (this.plunger !== null && plunger !== undefined) {
      const count = plunger.frames.length;
      const pull = this.plunger.pulling ? this.plunger.kick / this.plunger.max_kick : 0.0;
      plunger.setFrame(Math.floor((count - 1) * pull));
    }
  }
}

export { App };
