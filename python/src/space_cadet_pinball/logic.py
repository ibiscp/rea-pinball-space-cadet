"""The original's light and timer framework, ported literally.

Every table light (`liteN`, type 0x3ea, constructor FUN_0100ad21) and light
group (`*_lights`, `*_circle`, type 0x402, FUN_0100adb1) is a message-driven
object: the control handlers (listeners) and missions talk to them through
their vtable slot 0, `FUN_01009ae3` for a light and `FUN_0100a166` for a
group. Timers are the game's own one-shot scheduler (FUN_010074b7 schedules
a callback after N seconds and returns a handle, FUN_01007659 cancels it).

Visual state (for the renderer): a light shows either nothing (its "off"
bitmap is null, so the lamp printed on the table art shows through) or one
of its own sprite frames (`frame`, set by message 0xb). `Light.shown` is
None or that frame index.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

MAX_TIMERS = 150  # FUN_0100742f(0x96), called by FUN_01015424


class Timers:
    """The game's one-shot timer pool: FUN_010074b7 schedules, FUN_01007659
    cancels, FUN_0100758d fires (once per tick, after the physics).

    - The clock is whole milliseconds (DAT_01024f84, advanced by each tick's
      elapsed ms); an expiry is `now + trunc(delay * 1000)`.
    - The pool holds 150 timers; scheduling into a full pool returns handle 0
      and the timer never fires.
    - The queue is sorted by expiry; a new timer goes after every timer with
      the same or an earlier expiry.
    - Each tick fires at most two due timers, then any that are at least
      100 ms overdue.
    """

    def __init__(self) -> None:
        self.now_ms = 0
        self._ms_carry = 0.0
        self._queue: list[tuple[int, int, Callable[[], None]]] = []
        self._next = 1

    @property
    def now(self) -> float:
        return self.now_ms / 1000.0

    def schedule(self, delay: float, callback: Callable[[], None]) -> int:
        if len(self._queue) >= MAX_TIMERS:
            return 0
        expiry = self.now_ms + int(delay * 1000.0)
        k = 0
        while k < len(self._queue) and self._queue[k][0] <= expiry:
            k += 1
        handle = self._next
        self._next += 1
        self._queue.insert(k, (expiry, handle, callback))
        return handle

    def cancel(self, handle: int) -> None:
        for k, entry in enumerate(self._queue):
            if entry[1] == handle:
                del self._queue[k]
                return

    def advance(self, ms: int) -> None:
        self.now_ms += ms

    def update(self, dt: float) -> None:
        """Advance the clock by `dt` seconds (kept in whole ms, carrying the
        remainder) and fire what's due."""
        self._ms_carry += dt * 1000.0
        ms = int(self._ms_carry)
        self._ms_carry -= ms
        self.advance(ms)
        self.fire()

    def fire(self) -> int:
        fired = 0
        while self._queue and self._queue[0][0] <= self.now_ms and fired < 2:
            fired += 1
            self._queue.pop(0)[2]()
        while self._queue and self._queue[0][0] + 100 <= self.now_ms:
            fired += 1
            self._queue.pop(0)[2]()
        return fired


class Bus:
    """FUN_01011ec9: deliver an object's notification to its control
    handler (the listener the control table at 0x1023ef0 linked to it, if
    any), then to the mission dispatcher FUN_01011bb5."""

    def __init__(self) -> None:
        self.listeners: dict[str, Callable[[int, object], None]] = {}
        self.mission: Callable[[int, object], None] | None = None

    def has_listener(self, name: str) -> bool:
        return name in self.listeners

    def notify(self, code: int, obj: object) -> None:
        handler = self.listeners.get(getattr(obj, "name", ""))
        if handler is not None:
            handler(code, obj)
        if self.mission is not None:
            self.mission(code, obj)


