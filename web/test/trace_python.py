"""Runs the Python game headless through web/test/scenarios.json and writes
one trace per scenario to web/test/traces/<name>.json, for parity.mjs to
compare the JS port against.

    uv run --project python python web/test/trace_python.py [scenario ...]

Each run is deterministic: `random` is seeded per scenario, every tick gets
a fixed dt (the scenarios' 17/16/17 ms pattern), and math.sin / cos / acos
are routed through fdlibm (web/test/fdlibm.py), the same code the JS port
uses, since the platform libm differs from it in the last bit for a few
percent of inputs (and differs between platforms anyway). The loop mirrors
App.run: input, the pending high-score entry, then a tick only while the
window would tick (focused, no menu / dialog open, or still in the startup
wait). A high-score name entry is answered by typing "REA" and Enter.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "python" / "src"))
sys.path.insert(0, str(HERE))

import fdlibm
import pygame

fdlibm.install()

from space_cadet_pinball import debug_log, highscores
from space_cadet_pinball.menu import HighScoreDialog
from space_cadet_pinball.vec2 import Vec2

debug_log.event = lambda *args, **kwargs: None

KEYS = {
    0x20: pygame.K_SPACE, 0x5A: pygame.K_z, 0xBF: pygame.K_SLASH, 0x58: pygame.K_x, 0xBE: pygame.K_PERIOD,
    0x26: pygame.K_UP, 0x72: pygame.K_F3, 0x71: pygame.K_F2, 0x0D: pygame.K_RETURN, 0x1B: pygame.K_ESCAPE,
    0x52: pygame.K_r, 0x45: pygame.K_e, 0x41: pygame.K_a,
}
NAME_KEYS = [(0x52, "R"), (0x45, "E"), (0x41, "A"), (0x0D, "\r")]


def lights_digest(game) -> str:
    parts = []
    for light in game.lights.values():
        shown = "-" if light.shown is None else str(light.shown)
        parts.append(f"{shown},{light.state},{light.flashing},{light.temp_on},{light.temp_off};")
    return hashlib.md5("".join(parts).encode()).hexdigest()


def run(scenario: dict, dt_pattern: list[int], draw_every: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        highscores.SETTINGS_PATH = Path(tmp) / "pinball_settings.ini"
        sys.argv = ["trace", "-quick"] if scenario["quick"] else ["trace"]
        if scenario["demo"]:
            sys.argv.append("-demo")
        random.seed(scenario["seed"])
        from space_cadet_pinball.app import App

        app = App()
        game = app.game
        events: dict[int, list[dict]] = {}
        for ev in scenario["events"]:
            events.setdefault(ev["tick"], []).append(ev)
        typed: set[int] = set()
        rows, draws = [], {}
        for tick in range(scenario["ticks"]):
            keys = []
            dialog = app.dialog
            if isinstance(dialog, HighScoreDialog) and dialog.entering and id(dialog) not in typed:
                typed.add(id(dialog))
                keys += [(vk, True, ch) for vk, ch in NAME_KEYS]
            for ev in events.get(tick, []):
                kind = ev["type"]
                if kind == "key":
                    keys.append((ev["vk"], ev["down"], ev.get("char", "")))
                elif kind == "set_ball":
                    app.ball.position = Vec2(*ev["pos"])
                    app.ball.velocity = Vec2(*ev["vel"])
                elif kind == "notify":
                    game.bus.notify(ev["code"], game.objects[ev["name"]])
                elif kind == "msg":
                    game.msg(ev["name"], ev["code"], ev["value"])
            for vk, down, ch in keys:
                kind = pygame.KEYDOWN if down else pygame.KEYUP
                pygame.event.post(pygame.event.Event(kind, key=KEYS[vk], mod=0, unicode=ch, scancode=0))
            app._handle_events()
            app._next_high_score_entry()
            if app._first_game_ms > 0 or (app.focused and not app._modal()):
                app._update(dt_pattern[tick % len(dt_pattern)] / 1000.0)
            b = app.ball
            rows.append([
                tick, b.position.x, b.position.y, b.velocity.x, b.velocity.y, b.z, b.mask, int(b.held), int(b.alive),
                game.score, game.balls, game.mode, len(game.timers._queue), app.tilt_heat, lights_digest(game),
                game.info_text, game.mission_text, app.left_flipper.state, app.right_flipper.state,
                app.plunger.kick, game.data("lite198"), game.player_number, int(app.dialog is not None),
            ])
            if tick % draw_every == 0:
                app._draw()
                draws[tick] = hashlib.sha1(app.renderer.screen.tobytes()).hexdigest()
        pygame.quit()
        return {
            "name": scenario["name"],
            "rows": rows,
            "draws": draws,
            "high_scores": [[e.name, e.score] for e in game.high_scores.entries],
        }


def main() -> None:
    spec = json.loads((HERE / "scenarios.json").read_text())
    wanted = set(sys.argv[1:])
    out_dir = HERE / "traces"
    out_dir.mkdir(exist_ok=True)
    for scenario in spec["scenarios"]:
        if wanted and scenario["name"] not in wanted:
            continue
        trace = run(scenario, spec["dt_ms"], spec["draw_every"])
        (out_dir / f"{scenario['name']}.json").write_text(json.dumps(trace))
        last = trace["rows"][-1]
        print(f"{scenario['name']}: {len(trace['rows'])} ticks, score {last[9]}, balls {last[10]}, mode {last[11]}")


if __name__ == "__main__":
    main()
