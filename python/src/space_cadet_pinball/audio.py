"""Loads and plays the original game's sound effects and music.

Sounds are played by the WAV file name a PINBALL.DAT sound entry gives
(type-0 value 202, type-9 path) -- the targets of every object's sound
references (tags 304 / 406 / 1100 / 1101 and the `soundwaveN` objects),
resolved in game.py. FUN_0100901f only maps those entries to its own
registration slots, an internal cache index with no meaning outside it."""

from __future__ import annotations

import logging
import time

import pygame

from .assets import SOUNDS_DIR

log = logging.getLogger(__name__)

# WaveMix is opened with the "Voices" option's channel count (default 8, at
# most 8; FUN_01006973); every effect plays on channels 0..7, clamped to
# that count (FUN_01009895 -> FUN_01006c26).
CHANNELS = 8


class AudioManager:
    def __init__(self, voices: int = CHANNELS) -> None:
        self._files: dict[str, pygame.mixer.Sound] = {}
        self._index = None
        self._enabled = False
        # Options > Sounds (FUN_01006d34): lengths are still reported (the
        # game times things by them), the sound just isn't played.
        self._effects_enabled = True
        self._channels: list[pygame.mixer.Channel] = []
        voices = max(1, min(CHANNELS, voices))
        self._started = [0.0] * voices  # DAT_01024f1c: when each channel last started
        try:
            pygame.mixer.init()
            pygame.mixer.set_num_channels(voices)
            self._channels = [pygame.mixer.Channel(i) for i in range(voices)]
            self._enabled = True
        except pygame.error as exc:
            log.warning("Audio disabled (no mixer device available): %s", exc)

    @property
    def effects_enabled(self) -> bool:
        return self._effects_enabled

    @effects_enabled.setter
    def effects_enabled(self, on: bool) -> None:
        """FUN_01006d34(0, 7, on): turning the channels off also stops them
        (FUN_01006bcc)."""
        self._effects_enabled = on
        if not on:
            self.stop_effects()

    def stop_effects(self) -> None:
        """FUN_01006bcc on every channel; also what WaveMixActivate(FALSE)
        amounts to when the app is deactivated (FUN_01006b8a): the device is
        released and whatever was playing stops."""
        for k, channel in enumerate(self._channels):
            channel.stop()
            self._started[k] = 0.0

    def play_file(self, filename: str) -> float:
        """Play an original WAV by its PINBALL.DAT file name (e.g.
        "sound12.wav"); returns its length the way the original computes it
        (file size * 9.0909e-05 s, FUN_0100901f)."""
        path = self._find(filename)
        if path is None:
            return 0.0
        duration = path.stat().st_size * 9.090909e-05
        if not self._enabled or not self.effects_enabled:
            return duration
        sound = self._files.get(path.name)
        if sound is None:
            try:
                sound = pygame.mixer.Sound(str(path))
            except pygame.error as exc:
                log.warning("Could not load %s: %s", path.name, exc)
                return duration
            self._files[path.name] = sound
        self._play_on_channel(sound)
        return duration

    def _play_on_channel(self, sound: pygame.mixer.Sound) -> None:
        """FUN_01006c26(wave, 0, 7, 5, 0): the channel that started longest
        ago (the lowest one on a tie) gets the sound, cutting off whatever it
        was playing."""
        if not self._channels:
            return
        best = 0
        for k in range(1, len(self._channels)):
            if self._started[k] < self._started[best]:
                best = k
        self._started[best] = time.monotonic()
        self._channels[best].play(sound)

    def _find(self, filename: str):
        if self._index is None:
            self._index = {p.name.lower(): p for p in SOUNDS_DIR.iterdir()} if SOUNDS_DIR.exists() else {}
        return self._index.get(filename.lower())

    def stop_music(self) -> None:
        """FUN_0100afb9 (MCI_STOP)."""
        if self._enabled:
            pygame.mixer.music.stop()

    def play_music(self, filename: str, loops: int = -1) -> None:
        if not self._enabled:
            return
        path = self._find(filename)
        if path is None:
            return
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play(loops)
        except pygame.error as exc:
            log.warning("Could not play music %s: %s", filename, exc)
