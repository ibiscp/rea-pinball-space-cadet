"""The original's control layer: lights, light groups, the score object and
the control-table handlers ("listeners"), ported from Pinball.exe.

Every table object reports events (0x3f = scored hit, 0x3c = a timer ran
out, ...) through FUN_01011ec9 to the handler the control table at
0x1023ef0 linked it to, and then to the mission dispatcher FUN_01011bb5
(see logic.Bus). The handlers drive the lights, award points through the
score object's FUN_01017526 (field multiplier, jackpot and bonus
accumulators) and message the physical objects (gates, sinks, kickouts,
targets, the plunger). Each handler below is named after its address and
the objects it serves, and follows the decompiled code line by line.

Lights are visual (logic.Light.shown): the renderer draws a light's frame
when lit. The two text boxes keep the original's message queue (TextBox);
`info_text` / `mission_text` are what each shows. The game flow -- new game,
players, the end of a ball, game over, high scores, pause and the demo --
is the score object's own handler, FUN_010187d6 (`score_message`).
"""

from __future__ import annotations

import logging
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import partout
from .entities import Sink, WallTarget
from .highscores import HighScores
from .logic import Bus, Light, LightGroup, Timers
from .missions import RANKS, Missions
from .projection import tagged_floats
from .scoring import SCORES
from .strings import STRINGS

if TYPE_CHECKING:
    from .ball import Ball
    from .demo import DemoPlayer
    from .table_data import TableLayout

log = logging.getLogger(__name__)

LIGHT_TYPE = 0x3EA  # FUN_0100ad21
LIGHT_GROUP_TYPE = 0x402  # FUN_0100adb1
BUMPER_GROUP_TYPE = 0x404  # FUN_01018ffd
BARGRAPH_TYPE = 0x406  # FUN_0100ae72
SOUND_TYPE = 0x407  # FUN_0101aa18
MULTIPLIERS = (1, 2, 3, 5, 10)  # DAT_01024758, indexed by score+0x126
SCORE_CAP = 5_000_000  # jackpot / bonus accumulators (FUN_01017526)


def _tag10(entry: partout.Entry) -> list[int]:
    variant = next((v for v in entry.variants if v.type_tag == 10), None)
    if variant is None:
        return []
    return [int.from_bytes(variant.raw[i : i + 2], "little", signed=True) for i in range(0, len(variant.raw), 2)]


def _sprite_frames(pf: partout.PartoutFile, index: int) -> int:
    frames = 1
    for following in pf.entries[index + 1 :]:
        marker = next((v for v in following.variants if v.type_tag == 0), None)
        if marker is None or int.from_bytes(marker.raw, "little", signed=True) != 201:
            break
        frames += 1
    return frames


def sound_files(pf: partout.PartoutFile) -> dict[int, str]:
    """PINBALL.DAT entry index -> wav file name, for every sound entry
    (type-0 value 202 with a type-9 path), the targets of the tag-1100 /
    304 / 406 sound references FUN_0100901f resolves."""
    files: dict[int, str] = {}
    for index, entry in enumerate(pf.entries):
        marker = next((v for v in entry.variants if v.type_tag == 0), None)
        path = next((v for v in entry.variants if v.type_tag == 9), None)
        if marker is None or path is None or int.from_bytes(marker.raw, "little", signed=True) != 202:
            continue
        files[index] = path.raw.split(b"\0")[0].decode("latin-1")
    return files


