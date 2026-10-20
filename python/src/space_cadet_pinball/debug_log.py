"""Writes a plain-text trace of gameplay events to a file in the project
root, so the ball's trajectory and the collisions/events it triggers can be
inspected after a play session instead of relying on a verbal description.

Enabled by default; set the PINBALL_DEBUG_LOG environment variable to a
path to redirect it, or to "" (empty) to disable it entirely.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "pinball_debug.log"

log = logging.getLogger("space_cadet_pinball.trace")
log.propagate = False


def setup() -> Path | None:
    path_str = os.environ.get("PINBALL_DEBUG_LOG", str(_DEFAULT_PATH))
    if not path_str:
        log.addHandler(logging.NullHandler())
        return None
    path = Path(path_str)
    handler = logging.FileHandler(path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    return path


def event(frame: int, kind: str, **fields: object) -> None:
    details = " ".join(f"{k}={v}" for k, v in fields.items())
    log.debug("[frame %6d] %-12s %s", frame, kind, details)
