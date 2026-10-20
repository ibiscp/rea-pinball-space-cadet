from __future__ import annotations

import logging
import math
import sys

import pygame

from . import constants as c
from . import debug_log
from .assets import font_data, pinball_data
from .audio import AudioManager
from .ball import Ball
from .controls import (
    BUMP_BOTTOM,
    BUMP_LEFT,
    BUMP_RIGHT,
    DEFAULT_KEYS,
    LEFT_FLIPPER,
    OPTION_NAMES,
    PLUNGER,
    RIGHT_FLIPPER,
    vk_of,
)
from .demo import build_demo
from .game import Game
from .geometry import Circle
from .highscores import load_option, save_options
from .menu import (
    ABOUT,
    DEMO,
    EXIT,
    FULL_SCREEN,
    HIGH_SCORES,
    LAUNCH_BALL,
    MENU_HEIGHT,
    MUSIC,
    NEW_GAME,
    PAUSE,
    PLAYER_CONTROLS,
    PLAYERS_1,
    PLAYERS_4,
    SOUNDS,
    HighScoreDialog,
    KeyMapperDialog,
    MenuBar,
)
from .projection import tagged_floats
from .render import FlipperAnimation, Renderer, nudge_shift
from .resources import debug_strip_palette
from .splash import show_splash
from .strings import STRINGS
from .table_data import _mask, build_table
from .vec2 import Vec2

log = logging.getLogger(__name__)

POSITION_LOG_INTERVAL = 10  # frames between periodic ball-position log lines
DRAIN_DELAY = 1.82  # the drain entry's tag 407
STARTUP_WAIT_MS = 5000  # FUN_0101461a(3 / 4): _DAT_01025574
FIRST_GAME_DELAY_MS = 2000  # WinMain's PeekMessage loop before the first game
FULL_SCREEN_MODE = (640, 480)  # FUN_01003a23: ChangeDisplaySettings 640x480x8
# Not from the original, which shows the 600x416 screen at 1x: the window is
# opened this much bigger (shrunk to fit the desktop) and can be resized.
# The game still draws at 600x416; _present scales it into the window and
# _to_screen maps the mouse back.
WINDOW_SCALE = 1.5


