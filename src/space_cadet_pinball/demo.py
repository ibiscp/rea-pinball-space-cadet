"""The `demo` object (type 0x3ff, FUN_0101a2b5; messages FUN_01017074,
collision FUN_01016f21): the attract-mode player. It owns five sensor
edges, live only while it is active (+5, set by FUN_0101461a(1) when
DAT_01025570 says a demo is running), and plays through the score object's
own messages, exactly as the keys would:

- tag 1400 (near a_flip1) / 1402 (near a_flip2): if that flipper isn't up
  or about to go up, flip it after a delay (+0x4e / +0x52: 0.2 +- 0.1 s
  from tag 407);
- tag 1401 / 1403 (triangles at the flipper tips): flip it now;
- tag 1404 (across the plunger lane, one ball radius out): pull the plunger
  and let go 2 + rand s later.
A flip (FUN_01016e70 / FUN_01016df3) holds the flipper for +0x56 / +0x5a
(0.4 +- 0.2 s) and drops it (FUN_01016dc0 / FUN_01016d8d). At game over
(0x3fe) an active demo starts the next demo game 5 s later (FUN_01016eed).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from .geometry import TripLine
from .logic import Timers
from .projection import tagged_floats
from .vec2 import Vec2

LEFT_ZONE, LEFT_TIP, RIGHT_ZONE, RIGHT_TIP, PLUNGER_LINE = 1400, 1401, 1402, 1403, 1404


def _rand() -> float:
    """rand() * 3.051851e-05: 0 .. 1."""
    return random.randrange(32768) * 3.051851e-05


def _around(centre: float, spread: float) -> float:
    """(centre + spread) - 2 * spread * rand: centre +- spread."""
    return (centre + spread) - (spread + spread) * _rand()


@dataclass(eq=False)
class DemoPlayer:
    timers: Timers
    send: Callable[[int], None]  # the score object's message handler
    restart: Callable[[], None]  # FUN_01016eed's new demo game
    flip_delay: tuple[float, float] = (0.2, 0.1)  # +0x4e / +0x52
    hold_time: tuple[float, float] = (0.2, 0.1)  # +0x56 / +0x5a
    name: str = "demo"
    active: bool = False  # +5
    data: int = 0
    left_up: int = 0  # +0x5e
    right_up: int = 0  # +0x62
    _left_pending: int = 0  # +0x66
    _right_pending: int = 0  # +0x6a
    _plunger: int = 0  # +0x6e
    _restart: int = 0  # +0x72
    lines: list[TripLine] = field(default_factory=list)

    def cross(self, tag: int) -> None:
        """FUN_01016f21."""
        if tag == LEFT_ZONE:
            if not self._left_pending and not self.left_up:
                self._left_pending = self.timers.schedule(_around(*self.flip_delay), self._flip_left)
        elif tag == LEFT_TIP:
            self._flip_left()
        elif tag == RIGHT_ZONE:
            if not self._right_pending and not self.right_up:
                self._right_pending = self.timers.schedule(_around(*self.flip_delay), self._flip_right)
        elif tag == RIGHT_TIP:
            self._flip_right()
        elif tag == PLUNGER_LINE and not self._plunger:
            self.send(0x3EC)
            self._plunger = self.timers.schedule(_rand() + 2.0, self._release_plunger)

    def _flip_left(self) -> None:
        """FUN_01016e70: the hold timer's handle isn't kept."""
        if self.left_up:
            return
        if self._left_pending:
            self.timers.cancel(self._left_pending)
            self._left_pending = 0
        self.send(1000)
        self.left_up = 1
        self.timers.schedule(_around(*self.hold_time), self._drop_left)

    def _flip_right(self) -> None:
        """FUN_01016df3."""
        if self.right_up:
            return
        if self._right_pending:
            self.timers.cancel(self._right_pending)
            self._right_pending = 0
        self.send(0x3EA)
        self.right_up = 1
        self.timers.schedule(_around(*self.hold_time), self._drop_right)

    def _drop_left(self) -> None:
        """FUN_01016dc0."""
        if self.left_up:
            self.send(0x3E9)
        self.left_up = 0

    def _drop_right(self) -> None:
        """FUN_01016d8d."""
        if self.right_up:
            self.send(0x3EB)
        self.right_up = 0

    def _release_plunger(self) -> None:
        """FUN_01016d62."""
        self._plunger = 0
        self.send(0x3ED)

    def _start_next(self) -> None:
        self._restart = 0
        self.restart()

    def message(self, code: int, value: float = 0.0) -> int:
        """FUN_01017074."""
        if code == 0x3F6:
            if self._restart:
                self.timers.cancel(self._restart)
            self._restart = 0
        elif code == 0x3FE:
            if self._restart:
                self.timers.cancel(self._restart)
            self._restart = 0
            if self.active:
                self._restart = self.timers.schedule(5.0, self._start_next)
        elif code == 0x400:
            for handle in (self._left_pending, self._right_pending):
                if handle:
                    self.timers.cancel(handle)
            self._left_pending = self._right_pending = 0
            if self.left_up:
                self._drop_left()
            if self.right_up:
                self._drop_right()
            if self._plunger:
                # The pull timer itself is left running (FUN_01016d62 called
                # directly), so the plunger is let go twice.
                self._release_plunger()
        return 0


def _edges(values: tuple[float, ...]) -> list[tuple[Vec2, Vec2]]:
    """FUN_010179a9 on a count-prefixed point list: 2 points = one line,
    more = a closed loop over all but the repeated last point."""
    count = int(values[0])
    points = [Vec2(values[1 + 2 * i], values[2 + 2 * i]) for i in range(count)]
    if count == 2:
        return [(points[0], points[1])]
    loop = points[:-1]
    return list(zip(loop, loop[1:] + loop[:1], strict=True))


def build_demo(entry, timers: Timers, send, restart, mask: int, ball_radius: float) -> DemoPlayer:
    """FUN_0101a2b5: delays from tag 407 (default 0.2 / 0.1 / 0.2 / 0.1),
    sensor edges from tags 1400..1404, the last one moved one ball radius
    out along its normal."""
    times = tagged_floats(entry, 407) or (0.2, 0.1, 0.2, 0.1)
    demo = DemoPlayer(timers, send, restart, flip_delay=(times[0], times[1]), hold_time=(times[2], times[3]))
    for tag in (LEFT_ZONE, LEFT_TIP, RIGHT_ZONE, RIGHT_TIP, PLUNGER_LINE):
        values = tagged_floats(entry, tag)
        if not values:
            continue
        for a, b in _edges(values):
            line = TripLine(a, b, mask, lambda ball, t=tag: demo.cross(t), lambda: demo.active)
            if tag == PLUNGER_LINE:
                line = line.offset(ball_radius)
            demo.lines.append(line)
    return demo