@dataclass(eq=False)
class Bargraph(LightGroup):
    """`fuel_bargraph` (type 0x406, FUN_0100ae72; messages FUN_0100ab28): a
    light group with a level 0..2n-1 (+0x92). Message 0x2d sets the level:
    members 0..level/2 lit, the top one flashing on even levels, and a
    decay timer from tag 904's per-level times; when it fires the level
    drops by one (notifying 0x3c), or at 0 the bar goes dark and notifies
    0x2f (out of fuel)."""

    step_times: list[float] = field(default_factory=list)
    level: int = 0
    _decay: int = 0

    def message(self, code: int, value: float = 0.0) -> int:
        if code == 0x25:
            return self.level
        if code == 0x2D:
            if self._decay:
                self.timers.cancel(self._decay)
                self._decay = 0
            level = min(math.floor(value), len(self.lights) * 2 - 1)
            if level < 0:
                super().message(0x14)
                self.level = 0
            else:
                super().message(0x2D, float(level // 2))
                if level % 2 == 0:
                    super().message(0x2E)
                if self.step_times:
                    self._decay = self.timers.schedule(self.step_times[level], self._decay_step)
                self.level = level
            return 0
        if code == 0x3F3:
            self.reset()
            return 0
        if code == 0x400:
            self.reset()
            return super().message(0x400)
        return super().message(code, value)

    def reset(self) -> None:
        if self._decay:
            self.timers.cancel(self._decay)
            self._decay = 0
        self.level = 0
        super().reset()

    def _decay_step(self) -> None:
        """FUN_0100aad9."""
        self._decay = 0
        if self.level:
            self.message(0x2D, float(self.level - 1))
            self.bus.notify(0x3C, self)
        else:
            self.message(0x14)
            self.bus.notify(0x2F, self)


@dataclass(eq=False)
class Bumper:
    """A bumper's own state (FUN_0101944a; messages FUN_01015d79): its
    level (+0x4e, 0..3) picks both its score (the listener's control-table
    entry) and its sprite pair (frames 2*level unlit / 2*level+1 lit). A
    kick (FUN_01015d0f) shows the lit frame and disables the kick for tag
    407 seconds (the physics Circle's cooldown). 0xb sets the level, 0xc /
    0xd step it; a change plays the up/down sound (tags 1100/1101) and
    notifies 0xb."""

    name: str
    frames: int
    bus: Bus
    level: int = 0
    data: int = 0
    lit_frame: bool = False
    on_sound: Callable[[str], None] | None = None
    # FUN_01015d0f, also run on a level change: lit frame + kick lockout.
    on_flash: Callable[[Bumper], None] | None = None

    @property
    def frame(self) -> int:
        return self.level * 2 + (1 if self.lit_frame else 0)

    def message(self, code: int, value: float = 0.0) -> int:
        top = (self.frames - 1) // 2
        if code == 0xB:
            level = math.floor(value)
            if (self.frames - 1) < level * 2:
                level = top
            level = max(level, 0)
            if level != self.level:
                if self.on_sound:
                    self.on_sound("up" if self.level <= level else "down")
                self.level = level
                if self.on_flash:
                    self.on_flash(self)
                self.bus.notify(0xB, self)
        elif code == 0xC:
            self.message(0xB, float(min(self.level + 1, top)))
        elif code == 0xD:
            self.message(0xB, float(max(self.level - 1, 0)))
        elif code == 0x400:
            self.level = 0
            self.data = 0
            self.lit_frame = False
        return 0


@dataclass(eq=False)
class BumperGroup:
    """`attack_bumpers` / `launch_bumpers` (type 0x404, FUN_01018ffd;
    messages FUN_010159f9): 0x30 starts a one-shot timer that notifies 0x3d;
    other codes (below 0x3f0, or above 0x3f3 except 0x3fc/0x3fe) go to every
    member bumper, last first."""

    name: str
    timers: Timers
    bus: Bus
    members: list[Bumper]
    data: int = 0
    _timer: int = 0

    def message(self, code: int, value: float = 0.0) -> int:
        if code == 0x30:
            if self._timer:
                self.timers.cancel(self._timer)
                self._timer = 0
            if value > 0.0:
                self._timer = self.timers.schedule(value, self._expire)
        elif code < 0x3F0 or (code > 0x3F3 and code not in (0x3FC, 0x3FE)):
            for bumper in reversed(self.members):
                bumper.message(code, value)
        return 0

    def _expire(self) -> None:
        self._timer = 0
        self.bus.notify(0x3D, self)

    @property
    def level(self) -> int:
        return self.members[0].level if self.members else 0


@dataclass(eq=False)
class PlungerControl:
    """The plunger's message side (FUN_010185ad): 0x3f8 = a new ball is
    coming -- its sound (tag 1100), the 0.96 s serve timer, and 0x3f8 to the
    listener; when the timer fires (0x3f7) the ball is put on the serve
    point and the listener hears 0x3f7."""

    name: str
    timers: Timers
    bus: Bus
    serve: Callable[[], None]
    sound: Callable[[], float] | None = None
    data: int = 0
    _timer: int = 0

    def message(self, code: int, value: float = 0.0) -> int:
        if code == 0x3F8:
            if self._timer:
                self.timers.cancel(self._timer)
            self._timer = self.timers.schedule(SERVE_DELAY, lambda: self.message(0x3F7))
            if self.sound:
                self.sound()
            self.bus.notify(0x3F8, self)
        elif code == 0x3F7:
            self._timer = 0
            self.serve()
            self.bus.notify(0x3F7, self)
        elif code == 0x400:
            if self._timer:
                self.timers.cancel(self._timer)
            self._timer = 0
        return 0


@dataclass(eq=False)
class DrainControl:
    """The `drain` (type 0x3ef, FUN_0101a4b4; collision FUN_01018562): the
    ball touching its line is reset, the score object's "ball lost" flag is
    set, the listener hears 0x3f at once and 0x3c after tag 407 (1.82 s)."""

    name: str
    timers: Timers
    bus: Bus
    delay: float
    data: int = 0
    _timer: int = 0

    def hit(self) -> None:
        self._timer = self.timers.schedule(self.delay, self._expire)
        self.bus.notify(0x3F, self)

    def _expire(self) -> None:
        self._timer = 0
        self.bus.notify(0x3C, self)

    def message(self, code: int, value: float = 0.0) -> int:
        if code == 0x400 and self._timer:
            self.timers.cancel(self._timer)
            self._timer = 0
        return 0


SERVE_DELAY = 0.96  # float at 0x10024d4


@dataclass(eq=False)
class _Message:
    """FUN_01013af1: a queued text-box message. `expire_ms` (+0xc) is the
    game clock (DAT_01024f84, ms) plus trunc(seconds * 1000); -1 seconds =
    show until replaced."""

    text: str
    seconds: float
    expire_ms: float


@dataclass
class PlayerRecord:
    """One player's saved state in the score object (+0x6a + i*0x1c):
    score, billions, jackpot, balls, extra balls, locked balls."""

    score: int = 0
    billions: int = 0
    jackpot: int = 0
    balls: int = 0
    extra_balls: int = 0
    locked_balls: int = 0


# FUN_0100e1b0, the typed codes: key -> states it advances from (to +1)
CODE_STEPS: dict[int, tuple[int, ...]] = {
    ord("M"): (4, 0x3D, 0x51, 0x65, 0x79),
    ord("D"): (0x16, 0x17),
    ord("A"): (5, 0x3E, 0x52, 0x66, 0x7A),
    ord("E"): (3, 0x18, 0x1C, 0x2C),
    ord("I"): (1, 10, 0x15),
    ord("S"): (0xC, 0x1D, 0x2D),
    ord("N"): (2, 9, 0x19),
    ord("O"): (8, 0x2A),
    ord("T"): (0x1B, 6, 0x2B),
}
# key -> (state it needs, new state) pairs
CODE_JUMPS: dict[int, tuple[tuple[int, int], ...]] = {
    ord(" "): ((0x1A, 0x1B),),
    ord("1"): ((0, 0x3D),),
    ord("B"): ((0, 0x51),),
    ord("C"): ((0, 1), (0xB, 0xC)),
    ord("G"): ((0, 0x65),),
    ord("H"): ((0, 0x15),),
    ord("Q"): ((0, 0x29),),
    ord("R"): ((0, 0x79), (7, 8)),
    ord("U"): ((0x29, 0x2A),),
}


NO_TIMER = 0  # +0x3a = 0: nothing on screen is timing
FOREVER = -1  # +0x3a = -1: the shown message has no end


@dataclass(eq=False)
class TextBox:
    """`info_text_box` / `mission_text_box` (type 0x409): a FIFO of messages
    (+0x46 head, +0x4a tail) of which only the head is on screen, plus its
    end timer (+0x3a). FUN_010144b7 adds (or refreshes) a message,
    FUN_01014269 shows the head, FUN_010141e1 ends it and shows the next
    (then notifies 0x3c), FUN_01014143 clears the box and the queue."""

    name: str
    timers: Timers
    bus: Bus
    data: int = 0
    queue: list[_Message] = field(default_factory=list)
    shown: str | None = None
    _timer: int = NO_TIMER

    @property
    def now_ms(self) -> float:
        return self.timers.now * 1000.0

    @property
    def message_text(self) -> str | None:
        return self.shown

    def _cancel(self) -> None:
        if self._timer not in (NO_TIMER, FOREVER):
            self.timers.cancel(self._timer)

    def show(self, text: str | None, seconds: float) -> None:
        """FUN_010144b7."""
        if text is None:
            return
        if self.queue and text == self.queue[-1].text:
            tail = self.queue[-1]
            tail.seconds = seconds  # FUN_01013b82
            tail.expire_ms = self.now_ms + math.trunc(seconds * 1000.0)
            if tail is not self.queue[0]:
                return
            self._cancel()
            self._timer = self.timers.schedule(seconds, self._expire) if seconds != -1.0 else FOREVER
            return
        if self._timer == FOREVER:
            self.clear()
        self.queue.append(_Message(text, seconds, self.now_ms + math.trunc(seconds * 1000.0)))
        if self._timer == NO_TIMER:
            self._draw()

    def clear(self) -> None:
        """FUN_01014143."""
        self.shown = None
        self._cancel()
        self._timer = NO_TIMER
        self.queue.clear()

    def _draw(self) -> None:
        """FUN_01014269: drop messages that can't be shown (an endless one
        with others behind it, or one that ended over 2 s ago), then show
        the head for what is left of its time, at least 0.25 s."""
        self.shown = None
        while self.queue:
            head = self.queue[0]
            if head.seconds == -1.0:
                if len(self.queue) == 1:
                    self._timer = FOREVER
                    self.shown = head.text
                    return
            else:
                remaining = (head.expire_ms - self.now_ms) * 0.001  # FUN_01013b60
                if remaining >= -2.0:
                    self._timer = self.timers.schedule(max(remaining, 0.25), self._expire)
                    self.shown = head.text
                    return
            self.queue.pop(0)

    def _expire(self) -> None:
        """FUN_010141e1."""
        self._timer = NO_TIMER
        if self.queue:
            self.queue.pop(0)
            self._draw()
            self.bus.notify(0x3C, self)


class Game(Missions):
    """The score object (DAT_01025040) plus every control handler."""

    def __init__(
        self,
        pf: partout.PartoutFile,
        layout: TableLayout,
        play_file: Callable[[str], float] | None = None,
    ) -> None:
        self.pf = pf
        self.layout = layout
        self.timers = Timers()
        self.bus = Bus()
        self.bus.mission = self._mission
        self._play_file = play_file
        self.sound_files = sound_files(pf)
        self.objects: dict[str, object] = {}
        # Score object fields (offsets into DAT_01025040).
        self.score = 0  # +0x52
        self.score_billions = 0  # +0x56
        self.multiplier = 0  # +0x126, index into MULTIPLIERS
        self.score_offset = 0  # +0x12a
        self.reflex_value = 25000  # +0x12e, set on every new ball
        self.bonus = 25000  # +0x132 ("Crash Bonus" / bonus awarded)
        self.bonus_on = 0  # +0x136: points also accrue to the bonus
        self.jackpot = 20000  # +0x13a
        self.jackpot_on = 0  # +0x13e: points also accrue to the jackpot
        self.balls = 3  # +0x146
        self.extra_balls = 0  # +0x14e ("Shoot Again")
        self.multiball_balls = 0  # +0x152
        self.locked_balls = 0  # +0x156
        self.multiball = 0  # +0x15a
        self.replay_balls = 0  # +0x15e
        self.tilted = 0  # +0x172
        self.ball_lost = 0  # +0x4e
        self.ball_save_window = 0  # DAT_01025044
        self.rollover_bonus_lit = 0  # DAT_0102504c
        # Game flow (FUN_010187d6, PHYSICS_SPEC_15).
        self.balls_per_game = 3  # +0x14a
        self.player_count = 1  # +0xd6
        self.current_player = 0  # +0xda
        self.player_number = 1  # the player_number1 box's value
        # The four score boxes (+0x66 + i*0x1c: score1 and its three clones,
        # FUN_01013c48, all at score1's rectangle); -1 = no such player.
        self.boxes = [0, -1, -1, -1]
        self.records = [PlayerRecord() for _ in range(4)]
        self.cheated = 0  # +0x3e: no high score this game
        self.code_state = 0  # DAT_01025050, the typed-code state
        self.debug_mode = 0  # DAT_01024ff8 ("hidden test")
        self.mode = 0  # DAT_01025568 (FUN_0101461a): 1 play, 2 game over, 3/4 startup
        self.demo = 0  # DAT_01025570
        self.paused = 0  # DAT_01024fd8
        self._start_timer = 0  # +0x5a
        self._game_over_timer = 0  # +0x5e
        self._tilt_timer = 0  # +0x62
        # Set by the app: 1000..0x3ed go to the flippers and the plunger
        # (FUN_010187d6 forwards them to +0x2a / +0x2e / +0xde).
        self.on_input: Callable[[int], None] | None = None
        # A message straight to both flippers (a_flip1 / a_flip2's handler).
        self.on_flipper_message: Callable[[int], None] | None = None
        self.on_hide_ball: Callable[[], None] | None = None
        self.on_force_drain: Callable[[], None] | None = None
        self.on_broadcast: Callable[[int, float], None] | None = None
        self.demo_player: DemoPlayer | None = None
        # FUN_0101479b's name entries, handled by the app's high-score dialog
        # (the original's modal DialogBoxParamA).
        self.high_scores = HighScores()
        self.pending_entries: list[tuple[int, str]] = []
        self.after_entries: Callable[[], None] | None = None
        self._slots: dict[int, list] = {}
        self.info_box = TextBox("info_text_box", self.timers, self.bus)
        self.mission_box = TextBox("mission_text_box", self.timers, self.bus)
        self.events: list[tuple[str, object]] = []  # for the debug log
        self.ball: Ball | None = None
        self.on_serve: Callable[[], None] | None = None
        self._build_lights()
        self._build_bumpers()
        self._register_listeners()

    # -- construction -------------------------------------------------------
    def _manifest(self) -> list[tuple[int, int]]:
        manifest = self.pf.find("table_objects")
        stream = _tag10(manifest)
        return list(zip(stream[1::2], stream[2::2], strict=False))

    def _build_lights(self) -> None:
        pf = self.pf
        self.lights: dict[str, Light] = {}
        self.groups: dict[str, LightGroup] = {}
        by_index: dict[int, Light] = {}
        manifest = self._manifest()
        for type_id, index in manifest:
            if type_id != LIGHT_TYPE:
                continue
            entry = pf.entries[index]
            on = tagged_floats(entry, 900)
            off = tagged_floats(entry, 901)
            light = Light(
                entry.name,
                self.timers,
                self.bus,
                frames=_sprite_frames(pf, index),
                base_times=(on[0] if on else 0.1, off[0] if off else 0.1),
            )
            self.lights[entry.name] = light
            by_index[index] = light
        for type_id, index in manifest:
            if type_id not in (LIGHT_GROUP_TYPE, BARGRAPH_TYPE):
                continue
            entry = pf.entries[index]
            stream = _tag10(entry)
            members = [by_index[i] for i in stream[1:] if i in by_index] if stream and stream[0] == 1027 else []
            interval = tagged_floats(entry, 903)
            if type_id == BARGRAPH_TYPE:
                times = tagged_floats(entry, 904)
                group: LightGroup = Bargraph(
                    entry.name,
                    self.timers,
                    self.bus,
                    members,
                    interval=interval[0] if interval else 0.1,
                    step_times=list(times[: len(members) * 2]) if times else [],
                )
            else:
                group = LightGroup(entry.name, self.timers, self.bus, members, interval=interval[0] if interval else 0.1)
            group.reset()
            self.groups[entry.name] = group
        self.objects.update(self.lights)
        self.objects.update(self.groups)
        # The score object's +0x10a: FUN_0100adb1(score, 0), a group with
        # no entry of its own that every light (type 0x3ea) joins in
        # manifest order (FUN_0101aaf3).
        self.all_lights = LightGroup("", self.timers, self.bus, list(self.lights.values()), interval=0.0)

    def _build_bumpers(self) -> None:
        pf = self.pf
        self.bumpers: dict[str, Bumper] = {}
        by_index: dict[int, Bumper] = {}
        manifest = self._manifest()
        for type_id, index in manifest:
            entry = pf.entries[index]
            if type_id == 0x3ED:
                bumper = Bumper(entry.name, _sprite_frames(pf, index), self.bus)
                bumper.on_sound = lambda which, e=entry: self._entry_sound(e, 1100 if which == "up" else 1101)
                bumper.on_flash = self._bumper_flash
                self.bumpers[entry.name] = bumper
                by_index[index] = bumper
        self.objects.update(self.bumpers)
        for type_id, index in manifest:
            if type_id != BUMPER_GROUP_TYPE:
                continue
            entry = pf.entries[index]
            stream = _tag10(entry)
            members = [by_index[i] for i in stream[1:] if i in by_index] if stream and stream[0] == 1027 else []
            self.objects[entry.name] = BumperGroup(entry.name, self.timers, self.bus, members)

    def register(self, obj: object, sound_tag: int | None = None) -> None:
        """A physical table object (gate, target, sink, ...) the handlers
        message by name: it reports events through `notify`, and its own
        sound (`sound_tag`: 304 = +0x46, 406 = +0x4a, 1100 / 1101) is
        resolved from its PINBALL.DAT entry."""
        self.objects[obj.name] = obj
        if hasattr(obj, "notify"):
            obj.notify = self.bus.notify
        if sound_tag is not None and hasattr(obj, "sound"):
            ref = self.sound_ref(obj.name, sound_tag)
            obj.sound = (lambda i=ref: self.play_entry(i)) if ref is not None else None

    def sound_ref(self, name: str, tag: int) -> int | None:
        """The entry index of `name`'s sound reference `tag`: from its own
        type-10 stream, or for 406 also from its tag-400 preset
        (FUN_0100950a / FUN_01009349)."""
        entry = self.pf.find(name)
        if entry is None:
            return None
        stream = _tag10(entry)
        for i in range(0, len(stream) - 1, 2):
            if stream[i] == tag:
                return stream[i + 1]
        if tag == 406:
            for i in range(0, len(stream) - 1, 2):
                if stream[i] != 400:
                    continue
                preset = next((v for v in self.pf.entries[stream[i + 1]].variants if v.type_tag == 11), None)
                if preset is None:
                    return None
                values = struct.unpack(f"<{len(preset.raw) // 4}f", preset.raw)
                j = 0
                while j + 1 < len(values):
                    key = int(values[j])
                    if key == 406:
                        return int(values[j + 1])
                    j += 4 if key == 404 else 2
        return None

    def play_ref(self, name: str, tag: int) -> float:
        ref = self.sound_ref(name, tag)
        return self.play_entry(ref) if ref is not None else 0.0

    # -- primitives -------------------------------------------------------------
    def lit(self, name: str) -> bool:
        """FUN_0100c092."""
        obj = self.objects.get(name)
        return bool(obj is not None and obj.lit())

    def msg(self, name: str, code: int, value: float = 0.0) -> int:
        obj = self.objects.get(name)
        if obj is None or not hasattr(obj, "message"):
            return 0
        return obj.message(code, value) or 0

    def data(self, name: str) -> int:
        return getattr(self.objects.get(name), "data", 0)

    def set_data(self, name: str, value: int) -> None:
        obj = self.objects.get(name)
        if obj is not None:
            obj.data = value

    @staticmethod
    def score_of(obj: object, index: int) -> int:
        """vtable slot 2 (FUN_01015ef9): the object's control-table score
        `index`, or 0 past the end of its list."""
        scores = SCORES.get(getattr(obj, "name", ""), ())
        return scores[index] if 0 <= index < len(scores) else 0

    def add_score(self, points: int) -> int:
        """FUN_01017526."""
        if self.jackpot_on:
            self.jackpot = min(self.jackpot + points, SCORE_CAP)
        if self.bonus_on:
            self.bonus = min(self.bonus + points, SCORE_CAP)
        added = MULTIPLIERS[self.multiplier] * points + self.score_offset
        self.score += added
        if self.score > 1_000_000_000:
            self.score_billions += 1
            self.score -= 1_000_000_000
        self.boxes[self.current_player] = self.score  # FUN_01013c89(+0x32, score)
        return added

    def award(self, points: int) -> int:
        """FUN_0100c335: add `points` with no multiplier and without feeding
        the jackpot or bonus."""
        saved = (self.jackpot_on, self.bonus_on, self.multiplier)
        self.jackpot_on = self.bonus_on = self.multiplier = 0
        added = self.add_score(points)
        self.jackpot_on, self.bonus_on, self.multiplier = saved
        return added

    def text(self, box: str, string: int | str, seconds: float, *args: object) -> None:
        """FUN_010144b7 on info_text_box / mission_text_box."""
        message = STRINGS.get(string, "") if isinstance(string, int) else string
        if args:
            message = message.replace("%ld", "%d") % args
        (self.info_box if box == "info" else self.mission_box).show(message, seconds)
        self.events.append(("TEXT", message))

    def clear_text(self, box: str) -> None:
        """FUN_01014143."""
        (self.info_box if box == "info" else self.mission_box).clear()

    @property
    def info_text(self) -> str | None:
        return self.info_box.message_text

    @property
    def mission_text(self) -> str | None:
        return self.mission_box.message_text

    def play(self, wave: str) -> float:
        """A `soundwaveN` object's slot 5: play its sound (type-10 tag 1100)
        and return its length (file size * 9.0909e-05 s, FUN_0100901f)."""
        entry = self.pf.find(wave)
        if entry is None:
            return 0.0
        return self._entry_sound(entry, 1100)

    def _entry_sound(self, entry: partout.Entry, tag: int) -> float:
        stream = _tag10(entry)
        for i in range(0, len(stream) - 1, 2):
            if stream[i] == tag:
                return self.play_entry(stream[i + 1])
        return 0.0

    def play_entry(self, index: int) -> float:
        """FUN_01009895 for the sound entry `index`."""
        name = self.sound_files.get(index)
        if name is None:
            return 0.0
        self.events.append(("SOUND", name))
        if self._play_file is not None:
            return self._play_file(name)
        return 0.0

    def update(self, dt: float) -> None:
        self.timers.update(dt)

    # -- inputs from the app ------------------------------------------------
    def setup_controls(self, serve: Callable[[], None], drain_delay: float) -> None:
        self.objects["plunger"] = PlungerControl(
            "plunger", self.timers, self.bus, serve, sound=lambda: self.play_ref("plunger", 1100)
        )
        self.objects["drain"] = DrainControl("drain", self.timers, self.bus, drain_delay)

    def drain(self) -> None:
        self.ball_lost = 1
        self.objects["drain"].hit()

    # -- game flow: FUN_0101461a, FUN_010153ae, the score object's FUN_010187d6
    def set_mode(self, mode: int) -> None:
        """FUN_0101461a (the menu items it greys out aside): 1 = playing
        (the demo object follows DAT_01025570), 2 = game over (every light
        sparkles, 0x1d 1.4), 3 / 4 = the startup wait (5000 ms each)."""
        if mode == 1 and self.demo_player is not None:
            self.demo_player.active = bool(self.demo)
        elif mode == 2:
            self.all_lights.message(0x1D, 1.4)
        self.mode = mode

    def new_game(self, demo: bool, players: int) -> None:
        """FUN_010153ae: F2 / Game > New Game (demo = 0) or Game > Demo
        (demo = 1); the app restarts the music."""
        self.demo = int(demo)
        self.set_mode(1)
        self.score_message(0x3F6, float(players))

    def toggle_demo(self, players: int) -> None:
        """FUN_01015802 (Game > Demo): stop a running demo, else start one."""
        if self.demo:
            self.demo = 0
            self.score_message(0x400)
            self.set_mode(2)
            self.clear_text("mission")
            self.text("info", 24, -1.0)
            return
        self.new_game(True, players)

    def toggle_pause(self) -> None:
        """FUN_010156e4 (F3): both boxes cleared; pausing broadcasts 0x3f0
        and says "Game Paused / F3 to Resume"; resuming broadcasts 0x3f1 and
        says "F2 Starts New Game" after a game, else "Continue Play" for 5 s
        (nothing in a demo). The app stops / restarts the music and skips
        the tick while paused (the WinMain loop)."""
        self.paused = int(not self.paused)
        self.clear_text("info")
        self.clear_text("mission")
        if self.paused:
            self.score_message(0x3F0)
            self.text("info", 22, -1.0)
            return
        self.score_message(0x3F1)
        if not self.demo:
            if self.mode == 2:
                self.text("info", 24, -1.0)
            else:
                self.text("info", 23, 5.0)

    def focus_lost(self) -> None:
        """WM_KILLFOCUS -> FUN_010156c1: 0x3f2 (flippers, plunger let go)."""
        self.score_message(0x3F2)

    def broadcast(self, code: int, value: float = 0.0, *, forward: bool = False) -> None:
        """The score object's loops over its component list (+0xfe): 0x3f0
        .. 0x3f2, 0x400 and 0x3fe last first, 0x3f3 and 0x3fc first first.
        The list is the construction order; this port's object dict is
        built in a similar but not identical order (INFERRED harmless:
        every handler here acts on itself only)."""
        objects = list(self.objects.values())
        if not forward:
            objects.reverse()
        for obj in objects:
            if code == 0x3FC and self._swap_player(obj, int(value)):
                continue
            if code == 0x400:
                self._clear_player_slots(obj)
            if hasattr(obj, "message"):
                obj.message(code, value)
        if self.on_broadcast is not None:
            self.on_broadcast(code, value)

    def score_message(self, code: int, value: float = 0.0) -> int:
        """FUN_010187d6."""
        if code in (1000, 0x3E9, 0x3EA, 0x3EB):
            if not self.tilted and self.on_input is not None:
                self.on_input(code)
        elif code in (0x3EC, 0x3ED):
            if self.on_input is not None:
                self.on_input(code)
        elif code in (0x3F0, 0x3F1, 0x3F2):
            self.broadcast(code, value)
        elif code == 0x3F4:
            self.all_lights.message(0xE, 0.0)
            if self.tilted:
                self.tilted = 0
                if self._tilt_timer:
                    self.timers.cancel(self._tilt_timer)
                self._tilt_timer = 0
        elif code == 0x3F5:
            self.all_lights.message(0x22, 0.0)
            self.all_lights.message(0x14, 0.0)
            self.msg("plunger", 0x3F8)
            self.text("info", 30 if self.demo else 26, -1.0)
            if self.demo_player is not None:
                self.demo_player.message(0x3F6)
        elif code == 0x3F6:
            self._new_game(value)
        elif code == 0x3FA:
            pass  # +0x162 / +0x166: a timer nothing reads (FUN_010175ef)
        elif code == 0x3FD:
            self._next_player()
        elif code == 0x3FE:
            self.play_ref("table", 1101)
            self.clear_text("mission")
            self.text("info", 34, -1.0)
            self._game_over_timer = self.timers.schedule(3.0, self._game_over_end)
        elif code == 0x400:
            self.broadcast(0x400)
            if self._start_timer:
                self.timers.cancel(self._start_timer)
                self.all_lights.message(0x22, 0.0)
            self._start_timer = 0
            self.multiplier = self.score_offset = self.reflex_value = 0
            self.bonus, self.bonus_on = 10000, 0
            self.jackpot, self.jackpot_on = 20000, 0
            self.extra_balls = self.multiball_balls = self.locked_balls = 0
            self.multiball = self.replay_balls = self.tilted = 0
        if code == 0x3F3:
            self._tilt_side_effect()  # the default case, FUN_0100c0be
        return 0

    # -- typed codes (FUN_0100e1b0, from every table key while playing) -------
    def type_key(self, vk: int) -> None:
        """FUN_0100e1b0 (only with no mission running): "CINEMATRONICS" and
        "QUOTES" lead nowhere; "1MAX" = an extra ball, "BMAX" = the
        ball-save window (DAT_01025044) on, "GMAX" = the gravity well,
        "RMAX" = a promotion, "HIDDEN TEST" = debug mode (DAT_01024ff8).
        Each of those marks the game as cheated (no high score)."""
        if self.data("lite198") != 0:
            return
        state = self.code_state
        if vk == ord("X"):
            if state == 0x3F:
                self._extra_ball(2.0)
            elif state == 0x53:
                self.ball_save_window = 1
            elif state == 0x67:
                self._gravity_well(0x40, None)
            elif state == 0x7B:
                self.cheat_rank()
            else:
                self.code_state = 0
                return
            self.cheated = 1
            self.code_state = 0
            return
        if vk == ord("T") and state == 0x1E:
            self.debug_mode = 1
            self.cheated = 1
            self.code_state = 0
            return
        if state in CODE_STEPS.get(vk, ()):
            self.code_state = state + 1
            return
        for need, new in CODE_JUMPS.get(vk, ()):
            if state == need:
                self.code_state = new
                return
        self.code_state = 0

    def cheat_rank(self) -> None:
        """FUN_0100e111 ("RMAX", and R in debug mode): the next middle-circle
        light, "Promotion to <rank>" for 8 s, soundwave10."""
        middle = self.objects.get("middle_circle")
        if middle is None:
            return
        rank = middle.message(0x25)
        if rank < 9:
            middle.message(0x29, 2.0)
            self.text("mission", 83, 8.0, STRINGS[RANKS[rank]])
            self.play("soundwave10")

    def flipper_message(self, code: int) -> None:
        if self.on_flipper_message is not None:
            self.on_flipper_message(code)

    def _tilt_side_effect(self) -> None:
        """FUN_0100c0be(0x3f3): the ball-save window shut, lite77 flashing."""
        self.ball_save_window = 0
        self.msg("lite77", 7)

    def _new_game(self, players: float) -> None:
        """0x3f6: a game over still counting down ends now; then everything
        is reset, `players` (1..4) boxes set up, the panel cleared and the
        start sound (the table's tag 1100) played while every light
        sparkles -- 0x3f5 serves when it ends. A second 0x3f6 during the
        sound starts at once."""
        if self._game_over_timer:
            self.timers.cancel(self._game_over_timer)
            self._game_over_end()
            self.set_mode(1)
        if self._start_timer:
            self.timers.cancel(self._start_timer)
            self._start_timer = 0
            self.score_message(0x3F5)
            return
        self.cheated = 0
        self.score_message(0x400)
        if self.on_hide_ball is not None:
            self.on_hide_ball()  # ball moved to (0, 0, -0.8)
        self.player_count = max(1, min(4, math.floor(players)))
        self.current_player = 0
        self.score = 0
        self.boxes[0] = 0
        self.multiplier = 0
        for record in self.records[1 : self.player_count]:
            record.score = record.billions = 0
            record.balls = self.balls_per_game
            record.extra_balls = self.extra_balls
            record.locked_balls = self.locked_balls
            record.jackpot = self.jackpot
        for i in range(1, self.player_count):
            self.boxes[i] = 0
        self.balls = self.balls_per_game  # FUN_010175aa
        self.player_number = 1
        for i in range(self.player_count, 4):
            self.boxes[i] = -1
        self.jackpot_on = self.bonus_on = 0
        self.clear_text("info")
        self.clear_text("mission")
        self.all_lights.message(0x1C, 0.2)
        length = self.play_ref("table", 1100)
        self._start_timer = self.timers.schedule(length, self._start)

    def _start(self) -> None:
        """FUN_01017467."""
        self._start_timer = 0
        self.score_message(0x3F5)

    def _next_player(self) -> None:
        """0x3fd, sent by the drain after a lost ball: with one player just
        "Player 1" again; otherwise, if the next player has balls left, the
        current player's score, balls, extra balls, locked balls and jackpot
        are put away, the next one's brought back, every object swaps its
        own per-player state (0x3fc) and "Player N" is shown."""
        if self.player_count < 2:
            self.text("info", 30 if self.demo else 26, -1.0)
            return
        nxt = (self.current_player + 1) % self.player_count
        if self.records[nxt].balls <= 0:
            return
        mine = self.records[self.current_player]
        mine.score, mine.billions, mine.balls = self.score, self.score_billions, self.balls
        mine.extra_balls, mine.locked_balls, mine.jackpot = self.extra_balls, self.locked_balls, self.jackpot
        theirs = self.records[nxt]
        self.score, self.score_billions, self.balls = theirs.score, theirs.billions, theirs.balls
        self.extra_balls, self.locked_balls, self.jackpot = theirs.extra_balls, theirs.locked_balls, theirs.jackpot
        self.boxes[nxt] = self.score
        self.player_number = nxt + 1
        self.broadcast(0x3FC, float(nxt), forward=True)
        self.text("info", (30 if self.demo else 26) + nxt, -1.0)
        self.jackpot_on = self.bonus_on = 0
        self.current_player = nxt

    def _game_over_end(self) -> None:
        """FUN_0101748b, 3 s after "Game Over": the high-score entries
        (FUN_0101479b), 0x3fe to every object and the demo, the mission
        box's 0x43 (starting the score/high-score cycle) and "F2 Starts New
        Game"."""
        self._game_over_timer = 0
        self._record_high_scores()
        if self.pending_entries:
            # The name entries are modal: the rest waits for them (the app
            # calls `after_entries` once the last dialog closes).
            self.after_entries = self._game_over_finish
            return
        self._game_over_finish()

    def _game_over_finish(self) -> None:
        self.after_entries = None
        self.broadcast(0x3FE)
        if self.demo_player is not None:
            self.demo_player.message(0x3FE)
        self.bus.notify(0x43, self.mission_box)
        self.text("info", 24, -1.0)

    def _record_high_scores(self) -> None:
        """FUN_0101479b: game over (mode 2); the players' final scores
        (their score boxes) sorted high to low as unsigned values; outside a
        demo and an uncheated game each one that would rank asks for a name,
        defaulting to "Player N"."""
        self.set_mode(2)
        scores = sorted(
            ((self.boxes[i], i) for i in range(self.player_count)),
            key=lambda item: item[0] & 0xFFFFFFFF,
            reverse=True,
        )
        if self.demo or self.cheated:
            return
        for score, player in scores:
            if self.high_scores.rank(score) >= 0:
                self.pending_entries.append((score, STRINGS[26 + player]))

    def has_high_score(self) -> bool:
        """FUN_01014908."""
        if self.demo:
            return False
        return any(self.high_scores.rank(self.boxes[i]) >= 0 for i in range(self.player_count - 1, -1, -1))

    # -- per-player state (each handler's own 0x3fc / 0x400) ------------------
    def _player_slots(self, obj: object) -> list:
        """The object's four per-player copies (+0x7e.., +0x4a.., ...),
        zeros until first saved: the objects are calloc'ed (FUN_010145f5)."""
        slots = self._slots.get(id(obj))
        if slots is None:
            if isinstance(obj, Bargraph):
                empty: object = 0
            elif isinstance(obj, Light):
                empty = (0, 0, 0, 0)
            elif isinstance(obj, LightGroup):
                empty = (0, 0, 0.0)
            elif isinstance(obj, Bumper):
                empty = (0, 0)
            else:
                empty = 0
            slots = self._slots[id(obj)] = [empty] * 4
        return slots

    def _swap_player(self, obj: object, nxt: int) -> bool:
        """0x3fc for the objects that keep per-player copies (saved under
        the current player, then reset and reloaded from `nxt`). Returns
        False for every other object, which just gets the message."""
        cur = self.current_player
        slots = self._player_slots(obj)
        if isinstance(obj, Bargraph):
            # FUN_0100ab28: its level.
            slots[cur] = obj.level
            obj.reset()
            obj.level = slots[nxt]
            if obj.level:
                obj.message(0x2D, float(obj.level))
            return True
        if isinstance(obj, Light):
            # FUN_01009ae3: flashing, frame, steady state and data.
            slots[cur] = (obj.flashing, obj.frame, obj.state, obj.data)
            obj.reset()
            obj.flashing, obj.frame, obj.state, obj.data = slots[nxt]
            if obj.frame:
                obj.message(0xB, float(obj.frame))
            if obj.state:
                obj.message(1)
            if obj.flashing:
                obj.message(4)
            return True
        if isinstance(obj, LightGroup):
            # FUN_0100a166: data, animation and step; re-runs the animation
            # step when data is non-zero (as the original tests +6).
            slots[cur] = (obj.data, obj.animation, obj._step)
            obj.reset()
            obj.data, obj.animation, obj._step = slots[nxt]
            if obj.data:
                obj._animate()
            return True
        if isinstance(obj, Bumper):
            # FUN_01015d79: level and data; the 0xb that follows sees no
            # change, so no sound or flash.
            slots[cur] = (obj.level, obj.data)
            obj.level, obj.data = slots[nxt]
            return True
        if isinstance(obj, WallTarget) and obj.drop_time == 0.0:
            # FUN_010160f4 (standup targets): data, then down if set, else
            # raised after its delay.
            slots[cur] = obj.data
            obj.data = slots[nxt]
            obj.message(0x31 if obj.data else 0x32)
            return True
        if isinstance(obj, Sink):
            # FUN_01017197: data.
            slots[cur] = obj.data
            obj.data = slots[nxt]
            return True
        return False

    def _clear_player_slots(self, obj: object) -> None:
        """Each per-player handler's 0x400 also resets the copies of the
        first `player_count` players (the count still from the last game:
        0x3f6 resets before it changes it)."""
        if not isinstance(obj, (Light, LightGroup, Bumper, Sink)) and not (
            isinstance(obj, WallTarget) and obj.drop_time == 0.0
        ):
            return
        slots = self._player_slots(obj)
        for i in range(self.player_count):
            if isinstance(obj, Bargraph):
                slots[i] = 0
            elif isinstance(obj, Light):
                slots[i] = (0, 0, 0, 0)
            elif isinstance(obj, LightGroup):
                slots[i] = (obj.data, 0, obj.interval)
            elif isinstance(obj, Bumper):
                slots[i] = (0, 0)
            else:
                slots[i] = 0

    def bumper_hit(self, name: str, lockout: float) -> None:
        """FUN_0101811d: a kicking hit shows the bumper's lit frame for its
        lockout (FUN_01015d0f / FUN_01015cb2), plays its tag-406 sound and
        notifies 0x3f."""
        bumper = self.bumpers.get(name)
        if bumper is None:
            return
        self.play_ref(name, 406)
        self._bumper_flash(bumper, lockout)
        self.bus.notify(0x3F, bumper)

    def _bumper_flash(self, bumper: Bumper, lockout: float | None = None) -> None:
        """FUN_01015d0f: frame 2*level+1 and no kick (threshold 1e9) until
        FUN_01015cb2 restores both after tag 407 seconds. Earlier timers are
        not cancelled, so the first one to end restores."""
        circle = next((c for c in self.layout.bumpers if getattr(c, "name", None) == bumper.name), None)
        if lockout is None:
            lockout = circle.cooldown if circle is not None else 0.1
            if circle is not None:
                circle._cooldown_remaining = lockout
        bumper.lit_frame = True
        self.timers.schedule(lockout, lambda: setattr(bumper, "lit_frame", False))

    def flipper(self, name: str, pressed: bool) -> None:
        """FUN_0101c178: 1 = extend (notifies the listener, sound tag 1100),
        2 = retract (sound tag 1101)."""
        if pressed:
            self.bus.notify(1, _Named(name))
            self.play_ref(name, 1100)
        else:
            self.play_ref(name, 1101)

    def tilt(self) -> bool:
        """FUN_01017791 (not while tilted or with the ball already lost):
        both boxes cleared, "TILT!", the table's tilt sound (tag 406), a
        30 s timer that drains the ball if it is still tilted then, 0x3f3 to
        the score object itself and to every object, every light
        temporarily off (8), scoring stopped (+0x172) until 0x3f4."""
        if self.tilted or self.ball_lost:
            return False
        self.clear_text("info")
        self.clear_text("mission")
        self.text("info", 35, -1.0)
        self.play_ref("table", 406)
        self._tilt_timer = self.timers.schedule(30.0, self._tilt_expired)
        self.score_message(0x3F3, -1.0)
        self.broadcast(0x3F3, forward=True)
        self.all_lights.message(8, 0.0)
        self.tilted = 1
        self._tilt_side_effect()
        return True

    def _tilt_expired(self) -> None:
        """FUN_01017738: still tilted after 30 s -- every ball goes down the
        drain (the drain's collision handler called directly)."""
        self._tilt_timer = 0
        if self.tilted and self.on_force_drain is not None:
            self.on_force_drain()

    # -- the listeners --------------------------------------------------------
    def _register_listeners(self) -> None:
        reg = self.bus.listeners
        for name in ("a_bump1", "a_bump2", "a_bump3", "a_bump4", "a_bump5", "a_bump6", "a_bump7"):
            reg[name] = self._bumper
        for name in ("a_roll1", "a_roll2", "a_roll3"):
            reg[name] = self._attack_rollover
        for name in ("a_roll110", "a_roll111", "a_roll112"):
            reg[name] = self._launch_rollover
        reg["attack_bumpers"] = self._bumper_group_decay
        reg["launch_bumpers"] = self._bumper_group_decay
        reg["v_rebo1"] = lambda code, obj: self._rebound(code, obj, "lite84")
        reg["v_rebo2"] = lambda code, obj: self._rebound(code, obj, "lite85")
        reg["v_rebo3"] = lambda code, obj: self._rebound(code, obj, None)
        reg["v_rebo4"] = lambda code, obj: self._rebound(code, obj, None)
        reg["a_kick1"] = lambda code, obj: code == 0x3C and self.msg("v_gate1", 0x36)
        reg["a_kick2"] = lambda code, obj: code == 0x3C and self.msg("v_gate2", 0x36)
        reg["v_gate1"] = lambda code, obj: self._gate(code, "lite30", "lite196")
        reg["v_gate2"] = lambda code, obj: self._gate(code, "lite29", "lite195")
        reg["s_onewy4"] = self._skill_shot
        reg["s_onewy10"] = lambda code, obj: code == 0x3F and self.msg("skill_shot_lights", 0x14)
        reg["v_bloc1"] = self._center_post
        reg["ramp"] = self._ramp
        reg["ramp_hole"] = lambda code, obj: code == 0x3A and self.msg("lite54", 7, 5.0)
        reg["a_roll4"] = self._outlane
        reg["a_roll8"] = self._outlane
        reg["lite17"] = self._lite17
        reg["a_roll6"] = self._inlane
        reg["a_roll7"] = self._inlane
        reg["a_roll5"] = self._fuel_rollover
        for i, name in enumerate(("a_roll179", "a_roll180", "a_roll181", "a_roll182", "a_roll183", "a_roll184")):
            reg[name] = lambda code, obj, i=i: self._fuel_lane(code, obj, i)
        reg["a_flag1"] = self._flag
        reg["a_flag2"] = self._flag
        reg["a_kout2"] = self._hyperspace
        reg["hyperspace_lights"] = lambda code, obj: self._decaying_group(code, obj, 60.0)
        for name in ("v_sink1", "v_sink2", "v_sink3"):
            reg[name] = self._wormhole
        reg["a_flip1"] = lambda code, obj: code == 1 and self._lane_change(0x18)
        reg["a_flip2"] = lambda code, obj: code == 1 and self._lane_change(0x19)
        reg["plunger"] = self._plunger
        for name in ("a_targ1", "a_targ2", "a_targ3"):
            reg[name] = self._booster_targets
        reg["lite60"] = lambda code, obj: code == 0x3C and setattr(self, "jackpot_on", 0)
        reg["lite59"] = lambda code, obj: code == 0x3C and setattr(self, "bonus_on", 0)
        for name in ("a_targ4", "a_targ5", "a_targ6"):
            reg[name] = self._medal_targets
        reg["bumper_target_lights"] = lambda code, obj: self._decaying_group(code, obj, 30.0)
        for name in ("a_targ7", "a_targ8", "a_targ9"):
            reg[name] = self._multiplier_targets
        reg["top_target_lights"] = self._multiplier_group
        for name in ("a_targ10", "a_targ11", "a_targ12"):
            reg[name] = self._fuel_targets
        for name in ("a_targ13", "a_targ14", "a_targ15"):
            reg[name] = self._mission_targets
        for name in ("a_targ16", "a_targ17", "a_targ18"):
            reg[name] = lambda code, obj: self._gate_targets(
                code, obj, ("a_targ16", "a_targ17"), ("lite104", "lite105", "lite106"), "lchute_tgt_lights", "v_gate1"
            )
        for name in ("a_targ19", "a_targ20", "a_targ21"):
            reg[name] = lambda code, obj: self._gate_targets(
                code, obj, ("a_targ19", "a_targ20"), ("lite107", "lite108", "lite109"), "bpr_solotgt_lights", "v_gate2"
            )
        reg["a_targ22"] = self._wormhole_target
        reg["a_roll9"] = lambda code, obj: code == 0x3F and (self.msg("lite27", 0x13), self.msg("lite28", 0x13))
        reg["a_kout3"] = self._black_hole
        reg["a_kout1"] = self._gravity_well
        reg["drain"] = self._drain
        reg["s_onewy1"] = self._launch_lane
        reg["s_trip1"] = lambda code, obj: self._skill_trip(code, "lite68")
        reg["s_trip2"] = lambda code, obj: self._skill_trip(code, "lite69")
        reg["s_trip3"] = lambda code, obj: self._skill_trip(code, "lite131")
        reg["s_trip4"] = lambda code, obj: self._skill_trip(code, "lite132")
        reg["s_trip5"] = lambda code, obj: self._skill_trip(code, "lite133")
        reg["lite200"] = self._redeploy_light
        reg["v_sink7"] = lambda code, obj: code == 0x3F and obj.message(0x38, obj.eject_delay)

    def _bumper(self, code: int, obj: Bumper) -> None:
        """FUN_0100c4f5: score the entry for the bumper's level."""
        if code == 0x3F:
            self.add_score(self.score_of(obj, obj.level))

    def _rollover_bank(self, obj: object, lights: tuple[str, str, str], names: tuple[str, str], bank: str,
                       first_bumper: str, group: str, text: int) -> None:
        light = lights[0] if obj is self.objects.get(names[0]) else (lights[1] if obj is self.objects.get(names[1]) else lights[2])
        lamp = self.objects[light]
        if not lamp.flashing:
            if not lamp.state:
                lamp.message(0x13)
                if self.msg(bank, 0x25) == self.msg(bank, 0x26):
                    self.msg(bank, 7, 5.0)
                    self.msg(bank, 0)
                    if self.bumpers[first_bumper].level < 3:
                        self.msg(group, 0xC)
                        self.text("info", text, 2.0)
                    self.msg(group, 0x30, 60.0)
            else:
                lamp.message(0x14)
        self.add_score(self.score_of(obj, 0))

    def _attack_rollover(self, code: int, obj: object) -> None:
        """FUN_0100c939: a_roll1..3 toggle lite10/9/8; all three lit flash
        the bank, upgrade the attack bumpers (unless already at level 3) and
        start their 60 s decay; a pass also stops the trek lights unless
        lite56 is lit."""
        if code != 0x3F:
            return
        if not self.lit("lite56") and self.msg("l_trek_lights", 0x27):
            for group in ("l_trek_lights", "r_trek_lights"):
                self.msg(group, 0x22)
                self.msg(group, 0x14)
        self._rollover_bank(obj, ("lite8", "lite9", "lite10"), ("a_roll3", "a_roll2"), "bmpr_inc_lights",
                            "a_bump1", "attack_bumpers", 5)

    def _launch_rollover(self, code: int, obj: object) -> None:
        """FUN_0100cafe: the upper deck's a_roll110..112 and the launch
        bumpers, as FUN_0100c939."""
        if code == 0x3F:
            self._rollover_bank(obj, ("lite171", "lite170", "lite169"), ("a_roll112", "a_roll111"),
                                "ramp_bmpr_inc_lights", "a_bump5", "launch_bumpers", 6)

    def _bumper_group_decay(self, code: int, obj: BumperGroup) -> None:
        """FUN_0100cabf: every 60 s a raised bumper group drops one level.
        (The original tests the group's +0x4e, past the end of its 0x36-byte
        object; the first bumper's level is the evident intent.)"""
        if code == 0x3D and obj.level != 0:
            obj.message(0x30, 60.0)
            obj.message(0xD)

    def _rebound(self, code: int, obj: object, light: str | None) -> None:
        """FUN_0100c44b / FUN_0100c48b / FUN_0100c4cb: slingshots."""
        if code == 0x3F:
            if light is not None:
                self.msg(light, 9, 0.1)
            self.add_score(self.score_of(obj, 0))

    def _gate(self, code: int, light: str, arrow: str) -> None:
        """FUN_0100c56c / FUN_0100c5d3: an open gate flashes its kickback
        lights for 5 s, a closed one turns them off."""
        if code == 0x35:
            self.msg(light, 0xF, 5.0)
            self.msg(arrow, 7, 5.0)
        elif code == 0x36:
            self.msg(light, 0x14)
            self.msg(arrow, 0x14)

    def _skill_shot(self, code: int, obj: object) -> None:
        """FUN_0100c63a: s_onewy4, the skill shot -- scores by how many
        skill-shot lights the launch lit."""
        if code != 0x3F:
            return
        lit = self.msg("skill_shot_lights", 0x25)
        if not lit:
            return
        self.play("soundwave3")
        added = self.add_score(self.score_of(obj, lit - 1))
        self.text("info", 21, 2.0, added)
        if not self.lit("lite56"):
            for group in ("l_trek_lights", "r_trek_lights"):
                self.msg(group, 0x22)
                self.msg(group, 0x14)
        self.msg("skill_shot_lights", 0x2C, 1.0)

    def _center_post(self, code: int, obj: object) -> None:
        """FUN_0100c764: v_bloc1, the center post: 0x34 raises it for +0x4e
        (55) s with lite1 on, then it flashes for +0x52 (5) s and drops."""
        if code == 0x34:
            obj.data = 1
            obj.message(0x34, float(obj.up_time))
            self.msg("lite1", 9, float(obj.up_time))
        elif code == 0x3C:
            if obj.data != 1:
                obj.data = 0
                obj.message(0x33)
                return
            obj.data = 2
            obj.message(0x3B, float(obj.warn_time))
            self.msg("lite1", 7, float(obj.warn_time))

    def _ramp(self, code: int, obj: object) -> None:
        """FUN_0100c7e9: the ramp score line. With lite54 lit it awards the
        reflex shot; with none of lite54..56 lit it scores 5000."""
        if code != 0x3F:
            return
        mask = 0
        if self.lit("lite54"):
            mask = 1
            added = self.award(self.reflex_value)
            self.text("info", 10, 2.0, added)
        if self.lit("lite55"):
            mask |= 2
        if self.lit("lite56"):
            mask |= 4
        if mask == 0:
            self.add_score(self.score_of(obj, 0))
            wave = "soundwave30"
        elif mask == 1:
            wave = "soundwave21"
        elif mask < 4:
            wave = "soundwave23"
        else:
            wave = "soundwave24"
        self.play(wave)

    def _outlane(self, code: int, obj: object) -> None:
        """FUN_0100cc20: a_roll4/a_roll8, the outlanes. With lite17/lite18
        lit they give an extra ball; a lit kickback (lite30/lite29) flashes
        its arrows."""
        if code != 0x3F:
            return
        if not self.lit("lite17") and not self.lit("lite18"):
            self.play("soundwave26")
        else:
            self._extra_ball(2.0)
            self.msg("lite17", 0x14)
            self.msg("lite18", 0x14)
        if obj is self.objects.get("a_roll4"):
            if self.lit("lite30"):
                self.msg("lite30", 4)
                self.msg("lite196", 4)
        elif self.lit("lite29"):
            self.msg("lite29", 4)
            self.msg("lite195", 4)
        self.add_score(self.score_of(obj, 0))

    def _lite17(self, code: int, obj: object) -> None:
        """FUN_0100cd12: lite17/lite18, the extra-ball outlane lights: on for
        55 s, then flashing for 5 s."""
        if code == 0x13:
            self.msg("lite17", 9, 55.0)
            self.msg("lite18", 9, 55.0)
            self.rollover_bonus_lit = 1
        elif code == 0x3C and self.rollover_bonus_lit:
            self.msg("lite17", 7, 5.0)
            self.msg("lite18", 7, 5.0)
            self.rollover_bonus_lit = 0

    def _inlane(self, code: int, obj: object) -> None:
        """FUN_0100cda0: a_roll6/7 score their second entry when their
        lite27/28 is lit (consuming it and lite59)."""
        if code != 0x3F:
            return
        light = "lite27" if obj is self.objects.get("a_roll6") else "lite28"
        index = 0
        if self.lit(light):
            self.msg("lite59", 0x14)
            self.msg(light, 0x14)
            index = 1
        self.add_score(self.score_of(obj, index))

    def _fuel_rollover(self, code: int, obj: object) -> None:
        """FUN_0100ce40: a_roll5 refuels (full bargraph); with lite16 lit it
        instead awards the bonus."""
        if code != 0x3F:
            return
        if not self.lit("lite16"):
            self.add_score(self.score_of(obj, 0))
            self.play("soundwave25")
            self.text("info", 44, 2.0)
        else:
            added = self.award(self.bonus)
            self.text("info", 3, 2.0, added)
            self.msg("lite16", 0x14)
            self.play("soundwave50")
        self.msg("fuel_bargraph", 0x2D, 11.0)

    def _fuel_lane(self, code: int, obj: object, index: int) -> None:
        """FUN_0100cf36 .. FUN_0100d1f8: a_roll179..184, the fuel lanes: each
        tops the bargraph up to its own level (2*i+1), else its light blinks
        off briefly."""
        if code != 0x3F:
            return
        target = 2 * index + 1
        if self.msg("fuel_bargraph", 0x25) < target + 1:
            self.msg("fuel_bargraph", 0x2D, float(target))
            self.text("info", 44, 2.0)
        else:
            self.msg(f"literoll{179 + index}", 8, 0.05)
        self.add_score(self.score_of(obj, 0))

    def _flag(self, code: int, obj: object) -> None:
        """FUN_0100dd33: a flag's rotation advances the wormhole arrows; a
        hit scores its second entry while lite20 is lit."""
        if code == 0x3E:
            self._advance_wormhole(0)
        elif code == 0x3F:
            self.add_score(self.score_of(obj, int(self.lit("lite20"))))

    def _hyperspace(self, code: int, obj: object) -> None:
        """FUN_01011f1a: a_kout2, the hyperspace kickout. Each entry lights
        the next hyperspace light (5 levels): jackpot, center post, extra
        ball lights, then the gravity well; lite25 flashes and the hole
        ejects after the level's sound."""
        if code != 0x3F:
            return
        level = self.msg("hyperspace_lights", 0x25)
        self._decaying_group(0x29, self.objects["hyperspace_lights"], 60.0)
        if level == 0:
            added = self.add_score(self.score_of(obj, 0))
            self.text("info", 12, 2.0, added)
        elif level == 1:
            added = self.award(self.jackpot)
            self.text("info", 14, 2.0, added)
            self.jackpot = 20000
        elif level == 2:
            self._center_post(0x34, self.objects["v_bloc1"])
            added = self.add_score(self.score_of(obj, 2))
            self.text("info", 2, 2.0, added)
        elif level == 3:
            self._lite17(0x13, None)
            added = self.add_score(self.score_of(obj, 3))
            self.text("info", 8, 2.0, added)
        elif level == 4:
            self.msg("hyperspace_lights", 0)
            added = self.add_score(self.score_of(obj, 4))
            self._gravity_well(0x40, None, added)
        mask = 0
        if self.lit("lite25"):
            mask = 1
            added = self.award(self.reflex_value)
            self.text("info", 10, 2.0, added)
        if self.lit("lite26"):
            mask |= 2
        if self.lit("lite130"):
            mask |= 4
            self.msg("lite130", 0x14)
            self._multiplier_group(0x40, self.objects["top_target_lights"])
            self.msg("bumper_target_lights", 0x13)
            self._jackpot_on()
            self._bonus_on()
            self._flags_upgrade()
            self._bonus_hold()
            self.msg("lite27", 0x13)
            self.msg("lite28", 0x13)
            self._lite17(0x13, None)
            self._center_post(0x34, self.objects["v_bloc1"])
            if self.multiball:
                self.text("info", 16, 2.0)
            self.jackpot = max(self.jackpot, 100000)
            self.bonus = max(self.bonus, 100000)
            self._gravity_well(0x40, None)
        if mask == 0:
            wave = {1: "soundwave36", 2: "soundwave35", 3: "soundwave38", 4: "soundwave39"}.get(level, "soundwave35")
            duration = self.play(wave)
        elif mask == 1 or mask in (2, 3):
            duration = self.play("soundwave21" if mask == 1 else "soundwave40")
        else:
            duration = self.play("soundwave41")
            self.play("soundwave36")
            self.play("soundwave50")
        self.msg("lite25", 7, 5.0)
        obj.message(0x37, duration)

    def _decaying_group(self, code: int, obj: LightGroup, period: float) -> None:
        """FUN_0100d286 (60 s) / FUN_0100d73e (30 s): 0x29 lights the next
        member (flashing 2 s) and (re)starts the decay timer; every timer
        tick turns the top lit member off; 0 resets."""
        if code == 0:
            obj.message(0, 0.0)
            return
        if code == 0x29:
            obj.message(0x29, 2.0)
        elif code == 0x3D:
            obj.message(0x21)
            if obj.message(0x25) == 0:
                return
        else:
            return
        obj.message(0x2B, period)

    def _wormhole(self, code: int, obj: object) -> None:
        """FUN_0100d303: the wormholes v_sink1..3. Unlit (lite4.data = 0)
        the ball comes back out of the same hole; a lit wormhole sends it
        to the hole lite4 names (scoring the second entry, or the third for
        a wrong hole), and the right hole also locks a ball / awards."""
        if code != 0x3F:
            return
        sinks = ("v_sink1", "v_sink2", "v_sink3")
        arrows = ("lite5", "lite6", "lite7")
        frames = ("lite4", "lite2", "lite3")
        here = sinks.index(obj.name)
        target = self.data("lite4")
        if target == 0:
            self.add_score(self.score_of(obj, 0))
            self.msg(arrows[here], 0x10, obj.eject_delay)
        else:
            self.set_data("lite4", 0)
            self.msg("worm_hole_lights", 0x14)
            self.msg("bsink_arrow_lights", 0x14)
            self.msg("lite110", 0x14)
            if target == here + 1:
                if self.multiball:
                    self._lock_ball()
                    self.add_score(10000)
                    return
                self.text("info", 49, 2.0)
                self._replay_ball(4.0)
                self.add_score(self.score_of(obj, 1))
                self.msg(arrows[here], 0x10, obj.eject_delay)
                self.msg(frames[here], 0xB, float(2 - here))
                self.msg(frames[here], 0x10, obj.eject_delay)
                self.msg(sinks[here], 0x38, obj.eject_delay)
                return
            self.add_score(self.score_of(obj, 2))
            here = target - 1
            self.msg(arrows[here], 0x10, obj.eject_delay)
        self.msg(frames[here], 0xB, float(2 - here))
        self.msg(frames[here], 0x10, obj.eject_delay)
        self.msg(sinks[here], 0x38, obj.eject_delay)
        self.text("info", 49, 2.0)

    def _lane_change(self, animation: int) -> bool:
        """FUN_0100d53a / FUN_0100d572: a flipper press rotates the lit
        rollover lights of both bumper banks."""
        self.msg("bmpr_inc_lights", animation)
        self.msg("ramp_bmpr_inc_lights", animation)
        return True

    def _plunger(self, code: int, obj: object) -> None:
        """FUN_01012285: 0x3f7 = ball served; 0x3f8 = a new ball is coming.
        Unless the Re-Deploy light (lite200) is lit -- a saved ball --
        it lights the skill shot, starts the trek lights, sets the reflex
        value to 25000, resets the field multiplier lights, opens both
        kickback gates and turns lite200 on."""
        if code == 0x3F7:
            self._mission(0x43, None)
        elif code == 0x3F8:
            self.ball_save_window = 0
            if self.msg("middle_circle", 0x25) == 0:
                self.msg("middle_circle", 0x20)
            if not self.lit("lite200"):
                self.msg("skill_shot_lights", 0x14)
                self.msg("lite67", 0x13)
                self.msg("skill_shot_lights", 0x1A, 0.25)
                for group in ("l_trek_lights", "r_trek_lights"):
                    self.msg(group, 0x14)
                    self.msg(group, 0x20, 0.2)
                    self.msg(group, 0x1A, 0.2)
                self.reflex_value = 25000
                self._multiplier_group(0x41, self.objects["top_target_lights"])
                self.msg("fuel_bargraph", 0x13)
                self.msg("lite200", 0x13)
                self.msg("v_gate1", 0x35)
                self.msg("v_gate2", 0x35)
            self.set_data("lite200", 0)

    def _three_bank(self, obj: object, names: tuple[str, str, str]) -> bool:
        """Common head of FUN_0100d5ea / FUN_0101240d / FUN_01012570: a
        target already down this round does nothing; returns whether all
        three are now down."""
        obj.data = 1
        return sum(self.data(name) for name in names) == 3

    def _reset_bank(self, names: tuple[str, str, str]) -> None:
        for name in reversed(names):
            self.set_data(name, 0)
            self.msg(name, 0x32)

    def _booster_targets(self, code: int, obj: object) -> None:
        """FUN_0100d5ea: a_targ1..3. Completing the bank awards, in order of
        what isn't lit yet, the reflex value (lite19/20/61), the jackpot
        (lite60), the bonus (lite59) and the bonus hold (lite58)."""
        if code != 0x3F or obj.data != 0:
            return
        names = ("a_targ1", "a_targ2", "a_targ3")
        if not self._three_bank(obj, names):
            self.add_score(self.score_of(obj, 0))
            return
        if not self.lit("lite61"):
            if self.data("lite198") not in (0xF, 0x1D):
                self._flags_upgrade()
                self.play("soundwave47")
        elif not self.lit("lite60"):
            self._jackpot_on()
            self.play("soundwave45")
        elif not self.lit("lite59"):
            self._bonus_on()
            self.play("soundwave46")
        elif not self.lit("lite58"):
            self._bonus_hold()
            self.play("soundwave48")
        else:
            self.add_score(self.score_of(obj, 1))
            self.play("soundwave48")
        for name in ("a_targ1", "a_targ2", "a_targ3"):
            self.set_data(name, 0)
            self.msg(name, 0x32)
        self.add_score(self.score_of(obj, 1))

    def _jackpot_on(self) -> None:
        """FUN_0100c14f."""
        self.jackpot_on = 1
        self.msg("lite60", 9, 60.0)
        self.text("info", 15, 2.0)

    def _bonus_on(self) -> None:
        """FUN_0100c199."""
        self.bonus_on = 1
        self.msg("lite59", 9, 60.0)
        self.text("info", 4, 2.0)

    def _flags_upgrade(self) -> None:
        """FUN_0100c1e3."""
        self.msg("lite20", 9, 60.0)
        self.msg("lite19", 9, 60.0)
        self.msg("lite61", 9, 60.0)
        self.text("info", 51, 2.0)

    def _bonus_hold(self) -> None:
        """FUN_0100c24a."""
        self.msg("lite58", 0x13)
        self.text("info", 52, 2.0)

    def _medal_targets(self, code: int, obj: object) -> None:
        """FUN_0101240d: a_targ4..6. Each completed bank lights the next
        bumper target light (30 s decay): commendations, then an extra ball."""
        if code != 0x3F or obj.data != 0:
            return
        if not self._three_bank(obj, ("a_targ4", "a_targ5", "a_targ6")):
            self.add_score(self.score_of(obj, 0))
            return
        self._decaying_group(0x29, self.objects["bumper_target_lights"], 30.0)
        count = self.msg("bumper_target_lights", 0x25)
        if count == 1:
            self.add_score(self.score_of(obj, 1))
            self.text("info", 53, 2.0)
        elif count == 2:
            self.add_score(self.score_of(obj, 2))
            self.text("info", 54, 2.0)
        else:
            self.text("info", 55, 2.0)
            self._extra_ball(4.0)
        self._reset_bank(("a_targ4", "a_targ5", "a_targ6"))

    def _multiplier_targets(self, code: int, obj: object) -> None:
        """FUN_01012570: a_targ7..9 raise the field multiplier."""
        if code != 0x3F or obj.data != 0:
            return
        if not self._three_bank(obj, ("a_targ7", "a_targ8", "a_targ9")):
            self.add_score(self.score_of(obj, 0))
            return
        self.add_score(self.score_of(obj, 1))
        self._multiplier_group(0x29, self.objects["top_target_lights"])
        count = self.msg("top_target_lights", 0x25)
        self.multiplier = count if count in (1, 2, 3) else 4
        self.text("info", {1: 56, 2: 57, 3: 58}.get(count, 59), 2.0)
        self._reset_bank(("a_targ7", "a_targ8", "a_targ9"))

    def _multiplier_group(self, code: int, obj: LightGroup) -> None:
        """FUN_0100d7bb: top_target_lights, the field multiplier lights (30 s
        decay, each step also dropping the multiplier); 0x40 = 10x for 30 s,
        0x41 = reset."""
        if code == 0:
            obj.message(0, 0.0)
            return
        if code == 0x29:
            obj.message(0x29, 2.0)
            obj.message(0x2B, 30.0)
        elif code == 0x3D:
            if self.multiplier:
                self.multiplier -= 1
            obj.message(0x21)
            if obj.message(0x25):
                obj.message(0x2B, 30.0)
        elif code == 0x40:
            self.multiplier = 4
            obj.message(0x13)
            obj.message(0x2B, 30.0)
            self.text("info", 59, 2.0)
        elif code == 0x41:
            self.multiplier = 0
            obj.message(0x14)
            obj.message(0x2B, -1.0)

    def _fuel_targets(self, code: int, obj: object) -> None:
        """FUN_0100d8de: a_targ10..12 light lite70..72; all three refuel."""
        if code != 0x3F:
            return
        light = {"a_targ10": "lite70", "a_targ11": "lite71"}.get(obj.name, "lite72")
        self.msg(light, 0xF, 2.0)
        self.add_score(self.score_of(obj, 0))
        if self.msg("top_circle_tgt_lights", 0x25) == 3:
            self.msg("top_circle_tgt_lights", 0x10, 2.0)
            self.msg("fuel_bargraph", 0x2D, 11.0)
            self.play("soundwave25")
            self.text("info", 44, 2.0)
        else:
            self.play("soundwave49D")

    def _mission_targets(self, code: int, obj: object) -> None:
        """FUN_0100d9c2: a_targ13..15, the mission-select targets."""
        if code != 0x3F:
            return
        bits = {"a_targ13": (1, "lite101"), "a_targ14": (2, "lite102")}.get(obj.name, (4, "lite103"))
        self.set_data("lite101", self.data("lite101") | bits[0])
        self.msg(bits[1], 0xF, 2.0)
        if not self.lit("lite198") or self.objects["lite198"].flashing:
            self.play("soundwave52")
        else:
            self.play("soundwave49D")
        self.add_score(self.score_of(obj, 0))
        if self.msg("ramp_tgt_lights", 0x25) == 3:
            self.msg("ramp_tgt_lights", 0x10, 2.0)

    def _gate_targets(self, code: int, obj: object, first: tuple[str, str], lights: tuple[str, str, str],
                      bank: str, gate: str) -> None:
        """FUN_0100da94 / FUN_0100db68: a_targ16..18 / 19..21; all three
        open that side's kickback gate."""
        if code != 0x3F:
            return
        if obj.name == first[0]:
            bit, light = 1, lights[0]
        elif obj.name == first[1]:
            bit, light = 2, lights[1]
        else:
            bit, light = 4, lights[2]
        self.set_data(lights[0], self.data(lights[0]) | bit)
        self.msg(light, 0xF, 2.0)
        self.add_score(self.score_of(obj, 0))
        if self.msg(bank, 0x25) == 3:
            self.play("soundwave14")
            self.msg(gate, 0x35)
            self.msg(bank, 0x10, 2.0)
        else:
            self.play("soundwave49D")

    def _wormhole_target(self, code: int, obj: object) -> None:
        """FUN_0100dc3c: a_targ22 lights lite110 ("Wormhole Opened") and
        advances the wormhole arrows."""
        if code != 0x3F:
            return
        if not self.lit("lite110"):
            self.msg("lite110", 0xF, 3.0)
            self.text("info", 93, 2.0)
        self.add_score(self.score_of(obj, 0))
        self._advance_wormhole(1)

    def _advance_wormhole(self, force: int) -> None:
        """FUN_0100c397: step lite4.data (which wormhole is lit) 1..3."""
        mission = self.data("lite198")
        if mission in (0x10, 0x16, 0x17) or (force == 0 and self.data("lite4") == 0):
            return
        target = self.data("lite4") + 1
        if target == 4:
            target = 1
        self.msg("bsink_arrow_lights", 0x17, float(target))
        self.msg("bsink_arrow_lights", 0xB, float(3 - target))
        if not self.lit("lite4"):
            self.msg("worm_hole_lights", 0x13)
            self.msg("bsink_arrow_lights", 0x13)

    def _black_hole(self, code: int, obj: object) -> None:
        """FUN_0100dcb0: a_kout3."""
        if code == 0x3F:
            added = self.add_score(self.score_of(obj, 0))
            self.text("info", 80, 2.0, added)
            obj.message(0x37, -1.0)

    def _gravity_well(self, code: int, obj: object, value: int = 0) -> None:
        """FUN_0100dd7a: a_kout1, the gravity well, armed by 0x40 (with the
        points just scored, if any, for its text)."""
        well = self.objects.get("a_kout1")
        if code == 0x3F and obj is not None:
            added = self.add_score(self.score_of(obj, 0))
            self.text("info", 81, 2.0, added)
            self.msg("lite62", 0x14)
            obj.active = False
            duration = self.play("soundwave7")
            obj.message(0x37, duration)
        elif code == 0x40:
            if value:
                self.text("info", 82, 2.0, value)
            else:
                self.text("info", 45, 2.0)
            self.msg("lite62", 4)
            if well is not None:
                well.active = True
        elif code == 0x400 and well is not None:
            well.active = False

    def _launch_lane(self, code: int, obj: object) -> None:
        """FUN_0100dea5: s_onewy1, the launch lane's one-way: the ball
        entering play turns the Re-Deploy light on for 5 s (then lite200's
        own handler flashes it 5 s more); with the skill shot lit
        (lite67) it ends the skill shot."""
        if code != 0x3F:
            return
        self.msg("lite200", 9, 5.0)
        if self.lit("lite67"):
            self.msg("skill_shot_lights", 0x22)
            self.msg("skill_shot_lights", 0x14)
            self.msg("lite67", 0x13)
            self.msg("lite54", 7, 5.0)
            self.msg("lite25", 7, 5.0)
            self.msg("fuel_bargraph", 0x2D, 11.0)
            self.play("soundwave14")

    def _skill_trip(self, code: int, light: str) -> None:
        """FUN_0100df6a .. FUN_0100e06e: the skill-shot trip lines."""
        if code == 0x3F and self.lit("lite67"):
            self.msg(light, 0x13)
            self.play("soundwave14")

    def _redeploy_light(self, code: int, obj: Light) -> None:
        """FUN_0100e0af: lite200, the Re-Deploy (ball save) light. When its
        timed state ends the first time it flashes for 5 s and goes off."""
        if code == 0x3C:
            if obj.data == 0:
                obj.message(0x10, 5.0)
                obj.data = 1
            else:
                obj.data = 0

    def _extra_ball(self, seconds: float) -> None:
        """FUN_0100c2f3."""
        self.extra_balls += 1
        self.play("soundwave28")
        self.text("info", 9, seconds)

    def _replay_ball(self, seconds: float) -> None:
        """FUN_0100c0ee: lite199 on ("Replay Awarded")."""
        self.msg("lite199", 0x13)
        self.text("info", 0, seconds)

    def _lock_ball(self) -> None:
        """FUN_0100c281."""
        if self.locked_balls == 2:
            self.text("info", 16, 2.0)
            self.locked_balls = 0
            return
        self.locked_balls += 1
        self.play("soundwave44")
        self.text("info", 1, 2.0)
        self.msg("plunger", 0x3F8)

    def _drain(self, code: int, obj: object) -> None:
        """FUN_010126ba: the drain. 0x3f (the ball fell in): a lit Re-Deploy
        light saves it; a lit replay light (lite199) saves it once; else the
        bonus is awarded and the ball is lost (or a Shoot Again extra ball
        used): the last ball of the last player marks the game over
        (lite199.data = 1), any other lost ball passes to the next player
        (0x3fd); then the per-ball lights and objects are reset and the
        tilt lifted (0x3f4). 0x3c (1.82 s later): serve the next ball, or
        say "Game Over" (0x3fe) -- with "HIGH SCORE", soundwave3 and every
        light flashing 3 s if a player made the table."""
        if code == 0x3C:
            if self.data("lite199") != 0:
                self.score_message(0x3FE)
                if self.has_high_score():
                    self.play("soundwave3")
                    self.all_lights.message(0x10, 3.0)
                    self.text("mission", 177, -1.0)
                return
            self.msg("plunger", 0x3F8)
            return
        if code != 0x3F:
            return
        if self.ball_save_window != 0:
            # "BMAX": the drain forgets the ball (0x400) and v_sink3 puts it
            # straight back in play (0x38 with no delay).
            self.msg("drain", 0x400)
            self.msg("v_sink3", 0x38, 0.0)
            return
        if self.tilted:
            self.msg("lite200", 0x14)
            self.msg("lite199", 0x14)
        if self.lit("lite200"):
            self.play("soundwave27")
            self.msg("lite200", 0x13)
            self.text("info", 96, -1.0)
            self.play("soundwave59")
            return
        if self.lit("lite199"):
            self.play("soundwave27")
            self.msg("lite199", 0x14)
            self.msg("lite200", 0x13)
            self.text("info", 95, 2.0)
            self.play("soundwave59")
            self.replay_balls -= 1
            return
        if self.multiball_balls != 0:
            self.play("soundwave27")
            self.multiball_balls -= 1
            return
        if not self.tilted:
            added = self.award(self.bonus)
            self.text("info", 94, 2.0, added)
        if self.extra_balls == 0:
            self.balls -= 1  # FUN_010175aa
            if self.current_player + 1 == self.player_count and self.balls == 0:
                self.set_data("lite199", 1)
            else:
                self.score_message(0x3FD)
                self.set_data("lite199", 0)
            self.play("soundwave27")
        else:
            self.extra_balls -= 1
            self.play("soundwave59")
            self.text("info", 97 + min(self.current_player, 3), -1.0)
        for name in (
            "bmpr_inc_lights", "ramp_bmpr_inc_lights", "lite30", "lite29", "lite1", "lite54", "lite55", "lite56",
            "lite17", "lite18", "lite27", "lite28", "lite16", "lite20", "hyperspace_lights", "lite25", "lite26",
            "lite130", "lite19", "worm_hole_lights", "bsink_arrow_lights", "l_trek_lights", "r_trek_lights",
            "lite60", "lite59", "lite61", "bumper_target_lights", "top_target_lights", "top_circle_tgt_lights",
            "ramp_tgt_lights", "lchute_tgt_lights", "bpr_solotgt_lights", "lite110", "skill_shot_lights",
            "lite77", "lite198", "lite196", "lite195", "fuel_bargraph",
        ):
            self.msg(name, 0x14)
        self.msg("fuel_bargraph", 0x400)
        self._gravity_well(0x400, None)
        self.msg("lite62", 0x14)
        for name in ("lite4", "lite101", "lite102", "lite103", "ramp_tgt_lights"):
            self.set_data(name, 0)
        self.msg("outer_circle", 0x22)
        self.msg("middle_circle", 0x22)
        for name in (
            "attack_bumpers", "launch_bumpers", "v_gate1", "v_gate2", "v_bloc1", "a_targ1", "a_targ2", "a_targ3",
            "a_targ6", "a_targ5", "a_targ4", "a_targ9", "a_targ8", "a_targ7",
        ):
            self.msg(name, 0x400)
        self.set_data("lite198", 0 if self.data("lite199") == 0 else 0x20)
        self._mission(0x42, None)
        self.score_message(0x3F4)
        if not self.lit("lite58"):
            self.bonus = 25000
        else:
            self.msg("lite58", 0x14)


@dataclass(eq=False)
class _Named:
    name: str