class App:
    def __init__(self) -> None:
        self.frame = 0
        log_path = debug_log.setup()
        if log_path is not None:
            log.info("Writing gameplay trace to %s", log_path)
        pygame.init()
        # A placeholder mode so sprite surfaces can call convert()/
        # convert_alpha() while loading the real table below (SDL requires a
        # display mode to exist first); resized to the table's actual size
        # once build_table() has determined it.
        # WinMain: the splash comes up before the main window, which then
        # loads the table in WM_CREATE.
        self._splash = show_splash()
        if not self._splash:
            pygame.display.set_mode((1, 1))
        pygame.display.set_caption(STRINGS[38])
        self.voices = min(8, load_option("Voices", 8))
        self.audio = AudioManager(self.voices)
        # "-quick" also skips opening the MIDI device (WM_CREATE only calls
        # FUN_0100af1f without it), so there's no music.
        self.music_device = "-quick" not in sys.argv
        # The options FUN_01006070 reads from the registry (here the
        # settings file, see highscores.py): Sounds / Music on, one player.
        self.sounds_on = load_option("Sounds", 1)
        self.music_on = load_option("Music", 1)
        self.full_screen = load_option("FullScreen", 0)
        if "-fullscreen" in sys.argv:
            self.full_screen = 1
        self.change_display = load_option("Change Display", 1)
        self.players = max(1, min(4, load_option("Players", 1)))
        self.keys = [load_option(name, default) for name, default in zip(OPTION_NAMES, DEFAULT_KEYS, strict=True)]
        self.audio.effects_enabled = bool(self.sounds_on)
        self.font = pygame.font.SysFont("arial", 16)
        self.running = True
        self.focused = True
        self.dragging = False
        self.menu = MenuBar(self._command)
        self.menu.to_screen = self._to_screen
        self._display: pygame.Surface | None = None
        self.dialog: HighScoreDialog | KeyMapperDialog | None = None
        self.about_open = False

        self.layout = build_table()
        self.world = self.layout.world
        self.camera = self.layout.camera
        self.table_width, self.table_height = self.layout.screen_size
        # The window's client area is the 600x416 screen (FUN_01015404 /
        # FUN_01003d65); the menu bar sits above it. Shown scaled, see
        # WINDOW_SCALE.
        self.window = self._open_window((self.table_width, self.table_height + MENU_HEIGHT))
        self.scene = pygame.Surface((self.table_width, self.table_height))
        self.left_flipper = self.layout.left_flipper
        self.right_flipper = self.layout.right_flipper
        self.plunger = self.layout.plunger
        self.world.on_ball_drained = self._on_ball_drained
        self.ball = Ball(position=self.layout.plunger_rest.copy(), radius=self.layout.ball_radius, alive=False)

        self.game: Game | None = None
        self.renderer: Renderer | None = None
        self.flipper_anims: dict[str, FlipperAnimation] = {}
        self.table_shift = (0, 0)
        if self.layout.resources is not None:
            pf = pinball_data()
            self.game = Game(pf, self.layout, play_file=self.audio.play_file)
            self._wire_game(self.game)
            self.renderer = Renderer(pf, self.layout.resources.palette, self.camera, font_data())
            self.scene = pygame.Surface((self.renderer.width, self.renderer.height))
            for sprite in (self.layout.left_flipper_sprite, self.layout.right_flipper_sprite):
                if sprite is None or sprite.name not in self.renderer.by_name:
                    continue
                entry = pf.find(sprite.name)
                self.flipper_anims[sprite.name] = FlipperAnimation(
                    self.renderer.by_name[sprite.name],
                    tagged_floats(entry, 804)[0],
                    tagged_floats(entry, 805)[0],
                    self.game.timers,
                )

        self.tilt_heat = 0.0
        # The three nudges' "active" flags (DAT_01025640 / 0102563c /
        # 01025644), keyed by the bump key, and the one timer handle they
        # share (DAT_01025648).
        self._nudge_active: dict[int, tuple[float, float]] = {}
        self._nudge_timer = 0
        self._startup_ms = STARTUP_WAIT_MS
        # Draws every collision shape over the real table art. Toggle with D.
        self.debug_draw = False

        debug_log.event(
            self.frame,
            "INIT",
            table=(self.table_width, self.table_height),
            plunger_rest=self.layout.plunger_rest,
            drain_y=round(self.world.drain_y, 3),
            frame_bounds=self.world.frame_bounds,
            n_segments=len(self.world.segments),
            n_trip_lines=len(self.world.trip_lines),
        )
        self.fps_title = False  # debug "Y"
        self.frame_graph = False  # debug "H"
        self._graph: pygame.Surface | None = None
        self._graph_palette: list[tuple[int, int, int]] = []
        self._graph_shown: pygame.Surface | None = None
        self._fps_frames = 0
        self._fps_since = pygame.time.get_ticks()
        self._first_game_ms = FIRST_GAME_DELAY_MS if self.game is not None else 0
        if self.game is not None:
            self.game.high_scores.load()  # FUN_01004d18
            # FUN_01015424: the startup wait (mode 3) unless "-quick".
            self.game.set_mode(1 if "-quick" in sys.argv else 3)
            self._update_menu()
        else:
            self._serve()
        if self.full_screen:
            self.full_screen = 0
            self._toggle_full_screen()

    def _start_first_game(self) -> None:
        """WinMain after its 2 s PeekMessage loop (input in it is thrown
        away): a demo for "-demo", else a new game (FUN_010153ae(0))."""
        if "-demo" in sys.argv:
            self._toggle_demo()
        else:
            self._new_game(demo=False)

    def _wire_game(self, game: Game) -> None:
        """Hand every table object to the control layer (game.py), which
        owns scoring, lights and the objects' messages."""
        layout = self.layout
        tilted = lambda: bool(self.world.tilted)
        for target in layout.wall_targets:
            game.register(target, 406)
        for rollover in layout.rollovers:
            rollover.tilted = tilted
            game.register(rollover, 304)
        for flag in layout.flags:
            flag.tilted = tilted
            flag.schedule = game.timers.schedule
            game.register(flag, 304)
        for line in layout.passes:
            line.tilted = tilted
            game.register(line, 304 if line.name.startswith("s_trip") else 406)
        for switch in layout.switches:
            game.register(switch, 406)
            ref = game.sound_ref(switch.name, 304)
            switch.soft_sound = (lambda i=ref: game.play_entry(i)) if ref is not None else None
        for gate in layout.gates:
            game.register(gate)
        for kickback in layout.kickbacks:
            game.register(kickback, 406)
        for sink in layout.sinks:
            sink.ball_source = self._sink_ball
            sink.on_eject = self._on_sink_eject
            game.register(sink, 1100)
        for kickout in layout.kickouts:
            game.register(kickout, 304)
        for ramp in layout.ramps:
            ramp.tilted = tilted
            game.register(ramp)
        for hole in layout.ramp_holes:
            game.register(hole)
        if layout.center_post is not None:
            game.register(layout.center_post)
        for bumper in layout.bumpers:
            bumper.on_hit = self._on_bumper_hit
        game.setup_controls(serve=self._serve, drain_delay=DRAIN_DELAY)
        game.on_input = self._game_input
        game.on_flipper_message = self._flipper_message
        game.on_broadcast = self._on_broadcast
        game.on_hide_ball = self._hide_ball
        game.on_force_drain = self._force_drain
        entry = game.pf.find("demo")
        if entry is not None:
            demo = build_demo(
                entry,
                game.timers,
                send=game.score_message,
                restart=self._restart_demo,
                mask=_mask(entry),
                ball_radius=self.layout.ball_radius,
            )
            self.world.trip_lines.extend(demo.lines)
            game.demo_player = demo
            game.objects[demo.name] = demo

    # -- game flow (the original's menu / key actions) -------------------------
    def _game_input(self, code: int) -> None:
        """The score object forwarding 1000 / 0x3e9 / 0x3ea / 0x3eb to the
        flippers (+0x2a / +0x2e) and 0x3ec / 0x3ed to the plunger (+0xde)."""
        if code in (1000, 0x3E9):
            self._set_flipper(self.left_flipper, self.layout.left_flipper_sprite, code == 1000)
        elif code in (0x3EA, 0x3EB):
            self._set_flipper(self.right_flipper, self.layout.right_flipper_sprite, code == 0x3EA)
        elif code == 0x3EC:
            self._press_plunger()
        elif code == 0x3ED:
            self._release_plunger()

    def _flipper_message(self, code: int) -> None:
        """0x3f1..0x3f3 / 0x3fe: down without the sound; 0x3fc / 0x400: an
        animating flipper sprite jumps to rest (0x101c178)."""
        for flipper, sprite in (
            (self.left_flipper, self.layout.left_flipper_sprite),
            (self.right_flipper, self.layout.right_flipper_sprite),
        ):
            anim = self.flipper_anims.get(sprite.name) if sprite is not None else None
            if code in (0x3F1, 0x3F2, 0x3F3, 0x3FE):
                # 0x101c178 sends the edge "down" (FUN_0101bf98(2)) every time.
                flipper.message(2, self.world.time)
                if flipper.pressed:
                    flipper.pressed = False
                    if anim is not None:
                        anim.message(2)
            elif code in (0x3FC, 0x400) and anim is not None and anim.mode:
                anim.reset()
                flipper.message(code, self.world.time)
                if code == 0x400:
                    flipper.pressed = False

    def _on_broadcast(self, code: int, value: float) -> None:
        """The score object's component loops also reach the flippers and
        the plunger, whose handlers live here."""
        self._flipper_message(code)
        if code in (0x3F1, 0x3F2, 0x400) and self.plunger is not None and self.plunger.pulling:
            self.plunger.release()  # FUN_010185ad: let go, no sound

    def _sink_ball(self) -> Ball:
        """FUN_01017130 ejects the score object's first ball and sets it
        active whatever state it was in (the "BMAX" save brings a drained
        ball back this way)."""
        if not self.ball.alive:
            self.ball.alive = True
            self.ball.held = False
            self.world.balls = [self.ball]
        return self.ball

    def _hide_ball(self) -> None:
        """0x3f6 parks the ball at (0, 0, -0.8), out of sight."""
        self.world.balls = []
        self.ball.alive = False

    def _force_drain(self) -> None:
        """FUN_01017738: the drain's collision handler on every ball."""
        if self.ball.alive and not self.ball.held:
            self._on_ball_drained(self.ball)

    def _new_game(self, demo: bool) -> None:
        """FUN_01007976 / FUN_010153ae: unpause, music from the top, 0x3f6."""
        if self.game is None:
            return
        self._unpause()
        self._restart_music()
        self.game.new_game(demo, self.players)
        self._update_menu()

    def _restart_demo(self) -> None:
        """FUN_01016eed: a new demo game, then 0x3f6 again (which serves at
        once instead of waiting for the start sound)."""
        self._new_game(demo=True)
        self.game.score_message(0x3F6, float(self.game.player_count))

    def _toggle_demo(self) -> None:
        """FUN_01015802 (Game > Demo, or "-demo" on the command line)."""
        self._unpause()
        if self.game.demo:
            self.game.toggle_demo(self.players)
        else:
            self._restart_music()
            self.game.toggle_demo(self.players)
        self._update_menu()

    def _toggle_pause(self) -> None:
        """FUN_01007918 -> FUN_010156e4 (F3)."""
        self.game.toggle_pause()
        if self.game.paused:
            self.audio.stop_music()
        else:
            self._restart_music()

    def _unpause(self) -> None:
        """FUN_01007949."""
        if self.game is not None and self.game.paused:
            self._toggle_pause()

    def _restart_music(self) -> None:
        """FUN_0100afdc(0): stop, then play PINBALL.MID from the start."""
        self.audio.stop_music()
        if self.music_on and self.music_device:
            self.audio.play_music("PINBALL.MID")

    def _update_menu(self) -> None:
        """FUN_0101461a's EnableMenuItem / CheckMenuItem calls and the
        option checks (FUN_010056ff)."""
        if self.game is None:
            return
        mode, demo = self.game.mode, self.game.demo
        if mode == 1:
            self.menu.set(HIGH_SCORES, enabled=not demo)
            self.menu.set(LAUNCH_BALL, enabled=not demo)
            self.menu.set(DEMO, checked=bool(demo))
        elif mode == 2:
            self.menu.set(LAUNCH_BALL, enabled=False)
            if not demo:
                self.menu.set(HIGH_SCORES, enabled=True)
                self.menu.set(DEMO, checked=False)
        else:
            self.menu.set(LAUNCH_BALL, enabled=False)
            self.menu.set(HIGH_SCORES, enabled=False)
        for command in range(PLAYERS_1, PLAYERS_4 + 1):
            self.menu.set(command, checked=command - PLAYERS_1 + 1 == self.players)
        self.menu.set(SOUNDS, checked=bool(self.sounds_on))
        self.menu.set(MUSIC, checked=bool(self.music_on))
        self.menu.set(FULL_SCREEN, checked=bool(self.full_screen))

    def _command(self, command: int) -> None:
        """WM_COMMAND (FUN_01007a3e)."""
        if self.game is None:
            return
        if command == NEW_GAME:
            self._new_game(demo=False)
        elif command == LAUNCH_BALL:
            self._unpause()
            if self.plunger is not None:
                self.plunger.auto_launch()  # plunger 0x3f9
        elif command == PAUSE:
            self._toggle_pause()
        elif command == HIGH_SCORES:
            if not self.game.paused:
                self._toggle_pause()
            self.dialog = HighScoreDialog(self.game.high_scores)
        elif command == DEMO:
            self._toggle_demo()
        elif command == EXIT:
            self.running = False
        elif command == FULL_SCREEN:
            self._toggle_full_screen()
        elif PLAYERS_1 <= command <= PLAYERS_4:
            self.players = command - PLAYERS_1 + 1
            self._new_game(demo=False)
        elif command == SOUNDS:
            self.sounds_on = int(not self.sounds_on)
            self.audio.effects_enabled = bool(self.sounds_on)
        elif command == MUSIC:
            self.music_on = int(not self.music_on)
            if self.music_on:
                self._restart_music()
            else:
                self.audio.stop_music()
        elif command == PLAYER_CONTROLS:
            self._player_controls()
        elif command == ABOUT:
            if not self.game.paused:
                self._toggle_pause()
            self.about_open = True
        self._update_menu()

    def _player_controls(self) -> None:
        """F8 / Options > Player Controls...: pause (if not paused), then the
        KEYMAPPER dialog (FUN_01005f45)."""
        if self.game is not None and not self.game.paused:
            self._toggle_pause()
        self.dialog = KeyMapperDialog(list(self.keys), self._set_keys)

    def _set_keys(self, keys: list[int]) -> None:
        self.keys = keys

    def _toggle_full_screen(self) -> None:
        """FUN_010056ff(0x193) -> FUN_01003be4. Full screen: with "Change
        Display" (default 1) the display is switched to 640x480
        (FUN_01003a23), otherwise the window just covers the desktop; the
        menu goes away and the 600x416 screen is drawn unscaled, centred on
        black (FUN_010038f8). Leaving restores the window (FUN_01003b66)."""
        self.full_screen = int(not self.full_screen)
        size = (self.table_width, self.table_height + MENU_HEIGHT)
        try:
            if self.full_screen:
                self._display = None
                try:
                    if not self.change_display:
                        raise pygame.error("no display change")
                    self.window = pygame.display.set_mode(FULL_SCREEN_MODE, pygame.FULLSCREEN)
                except pygame.error:
                    self.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                self.window = self._open_window(size)
        except pygame.error as exc:
            log.warning("Full screen not available: %s", exc)
            self.full_screen = 0
            self.window = self._open_window(size)

    def _open_window(self, size: tuple[int, int]) -> pygame.Surface:
        """Opens a resizable window WINDOW_SCALE times `size` (shrunk to fit
        the desktop) and returns a `size` surface to draw on; `_present`
        scales it into the window."""
        try:
            desk_w, desk_h = pygame.display.get_desktop_sizes()[0]
        except (IndexError, pygame.error):
            desk_w, desk_h = size
        scale = max(1.0, min(WINDOW_SCALE, desk_w * 0.95 / size[0], desk_h * 0.85 / size[1]))
        self._display = pygame.display.set_mode((round(size[0] * scale), round(size[1] * scale)), pygame.RESIZABLE)
        return pygame.Surface(size).convert()

    def _view_rect(self) -> pygame.Rect:
        """Where the drawing surface lands in the window: as large as fits,
        aspect kept, centred."""
        dw, dh = self._display.get_size()
        lw, lh = self.window.get_size()
        scale = min(dw / lw, dh / lh)
        w, h = round(lw * scale), round(lh * scale)
        return pygame.Rect((dw - w) // 2, (dh - h) // 2, w, h)

    def _present(self) -> None:
        if self._display is not None:
            self._display = pygame.display.get_surface()
            rect = self._view_rect()
            self._display.fill((0, 0, 0))
            self._display.blit(pygame.transform.smoothscale(self.window, rect.size), rect)
        pygame.display.flip()

    def _to_screen(self, pos: tuple[int, int]) -> tuple[int, int]:
        """A window position in the drawing surface's pixels."""
        if self._display is None:
            return pos
        rect = self._view_rect()
        lw, lh = self.window.get_size()
        return (pos[0] - rect.x) * lw // rect.w, (pos[1] - rect.y) * lh // rect.h

    def _screen_scale(self) -> float:
        return 1.0 if self._display is None else self._view_rect().w / self.window.get_width()

    def _minimize(self) -> None:
        """Esc: leave full screen, then SC_MINIMIZE."""
        if self.full_screen:
            self._toggle_full_screen()
        try:
            pygame.display.iconify()
        except pygame.error as exc:
            log.warning("Can't minimize: %s", exc)

    def _modal(self) -> bool:
        """The menu loop and the dialog boxes block the original's message
        loop, so nothing ticks while they're open."""
        return self.menu.is_open or self.dialog is not None or self.about_open

    def _next_high_score_entry(self) -> None:
        """FUN_0101479b's DialogBoxParamA per qualifying player, one at a
        time (each ranked against the table as it stands)."""
        if self.dialog is not None or self.game is None:
            return
        if not self.game.pending_entries:
            if self.game.after_entries is not None:
                self.game.after_entries()
            return
        score, name = self.game.pending_entries.pop(0)
        rank = self.game.high_scores.rank(score)
        if rank >= 0:
            self.dialog = HighScoreDialog(self.game.high_scores, score=score, rank=rank, name=name)

    def _save_settings(self) -> None:
        """FUN_0101566e (high scores) and FUN_010055f3 (options) at exit."""
        if self.game is not None:
            self.game.high_scores.save()
        options = {
            "Sounds": self.sounds_on,
            "Music": self.music_on,
            "FullScreen": self.full_screen,
            "Players": self.players,
        }
        options.update(zip(OPTION_NAMES, self.keys, strict=True))
        save_options(options)

    # -- table events -----------------------------------------------------
    def _serve(self) -> None:
        """The plunger's 0x3f7: the ball reset and put on the serve point,
        the score object's ball-lost flag (+0x4e) cleared."""
        ball = Ball(position=self.layout.plunger_rest.copy(), radius=self.layout.ball_radius)
        self.world.balls = [ball]
        self.ball = ball
        if self.game is not None:
            self.game.ball_lost = 0
            # FUN_01014d59: a tilt still standing is lifted (its "TILT!" box
            # cleared) and the nudge heat restarts at -2.0.
            if self.game.tilted:
                self.game.clear_text("info")
            self.game.tilted = 0
        self.tilt_heat = -2.0
        debug_log.event(self.frame, "SERVE", pos=ball.position)

    def _on_bumper_hit(self, circle: Circle) -> None:
        if self.game is not None:
            self.game.bumper_hit(circle.name, circle.cooldown)
        debug_log.event(self.frame, "BUMPER_HIT", name=circle.name, score=self.score)

    def _on_sink_eject(self, sink) -> None:
        debug_log.event(self.frame, "SINK_EJECT", name=sink.name, pos=self.ball.position, vel=self.ball.velocity)

    def _on_ball_drained(self, ball: Ball) -> None:
        debug_log.event(self.frame, "DRAIN", pos=ball.position, balls_left=self.balls_left)
        self.world.balls = []
        if self.game is not None:
            self.game.drain()
        else:
            self._serve()

    @property
    def score(self) -> int:
        return self.game.score if self.game is not None else 0

    @property
    def balls_left(self) -> int:
        return self.game.balls if self.game is not None else 1

    @balls_left.setter
    def balls_left(self, value: int) -> None:
        if self.game is not None:
            self.game.balls = value

    @property
    def tilted(self) -> bool:
        return bool(self.game.tilted) if self.game is not None else False

    # -- main loop ------------------------------------------------------
    def run(self) -> None:
        """WinMain's loop: the table only ticks while the window has focus
        (WM_SETFOCUS / WM_KILLFOCUS), the game isn't paused and no menu or
        dialog is open (they block the loop); a tick is as long as the real
        time since the last one."""
        last = pygame.time.get_ticks()
        while self.running:
            self._handle_events()
            self._next_high_score_entry()
            if self.dragging:
                self._drag_ball()
            now = pygame.time.get_ticks()
            if not (self._first_game_ms > 0 or (self.focused and not self._modal())):
                last = now  # DAT_01024ff4: the clock restarts when ticking resumes
            elif now == last:
                pygame.time.wait(8)  # Sleep(8): no time has passed
                continue
            else:
                # Each tick gets the real elapsed ms (FUN_01014bf9 clamps
                # it to 100); there is no fixed frame rate.
                self._update((now - last) / 1000.0)
                last = now
            self._draw()
        self._save_settings()
        pygame.quit()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if self._first_game_ms > 0 and event.type != pygame.QUIT:
                continue  # WinMain's 2 s PeekMessage loop throws input away
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.MOUSEWHEEL and isinstance(self.dialog, KeyMapperDialog):
                self.dialog.wheel(event.y)
            elif event.type == pygame.WINDOWFOCUSGAINED:
                # WM_ACTIVATEAPP (on): the music restarts unless paused.
                debug_log.event(self.frame, "FOCUS_GAINED")
                self.focused = True
                if self.game is not None and not self.game.paused:
                    self._restart_music()
            elif event.type == pygame.WINDOWFOCUSLOST:
                # WM_KILLFOCUS: 0x3f2 to every object (FUN_010156c1);
                # WM_ACTIVATEAPP (off): full screen off, the music stopped.
                debug_log.event(self.frame, "FOCUS_LOST")
                self.focused = False
                if self.game is not None:
                    self.game.focus_lost()
                if self.full_screen:
                    self._toggle_full_screen()
                self.audio.stop_effects()  # FUN_01006b8a: WaveMixActivate(FALSE)
                self.audio.stop_music()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._click(self._to_screen(event.pos))
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.dragging:
                self.dragging = False
                pygame.mouse.set_visible(True)
                pygame.event.set_grab(False)
            elif event.type == pygame.MOUSEMOTION:
                if not self.full_screen:
                    self.menu.hover(self._to_screen(event.pos))
            elif event.type == pygame.KEYDOWN:
                debug_log.event(self.frame, "KEYDOWN", key=pygame.key.name(event.key))
                if self.dialog is not None:
                    self.dialog.key(event)
                    if self.dialog.done:
                        self.dialog = None
                    continue
                if self.about_open:
                    if event.key in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_SPACE):
                        self.about_open = False
                    continue
                if self.menu.is_open:
                    if event.key == pygame.K_ESCAPE:
                        self.menu.close()
                    continue
                self._key_down(event.key)
            elif event.type == pygame.KEYUP:
                debug_log.event(self.frame, "KEYUP", key=pygame.key.name(event.key))
                if not self._modal():
                    self._key_up(event.key)

    def _click(self, pos: tuple[int, int]) -> None:
        if self.dialog is not None:
            self.dialog.click(pos)
            if self.dialog.done:
                self.dialog = None
            return
        if self.about_open:
            self.about_open = False
            return
        if not self.full_screen and self.menu.click(pos):
            return
        if self.game is None:
            return
        if self.game.mode == 0:
            self._startup_input()  # WM_LBUTTONDOWN -> FUN_01014743(-1)
        elif self.game.debug_mode:
            # "hidden test": the cursor is hidden and captured; while the
            # button is held each loop sets the ball's velocity to 30 x the
            # mouse movement (FUN_01014d8e), the cursor put back each time.
            self.dragging = True
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
            pygame.mouse.get_rel()

    def _drag_ball(self) -> None:
        """FUN_01014d8e(anchor.x - cursor.x, cursor.y - anchor.y), in the
        600x416 screen's pixels."""
        rx, ry = pygame.mouse.get_rel()
        scale = self._screen_scale()
        self.ball.velocity = Vec2(-rx / scale * 30.0, ry / scale * 30.0)

    def _key_down(self, key: int) -> None:
        """WM_KEYDOWN (FUN_01007a3e): the table keys first (FUN_01015072,
        not for auto-repeats -- pygame sends none), then Esc / F1..F4 / F8,
        then the "hidden test" window keys."""
        vk = vk_of(key, pygame.key.get_mods())
        self._table_key_down(vk)
        if vk == 0x1B:
            self._minimize()
        elif vk == 0x71:
            self._new_game(demo=False)
        elif vk == 0x72:
            if self.game is not None:
                self._toggle_pause()
        elif vk == 0x73:
            self._toggle_full_screen()
        elif vk == 0x77:
            self._player_controls()
        elif key == pygame.K_d and vk not in self.keys:
            self.debug_draw = not self.debug_draw  # this port's own overlay
        if self.game is not None and self.game.debug_mode:
            if vk == 0x48:
                self.frame_graph = True
            elif vk == 0x59:
                pygame.display.set_caption("Pinball")
                self.fps_title = not self.fps_title
            elif vk == 0x70:
                self._update(0.010, forced=True)  # FUN_01014bf9(10)
            elif vk == 0x7E:
                self.game.paused = int(not self.game.paused)  # DAT_01024fd8, silently

    def _table_key_down(self, vk: int) -> None:
        """FUN_01015072."""
        game = self.game
        if game is None or game.paused or game.demo:
            return
        if game.mode != 1:
            self._startup_input()
            return
        game.type_key(vk)
        keys = self.keys
        if vk == keys[LEFT_FLIPPER]:
            game.score_message(1000)
            return
        if vk == keys[RIGHT_FLIPPER]:
            game.score_message(0x3EA)
        elif vk == keys[PLUNGER]:
            game.score_message(0x3EC)
            return
        elif vk in (keys[BUMP_LEFT], keys[BUMP_RIGHT], keys[BUMP_BOTTOM]):
            if not game.tilted:
                self._nudge(vk)
            return
        if game.debug_mode:
            self._debug_key(vk)

    def _debug_key(self, vk: int) -> None:
        """FUN_01015072's "hidden test" keys: B puts the first inactive ball
        in play at (1, 1) at rest, H opens the high-score entry with
        1,000,000,000 at rank 2, R promotes (FUN_0100e111); F11 is an empty
        function and F12 only repaints every sprite (both no-ops here). M's
        "Mem:" box shows the original allocator's byte count, which has no
        counterpart here (not ported)."""
        game = self.game
        if vk == 0x42:
            ball = self.ball
            ball.position = Vec2(1.0, 1.0)
            ball.velocity = Vec2(0.0, 0.0)
            ball.z = ball.radius
            ball.alive, ball.held = True, False
            self.world.balls = [ball]
        elif vk == 0x48:
            self.dialog = HighScoreDialog(game.high_scores, score=1_000_000_000, rank=1, name=STRINGS[26])
        elif vk == 0x52:
            game.cheat_rank()

    def _key_up(self, key: int) -> None:
        """WM_KEYUP -> FUN_010152e4 (playing, not paused, no demo)."""
        game = self.game
        if game is None or game.mode != 1 or game.paused or game.demo:
            return
        vk = vk_of(key, pygame.key.get_mods())
        keys = self.keys
        if vk == keys[LEFT_FLIPPER]:
            game.score_message(0x3E9)
        elif vk == keys[RIGHT_FLIPPER]:
            game.score_message(0x3EB)
        elif vk == keys[PLUNGER]:
            game.score_message(0x3ED)
        elif vk in (keys[BUMP_LEFT], keys[BUMP_RIGHT], keys[BUMP_BOTTOM]):
            self._undo_nudge(vk)

    def _startup_input(self, elapsed_ms: int = -1) -> bool:
        """FUN_01014743: in the startup modes (3 then 4) the table waits
        5000 ms, or for any key / click, before play (mode 1); returns
        whether the tick is skipped."""
        game = self.game
        if game is None or game.mode in (1, 2):
            return False
        if game.mode in (3, 4):
            self._startup_ms -= elapsed_ms
            if self._startup_ms >= 0 and elapsed_ms >= 0:
                return True
            game.set_mode(4 if game.mode == 3 else 1)
            self._startup_ms = STARTUP_WAIT_MS
            self._update_menu()
        return True

    def _set_flipper(self, flipper, sprite, pressed: bool) -> None:
        if flipper.pressed == pressed:
            return
        flipper.pressed = pressed
        # 0x101c178 -> FUN_0101bf98: the edge starts its swing at the game time.
        flipper.message(1 if pressed else 2, self.world.time)
        if self.game is not None and sprite is not None:
            self.game.flipper(sprite.name, pressed)
            anim = self.flipper_anims.get(sprite.name)
            if anim is not None:
                anim.message(1 if pressed else 2)

    def _press_plunger(self) -> None:
        if self.plunger is None or self.plunger.pulling:
            return
        self.plunger.press()
        if self.game is not None:
            self.game.play_ref("plunger", 406)

    def _release_plunger(self) -> None:
        if self.plunger is None or not self.plunger.pulling:
            return
        debug_log.event(self.frame, "LAUNCH", kick=round(self.plunger.kick, 1))
        self.plunger.release()
        if self.game is not None:
            self.game.play_ref("plunger", 1101)

    def _nudge(self, key: int) -> None:
        """FUN_01014fa4 / FUN_01014f52 / FUN_01015024: the nudge
        FUN_01014dcf((2, 1) left, (-2, 1) right, (0, 1) bottom), then the
        shared 0.4 s timer is replaced by one that undoes this nudge
        (FUN_01014f20 / FUN_01014eee / FUN_01014ff6), and its flag set. An
        earlier nudge whose timer this cancels stays in until its key-up."""
        keys = self.keys
        if key == keys[BUMP_LEFT]:
            call = c.NUDGE_CALL_LEFT
        elif key == keys[BUMP_RIGHT]:
            call = c.NUDGE_CALL_RIGHT
        else:
            call = c.NUDGE_CALL_BOTTOM
        self._nudge_call(*call)
        if self.game is not None:
            if self._nudge_timer:
                self.game.timers.cancel(self._nudge_timer)
            self._nudge_timer = self.game.timers.schedule(c.NUDGE_AUTO_CANCEL_SECONDS, lambda: self._undo_nudge(key))
        self._nudge_active[key] = call

    def _undo_nudge(self, key: int) -> None:
        """Key-up or the timer: if the nudge is in, FUN_01014dcf(-x, -y)."""
        call = self._nudge_active.pop(key, None)
        if call is not None:
            self._nudge_call(-call[0], -call[1])

    def _nudge_call(self, x: float, y: float) -> None:
        """FUN_01014dcf(x, y): (x, y) * 0.5 added to every free ball's
        velocity, and the table image moved."""
        ball = self.ball
        if ball.alive and not ball.held:
            ball.velocity = ball.velocity + Vec2(x * 0.5, y * 0.5)
        self._shift_table(Vec2(x, y))

    def _shift_table(self, call: Vec2) -> None:
        """FUN_01014dcf(x, y) moves the table image by FUN_01013a8f."""
        dx, dy = nudge_shift(call.x, call.y)
        self.table_shift = (self.table_shift[0] + dx, self.table_shift[1] + dy)

    def _count_frame(self, elapsed_ms: int) -> None:
        """WinMain's debug counters, every tick: with "Y" on, every 300
        ticks the caption becomes "Frames/sec = %02.02f"; with "H" too, each
        tick adds a 1x10 column (value elapsed ms + 10, at most 249) to a
        300x10 strip shown at the screen's top-left every 300 ticks."""
        if not self.fps_title:
            self._fps_frames = 0
            self._fps_since = pygame.time.get_ticks()
            return
        if self.frame_graph:
            if self._graph is None:
                # First use: WinMain loads its gradient palette for the
                # whole screen (FUN_010043b9) and creates the strip.
                self._graph_palette = debug_strip_palette()
                if self.renderer is not None:
                    self.renderer.set_palette(self._graph_palette)
                self._graph = pygame.Surface((300, 10))
                self._graph.fill((0, 0, 0))
            value = min(elapsed_ms + 10, 0xF9)
            self._graph.fill(self._graph_palette[value], (299 - self._fps_frames, 0, 1, 10))
        self._fps_frames += 1
        if self._fps_frames >= 300:
            now = pygame.time.get_ticks()
            elapsed = max(1, now - self._fps_since)
            pygame.display.set_caption("Frames/sec = %02.02f" % (300.0 / (elapsed * 0.001)))
            self._fps_since = now
            self._fps_frames = 0
            if self._graph is not None:
                self._graph_shown = self._graph.copy()
                self._graph.fill((0, 0, 0))

    def _update_tilt_heat(self, dt: float) -> None:
        """FUN_01014bf9: heat rises 4/s while any nudge is in, otherwise falls
        1/s (floored at 0); untilted, above 0.5 the info box says
        "Careful..." (2 s), above 1.0 the table tilts (FUN_01017791)."""
        if self._nudge_active:
            self.tilt_heat += c.TILT_HEAT_RISE_RATE * dt
        else:
            self.tilt_heat = max(0.0, self.tilt_heat - c.TILT_HEAT_DECAY_RATE * dt)
        if self.game is None or self.game.tilted:
            return
        if self.tilt_heat > c.TILT_HEAT_WARN_THRESHOLD:
            self.game.text("info", 25, 2.0)
        if self.tilt_heat > c.TILT_HEAT_TRIGGER_THRESHOLD and self.game.tilt():
            debug_log.event(self.frame, "TILT")

    def _update(self, dt: float, forced: bool = False) -> None:
        if self._first_game_ms > 0:
            self._first_game_ms -= dt * 1000.0
            if self._first_game_ms <= 0:
                self._first_game_ms = 0
                self._start_first_game()
            return
        dt = min(dt, 0.1)  # FUN_01014bf9 clamps a frame to 100 ms
        if self.game is not None and ((self.game.paused and not forced) or self._startup_input(round(dt * 1000))):
            return
        self._count_frame(round(dt * 1000))
        self.world.tilted = self.tilted
        self.world.step(dt)
        if self.plunger is not None:
            self.plunger.update(dt)
        layout = self.layout
        for entity in (
            *layout.kickbacks,
            *layout.sinks,
            *layout.kickouts,
            *layout.ramp_holes,
            *layout.wall_targets,
            *layout.rollovers,
            *layout.switches,
        ):
            entity.update(dt)
        if layout.center_post is not None:
            layout.center_post.update(dt)
        if self.game is not None:
            self.game.update(dt)
            self._update_tilt_heat(dt)
            self.world.tilted = self.tilted
        if self.frame % POSITION_LOG_INTERVAL == 0:
            debug_log.event(
                self.frame,
                "BALL",
                pos=(round(self.ball.position.x, 3), round(self.ball.position.y, 3)),
                vel=(round(self.ball.velocity.x, 2), round(self.ball.velocity.y, 2)),
                mask=self.ball.mask,
                alive=self.ball.alive,
            )
        self.frame += 1

    # -- rendering --------------------------------------------------------
    def _draw(self) -> None:
        if self.renderer is not None:
            self.renderer.shift = self.table_shift
            self._sync_sprites()
            texts = self._texts()
            game = self.game
            balls = game.balls
            self.renderer.compose(
                ball=self._visible_ball(),
                score=self.score,
                # FUN_010175aa: ball (3 - balls left) + 1, blank below 1.
                ball_number=(game.balls_per_game - balls + 1) if balls >= 1 else None,
                player=game.player_number,
                texts=texts,
            )
            self.scene.blit(self.renderer.surface, (0, 0))
            self.renderer.draw_fallback_text(self.scene, texts)
        else:
            self._draw_vector_fallback()

        if self.debug_draw:
            self._draw_debug_overlay()
            hint = self.font.render("D: hide collision overlay", True, (255, 120, 120))
            self.scene.blit(hint, (6, self.scene.get_height() - 20))

        if self.fps_title and self._graph_shown is not None:
            self.scene.blit(self._graph_shown, (0, 0))
        self.window.fill((0, 0, 0))
        self.window.blit(self.scene, self._scene_origin())
        if self.dialog is not None:
            self.dialog.draw(self.window)
        if self.about_open:
            self._draw_about()
        if not self.full_screen:
            self.menu.draw(self.window)
        self._present()

    def _scene_origin(self) -> tuple[int, int]:
        """Windowed: the screen right under the menu bar. Full screen: the
        600x416 screen centred, unscaled (FUN_010038f8)."""
        if not self.full_screen:
            return 0, MENU_HEIGHT
        width, height = self.window.get_size()
        return (width - self.scene.get_width()) // 2, (height - self.scene.get_height()) // 2

    def _draw_about(self) -> None:
        """Help > About Pinball: DIALOG_1 ("3D-Pinball for Windows",
        "Version 1.0", OK) with the Maxis credit, string 101."""
        font = pygame.font.Font(None, 20)
        lines = ["3D-Pinball for Windows", "Version 1.0", "", *STRINGS[101].split("\n"), "", "OK"]
        w = max(font.size(line)[0] for line in lines) + 40
        h = 22 * len(lines) + 20
        x = (self.window.get_width() - w) // 2
        y = (self.window.get_height() - h) // 2
        pygame.draw.rect(self.window, (192, 192, 192), (x, y, w, h))
        pygame.draw.rect(self.window, (128, 128, 128), (x, y, w, h), 1)
        for i, line in enumerate(lines):
            text = font.render(line, True, (0, 0, 0))
            self.window.blit(text, (x + (w - text.get_width()) // 2, y + 10 + 22 * i))

    def _texts(self) -> dict[str, str | None]:
        if self.game is None:
            return {}
        return {"info_text_box": self.game.info_text, "mission_text_box": self.game.mission_text}

    def _visible_ball(self) -> tuple[Vec2, float] | None:
        """FUN_01014a68 repaints a ball only while its active byte is set: a
        sink's capture clears it (FUN_010184ed), a kickout or the ramp hole
        holds the ball but keeps it set."""
        in_ramp_hole = any(hole.held_ball is self.ball for hole in self.layout.ramp_holes)
        in_kickout = any(kickout.held_ball is self.ball for kickout in self.layout.kickouts)
        if self.ball.alive and (not self.ball.held or in_ramp_hole or in_kickout):
            return self.ball.position, self.ball.z
        return None

    def _sync_sprites(self) -> None:
        """Each object's sprite from its state, per its handler's own draw
        calls (see render.py and PHYSICS_SPEC_14.md)."""
        sprites = self.renderer.by_name
        layout = self.layout

        def show(name: str, index: int | None) -> None:
            sprite = sprites.get(name)
            if sprite is not None:
                sprite.set_bitmap(None if index is None else min(index, len(sprite.frames) - 1))

        def frame(name: str, index: int) -> None:
            sprite = sprites.get(name)
            if sprite is not None:
                sprite.set_frame(max(0, min(index, len(sprite.frames) - 1)))

        if self.game is not None:
            for name, light in self.game.lights.items():
                show(name, light.shown)  # FUN_01009ae3 / FUN_0100996f
            for name, bumper in self.game.bumpers.items():
                frame(name, bumper.frame)  # FUN_01015d0f / FUN_01015cb2
        for flag in layout.flags:
            frame(flag.name, flag.frame)  # FUN_01015f4e
        for target in layout.wall_targets:
            if target.drop_time > 0:
                frame(target.name, 0 if target.up else 1)  # FUN_01016230
            else:
                show(target.name, 0 if target.up else None)  # FUN_010160f4 / FUN_010160b3
        for rollover in layout.rollovers:
            show(rollover.name, 0 if rollover.shown else None)
        for switch in layout.switches:
            show(switch.name, 0 if switch.lit else None)  # FUN_01017fde / FUN_01015ace
        for gate in layout.gates:
            show(gate.name, None if gate.is_open else 0)  # FUN_010163db
        if layout.center_post is not None:
            show(layout.center_post.name, 0 if layout.center_post.up else None)  # FUN_0101631c
        for kickback in layout.kickbacks:
            if kickback.frame is None:
                show(kickback.name, None)  # FUN_010166f6
            else:
                frame(kickback.name, kickback.frame)  # FUN_0101663f
        plunger = sprites.get("plunger")
        if self.plunger is not None and plunger is not None:
            # FUN_01017314 while pulling; 0x3ed back to frame 0.
            count = len(plunger.frames)
            pull = self.plunger.kick / self.plunger.max_kick if self.plunger.pulling else 0.0
            plunger.set_frame(math.floor((count - 1) * pull))

    def _px(self, p: Vec2) -> tuple[int, int]:
        camera = self.renderer.camera if self.renderer is not None else self.camera
        s = camera.to_screen(p)
        return int(s.x) + self.table_shift[0], int(s.y) + self.table_shift[1]

    def _draw_world_circle(self, color, center: Vec2, radius: float, width: int = 1) -> None:
        camera = self.renderer.camera if self.renderer is not None else self.camera
        px_radius = max(1, round(radius * camera.px_per_unit(center)))
        pygame.draw.circle(self.scene, color, self._px(center), px_radius, width)

    def _draw_debug_overlay(self) -> None:
        """Every collision shape projected onto the real table art -- toggle
        with D. Grey = another collision layer, cyan = one-sided line, yellow
        = trip line (pass sensors, ramp edges)."""
        RED = (255, 40, 40)
        CYAN = (0, 220, 255)
        GREY = (110, 110, 110)
        YELLOW = (230, 200, 0)
        for seg in self.world.segments:
            if not seg.mask & self.ball.mask:
                color = GREY
            elif not seg.active:
                continue
            else:
                color = CYAN if seg.one_sided else RED
            pygame.draw.line(self.scene, color, self._px(seg.a), self._px(seg.b), 1)
        for line in self.world.trip_lines:
            color = YELLOW if line.mask & self.ball.mask else GREY
            pygame.draw.line(self.scene, color, self._px(line.a), self._px(line.b), 1)
        for circle in self.world.circles:
            self._draw_world_circle(RED if circle.mask & self.ball.mask else GREY, circle.center, circle.radius)
        for flipper in (self.left_flipper, self.right_flipper):
            pygame.draw.line(self.scene, RED, self._px(flipper.pivot), self._px(flipper.tip()), 1)
            self._draw_world_circle(RED, flipper.pivot, flipper.radius)
            self._draw_world_circle(RED, flipper.tip(), flipper.tip_radius)
        for kickout in self.layout.kickouts:
            color = (255, 0, 255) if kickout.active else GREY
            self._draw_world_circle(color, kickout.center, kickout.field_radius)
            self._draw_world_circle(color, kickout.center, kickout.capture_radius)
        if self.world.drain_y != math.inf:
            y = self.world.drain_y
            pygame.draw.line(self.scene, (0, 150, 255), self._px(Vec2(-10.0, y)), self._px(Vec2(10.0, y)), 1)

    def _draw_vector_fallback(self) -> None:
        self.scene.fill((10, 10, 30))
        for seg in self.world.segments:
            pygame.draw.line(self.scene, (200, 200, 220), self._px(seg.a), self._px(seg.b), 2)
        for circle in self.world.circles:
            color = (255, 120, 40) if circle.kick > 0 else (150, 150, 170)
            self._draw_world_circle(color, circle.center, circle.radius, 0)
        for flipper in self.world.flippers:
            pygame.draw.line(self.scene, (220, 220, 60), self._px(flipper.pivot), self._px(flipper.tip()), 4)