@dataclass(eq=False)
class Light:
    """A table light (FUN_0100ad21; messages FUN_01009ae3).

    Fields, with the original's offsets:
    - `state` (+0x4e): the steady on/off state;
    - `flashing` (+0x52), `temp_off` (+0x56), `temp_on` (+0x5a): timed
      overrides that hide the steady state until their timer (+0x6e) ends;
    - `off_after` (+0x5e): turn off when the timed state ends (message 0x10);
    - `frame` (+0x62): which sprite frame is the "on" bitmap (message 0xb);
    - `flash_times` (+0x3e/+0x42): how long the blink shows the off / on
      bitmap, from tags 900/901 (`base_times`, +0x66/+0x6a);
    - `data` (+6): a free per-light value (message 0x17).
    The timed state's end (FUN_01009a2a) notifies the listener with 0x3c."""

    name: str
    timers: Timers
    bus: Bus
    frames: int = 1
    base_times: tuple[float, float] = (0.1, 0.1)
    state: int = 0
    flashing: int = 0
    temp_off: int = 0
    temp_on: int = 0
    off_after: int = 0
    frame: int = 0
    data: int = 0
    shown: int | None = None
    flash_times: list[float] = field(default_factory=list)
    _timer: int = 0
    _timer2: int = 0
    _blink_timer: int = 0
    _phase: int = 0
    _on_frame: int = 0

    def __post_init__(self) -> None:
        self.flash_times = list(self.base_times)

    # -- the blink helper at +0x2a (FUN_01009910 / FUN_01009950 / FUN_0100996f)
    def _bitmap(self, index: int) -> int | None:
        return self._on_frame if index == 1 else None

    def _show(self, index: int) -> None:
        self.shown = self._bitmap(index)

    def _blink_toggle(self) -> None:
        self._phase = 1 - self._phase
        self._show(self._phase)
        self._blink_timer = self.timers.schedule(self.flash_times[self._phase], self._blink_toggle)

    def _start_blink(self, phase: int) -> None:
        self._phase = phase
        self._blink_toggle()

    def _stop_blink(self, phase: int) -> None:
        if self._blink_timer:
            self.timers.cancel(self._blink_timer)
        self._blink_timer = 0
        if phase >= 0:
            self._phase = phase
            self._show(phase)

    # -- timed states (FUN_01009a8f / FUN_01009a2a)
    def _set_timed(self, seconds: float) -> None:
        self.flash_times = list(self.base_times)
        if self._timer:
            self.timers.cancel(self._timer)
        self._timer = 0
        if seconds > 0:
            self._timer = self.timers.schedule(seconds, self._timed_end)

    def _timed_end(self) -> None:
        if self.flashing:
            self._stop_blink(-1)
        self._show(self.state)
        self.temp_off = self.temp_on = self.flashing = 0
        self._timer = 0
        if self.off_after:
            self.off_after = 0
            self.message(0x14)
        if self.bus.has_listener(self.name):
            self.bus.notify(0x3C, self)

    def reset(self) -> None:
        """FUN_010099a8 (vtable slot 5, also message 0x400)."""
        if self._timer:
            self.timers.cancel(self._timer)
        if self._timer2:
            self.timers.cancel(self._timer2)
        if self.flashing:
            self._stop_blink(-1)
        self._timer = self._timer2 = 0
        self.state = self.frame = self.temp_off = self.temp_on = self.flashing = self.off_after = 0
        self.shown = None
        self._on_frame = 0
        self.data = 0

    def lit(self) -> bool:
        """FUN_0100c092: steady on, temporarily on, or flashing."""
        return bool(self.state or self.temp_on or self.flashing)

    def message(self, code: int, value: float = 0.0) -> int:
        if code > 0x3FC:
            if code == 0x400:
                self.reset()
            return 0
        if code == 0x3FC:
            return 0  # player switch: single player only
        if code in (0, 1):
            self.state = code
            if not (self.flashing or self.temp_off or self.temp_on):
                self._show(code)
        elif code == 2:
            return self.state
        elif code == 3:
            return self.flashing
        elif code == 4:
            self._set_timed(0.0)
            if not self.flashing or not self._blink_timer:
                self.flashing = 1
                self.temp_on = self.temp_off = self.off_after = 0
                self._start_blink(self.state)
        elif code == 5:
            self.flash_times = [value * self.base_times[0], value * self.base_times[1]]
        elif code == 6:
            self.flash_times = list(self.base_times)
        elif code == 7:
            if not self.flashing:
                self._start_blink(self.state)
            self.flashing = 1
            self.temp_on = self.off_after = self.temp_off = 0
            self._set_timed(value)
        elif code == 8:
            if not self.temp_off:
                if not self.flashing:
                    self._show(0)
                else:
                    self._stop_blink(0)
                    self.flashing = 0
                self.temp_off = 1
                self.temp_on = 0
            self._set_timed(value)
        elif code == 9:
            if not self.temp_on:
                if not self.flashing:
                    self._show(1)
                else:
                    self._stop_blink(1)
                    self.flashing = 0
                self.temp_on = 1
                self.temp_off = 0
            self._set_timed(value)
        elif code == 0xB:
            self.frame = max(0, min(int(value), self.frames - 1))
            self._on_frame = self.frame
            if self.flashing:
                index = self._phase
            elif self.temp_off:
                index = 0
            elif self.temp_on:
                index = 1
            else:
                index = self.state
            self._show(index)
        elif code == 0xC:
            self.message(0xB, float(min(self.frame + 1, self.frames - 1)))
        elif code == 0xD:
            self.message(0xB, float(max(self.frame - 1, 0)))
        elif code == 0xE:
            if self._timer:
                self.timers.cancel(self._timer)
            self._timer = 0
            if self.flashing:
                self._stop_blink(-1)
            self.flashing = self.temp_off = self.temp_on = 0
            self._show(self.state)
        elif code == 0xF:
            self.off_after = 0
            if self._timer2:
                self.timers.cancel(self._timer2)
            self._timer2 = 0
            self.message(1)
            self.message(7, value)
        elif code == 0x10:
            if self._timer2:
                self.timers.cancel(self._timer2)
            self._timer2 = 0
            self.message(7, value)
            self.off_after = 1
        elif code == 0x11:
            self.message(1 if int(value) != 0 else 0)
            return self.state
        elif code == 0x12:
            self.message(0x11, value)
            self.message(0xE)
            return self.state
        elif code == 0x13:
            self.message(1)
            self.message(0xE)
        elif code == 0x14:
            self.message(0)
            self.message(0xE)
        elif code == 0x15:
            self.message(0x11, float(self.state == 0))
            return self.state
        elif code == 0x16:
            self.message(0x12, float(self.state == 0))
            return self.state
        elif code == 0x17:
            self.data = int(value)
        return 0


