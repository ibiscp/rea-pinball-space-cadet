"""The high-score table (DAT_01025578: 5 entries of a 32-byte name and a
score) and the original's settings, stored the way Pinball.exe stores them
in the registry under Software\\Microsoft\\Plus!\\Pinball\\SpaceCadet --
here in a git-ignored `pinball_settings.ini` in the project root, same
value names.

- FUN_01004d18 (load): "0.Name" .. "4.Name", "0.Score" .. "4.Score" and
  "Verification" = the sum of every name's characters (signed) plus every
  score; a mismatch (a fresh install included) clears the table.
- FUN_01004e87 (save, at exit from FUN_0101566e): the same values.
- FUN_01004c3c (clear): every name empty, every score -999 (shown blank).
- FUN_01004c60 (rank): a score above 0 ranks above the first entry it
  beats strictly; -1 = no place.
- FUN_01004c8d (insert): the entries from `rank` down move one place, the
  name is cut to 31 characters.
- FUN_01004f99 (format): -999 = blank, else thousands groups with the
  system's thousands separator (default ",").
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

from .assets import PROJECT_ROOT

SETTINGS_PATH = PROJECT_ROOT / "pinball_settings.ini"
SCORES_SECTION = "SpaceCadet"  # string 166 under string 165's key
OPTIONS_SECTION = "Pinball"  # the options sit on string 165's key itself
CLEARED = -999
ENTRIES = 5
NAME_LIMIT = 31


@dataclass
class Entry:
    name: str = ""
    score: int = CLEARED


def _signed(ch: str) -> int:
    value = ord(ch) & 0xFF
    return value - 256 if value >= 128 else value


def _checksum(entries: list[Entry]) -> int:
    total = 0
    for entry in entries:
        total += sum(_signed(ch) for ch in entry.name)
        total += entry.score
    return total


def _cdiv(a: int, b: int) -> int:
    """C integer division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _cmod(a: int, b: int) -> int:
    return a - _cdiv(a, b) * b


def format_score(score: int, separator: str = ",") -> str:
    """FUN_01004f99."""
    if score == CLEARED:
        return ""
    billions = _cdiv(score, 1_000_000_000)
    millions = _cdiv(_cmod(score, 1_000_000_000), 1_000_000)
    thousands = _cdiv(_cmod(score, 1_000_000), 1000)
    units = _cmod(score, 1000)
    if billions >= 1:
        return f"{billions}{separator}{millions:03d}{separator}{thousands:03d}{separator}{units:03d}"
    if millions >= 1:
        return f"{millions}{separator}{thousands:03d}{separator}{units:03d}"
    if thousands >= 1:
        return f"{thousands}{separator}{units:03d}"
    return str(score)


class HighScores:
    def __init__(self) -> None:
        self.entries = [Entry() for _ in range(ENTRIES)]

    def clear(self) -> None:
        """FUN_01004c3c."""
        self.entries = [Entry() for _ in range(ENTRIES)]

    def score(self, rank: int) -> int:
        return self.entries[rank].score

    def rank(self, score: int) -> int:
        """FUN_01004c60."""
        if score > 0:
            for i, entry in enumerate(self.entries):
                if entry.score < score:
                    return i
        return -1

    def insert(self, score: int, name: str, rank: int) -> int:
        """FUN_01004c8d."""
        if rank < 0:
            return rank
        if rank < ENTRIES:
            self.entries.insert(rank, Entry())
            del self.entries[ENTRIES:]
        entry = self.entries[min(rank, ENTRIES - 1)]
        entry.score = score
        entry.name = name[:NAME_LIMIT]
        return rank

    # -- storage ----------------------------------------------------------------
    def load(self, path: Path | None = None) -> None:
        """FUN_01004d18: missing values read as "" (score 0); a wrong
        "Verification" clears the table."""
        self.clear()
        config = _read(path or SETTINGS_PATH)
        values = config[SCORES_SECTION] if config.has_section(SCORES_SECTION) else {}
        for i, entry in enumerate(self.entries):
            entry.name = values.get(f"{i}.Name", "")[:NAME_LIMIT]
            entry.score = _atol(values.get(f"{i}.Score", ""))
        if values.get("Verification", "") != str(_checksum(self.entries)):
            self.clear()

    def save(self, path: Path | None = None) -> None:
        """FUN_01004e87."""
        path = path or SETTINGS_PATH
        config = _read(path)
        if not config.has_section(SCORES_SECTION):
            config.add_section(SCORES_SECTION)
        section = config[SCORES_SECTION]
        for i, entry in enumerate(self.entries):
            section[f"{i}.Name"] = entry.name
            section[f"{i}.Score"] = str(entry.score)
        section["Verification"] = str(_checksum(self.entries))
        _write(config, path)


def load_option(name: str, default: int, path: Path | None = None) -> int:
    """The options FUN_01006070 reads (Sounds, Music, FullScreen, Players,
    ...); a missing value keeps the default."""
    config = _read(path or SETTINGS_PATH)
    if config.has_section(OPTIONS_SECTION) and name in config[OPTIONS_SECTION]:
        return _atol(config[OPTIONS_SECTION][name])
    return default


def save_options(options: dict[str, int], path: Path | None = None) -> None:
    """FUN_010055f3, at exit."""
    path = path or SETTINGS_PATH
    config = _read(path)
    if not config.has_section(OPTIONS_SECTION):
        config.add_section(OPTIONS_SECTION)
    for name, value in options.items():
        config[OPTIONS_SECTION][name] = str(value)
    _write(config, path)


def _atol(text: str) -> int:
    text = text.strip()
    digits = ""
    for i, ch in enumerate(text):
        if ch.isdigit() or (i == 0 and ch in "+-"):
            digits += ch
        else:
            break
    try:
        return int(digits)
    except ValueError:
        return 0


def _read(path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # value names keep their case, like registry values
    try:
        config.read(path, encoding="latin-1")
    except (OSError, configparser.Error):
        pass
    return config


def _write(config: configparser.ConfigParser, path: Path) -> None:
    try:
        with open(path, "w", encoding="latin-1") as handle:
            config.write(handle)
    except OSError:
        pass