@dataclass(eq=False)
class LightGroup:
    """A light group (FUN_0100adb1; messages FUN_0100a166): an ordered list
    of lights (type-10 tag 1027) plus an animation timer. `interval` is tag
    903 (+0x36); an animation message (0x18..0x1d) runs one step and then
    re-sends itself every `value` seconds (or `interval` if negative) until
    0x22 stops it. Anything it doesn't handle is broadcast to every member
    (last first)."""

    name: str
    timers: Timers
    bus: Bus
    lights: list[Light]
    interval: float = 0.1
    data: int = 0
    animation: int = 0  # +0x3a
    rotating: int = 0  # +0x3e
    _step: float = 0.0  # +0x32
    _timer: int = 0  # +0x46
    _timer2: int = 0  # +0x42

    def reset(self) -> None:
        """FUN_01009feb."""
        for handle in (self._timer, self._timer2):
            if handle:
                self.timers.cancel(handle)
        self._timer = self._timer2 = 0
        self.animation = self.rotating = 0
        self._step = self.interval

    def lit(self) -> bool:
        return any(light.lit() for light in self.lights)

    def _schedule_step(self, value: float) -> None:
        """FUN_0100a04a."""
        if self._timer:
            self.timers.cancel(self._timer)
        self._timer = 0
        if value <= 0.0:
            if value == 0.0:
                self.animation = self.rotating = 0
                return
            self._step = self.interval
        else:
            self._step = value
        self._timer = self.timers.schedule(self._step, self._animate)

    def _animate(self) -> None:
        """FUN_0100a027."""
        self._timer = 0
        self.message(self.animation, self._step)

    def _hold_states(self) -> None:
        """FUN_0100a104: freeze every member in a timed state showing its
        steady state, so a chase can move the temporary states around."""
        for light in reversed(self.lights):
            light.message(9 if light.state else 8)

    def _first_off(self) -> int:
        return next((i for i, light in enumerate(self.lights) if not light.state), -1)

    def _last_on(self) -> int:
        return next((i for i in range(len(self.lights) - 1, -1, -1) if self.lights[i].state), -1)

    def _busy(self, light: Light) -> bool:
        return bool(light.flashing or light.temp_on or light.temp_off)

    def message(self, code: int, value: float = 0.0) -> int:
        lights = self.lights
        n = len(lights)
        if code > 0x3F1:
            if code in (0x3F3, 0x3FC, 0x3FE):
                return 0
            if code == 0x400:
                self.reset()
                return 0
            return self._broadcast(code, value)
        if code in (0x3F0, 0x3F1):
            return 0
        if code == 0x18 or code == 0x19:
            # Shift every member's steady state (and data) one place along,
            # wrapping; refused while the last member is in a timed state.
            if self._busy(lights[-1]):
                return 0
            if self.animation:
                self.message(0x22)
            self.rotating = 1
            self.animation = code
            source = lights[-1] if code == 0x18 else lights[0]
            carried_state, carried_data = source.state, source.data
            order = range(n - 1, 0, -1) if code == 0x18 else range(n - 1)
            for i in order:
                src = lights[i - 1] if code == 0x18 else lights[i + 1]
                lights[i].message(int(src.state != 0))
                lights[i].data = src.data
            target = lights[0] if code == 0x18 else lights[-1]
            target.message(int(carried_state != 0))
            target.data = carried_data
            self._schedule_step(value)
        elif code == 0x1A or code == 0x1B:
            # Chase: move the temporary-on pattern along, steady states kept.
            if self.rotating or not self.animation:
                self._hold_states()
            self.animation = code
            self.rotating = 0
            carried = lights[-1].temp_on if code == 0x1A else lights[0].temp_on
            order = range(n - 1, 0, -1) if code == 0x1A else range(n - 1)
            for i in order:
                src = lights[i - 1] if code == 0x1A else lights[i + 1]
                lights[i].message(8 + (src.temp_on != 0))
            target = lights[0] if code == 0x1A else lights[-1]
            target.message(8 + (carried != 0))
            self._schedule_step(value)
        elif code == 0x1C:
            # Sparkle: each member but the last, 29% of the time, lights for
            # rand/32767 * value * 3 + 0.1 s.
            if self.rotating or not self.animation:
                self._hold_states()
            self.animation = code
            self.rotating = 0
            for light in lights[:-1]:
                if random.randrange(32768) % 100 > 0x46:
                    light.message(9, random.randrange(32768) * 3.0518509476e-05 * value * 3.0 + 0.1)
            self._schedule_step(value)
        elif code == 0x1D:
            if self.rotating or not self.animation:
                self._hold_states()
            self.animation = code
            self.rotating = 0
            for light in lights[:-1]:
                light.message(0x12, float(random.randrange(32768) % 100 > 0x46))
            self._schedule_step(value)
        elif code in (0x1E, 0x1F):
            want_on = code == 0x1F
            candidates = [i for i, light in enumerate(lights) if bool(light.state) == want_on]
            if not candidates:
                return 0
            pick = random.randrange(32768) % len(candidates)
            index = sorted(candidates, reverse=True)[pick]
            lights[index].message(0 if want_on else 1)
            if self.animation:
                self._hold_states()
        elif code in (0x20, 0x21):
            index = self._first_off() if code == 0x20 else self._last_on()
            if index < 0:
                return 0
            lights[index].message(1 if code == 0x20 else 0)
            if self.animation:
                self._hold_states()
            return 1
        elif code == 0x22:
            if self._timer:
                self.timers.cancel(self._timer)
            self._timer = 0
            if self.animation in (0x1A, 0x1B, 0x1C):
                self._broadcast(0xE, 0.0)
            self.animation = self.rotating = 0
        elif code in (0x23, 0x24):
            index = int(value)
            if not 0 <= index < n:
                return 0
            lights[index].message(1 if code == 0x23 else 0)
            if self.animation:
                self._hold_states()
        elif code == 0x25:
            return sum(1 for light in lights if light.state)
        elif code == 0x26:
            return n
        elif code == 0x27:
            return self.animation
        elif code == 0x28:
            return self.rotating
        elif code in (0x29, 0x2A):
            index = self._first_off() if code == 0x29 else self._last_on()
            if index < 0:
                return 0
            if self.animation or self.rotating:
                self.message(0x22)
            lights[index].message(0xF if code == 0x29 else 0x10, value)
            return 1
        elif code == 0x2B:
            if self._timer2:
                self.timers.cancel(self._timer2)
            self._timer2 = 0
            if value > 0:
                self._timer2 = self.timers.schedule(value, self._timer2_end)
        elif code == 0x2C:
            for light in reversed(lights):
                if light.state:
                    light.message(0)
                    light.message(0x10, value)
        elif code == 0x2D:
            # Bargraph: members 0..value on, the rest off (value + 1 lit).
            self.bus.notify(0x2D, self)
            last = int(value)
            if 0 <= last <= n:
                last = min(last, n - 1)
                for light in reversed(lights[last + 1 :]):
                    light.message(0x14)
                for light in reversed(lights[: last + 1]):
                    light.message(0x13)
        elif code == 0x2E:
            index = self._last_on()
            if index >= 0:
                lights[index].message(4)
        else:
            return self._broadcast(code, value)
        return 0

    def _timer2_end(self) -> None:
        """FUN_0100a149."""
        self._timer2 = 0
        self.bus.notify(0x3D, self)

    def _broadcast(self, code: int, value: float) -> int:
        for light in reversed(self.lights):
            light.message(code, value)
        return 0
