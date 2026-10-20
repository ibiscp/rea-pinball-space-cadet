"""The mission state machine (FUN_01011bb5 and its 33 state handlers).

The current state is lite198's data value: 0 = no mission (waiting for the
launch), 1 = choosing one (the mission targets a_targ13..15 pick a mission
by rank -- the middle circle -- and the ramp accepts it), 2..18 = the
missions, 0x14..0x1f = later stages of multi-stage missions, 0x20 = game
over. Every notification goes to the current state's handler after the
object's own listener (logic.Bus). Handlers use 0x42 (state entered), 0x43
(redisplay the mission text) and 0x3f (an object scored) the same way the
original does; the progress counter is lite56's data value. Mission and
rank names come from the tables at 0x1024708 / 0x10246ec, the acceptance
awards from 0x10246a0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .strings import STRINGS

if TYPE_CHECKING:
    from .game import Game

# DAT_01024708: mission index -> name string id
MISSION_NAMES = {
    2: 60, 3: 61, 4: 62, 5: 63, 6: 64, 7: 65, 8: 66, 9: 67, 10: 68,
    11: 69, 12: 70, 13: 71, 14: 72, 15: 73, 16: 74, 17: 75, 18: 76,
}
# 0x10246a0: points awarded on accepting a mission
ACCEPT_POINTS = {**dict.fromkeys(range(2, 6), 10000), **dict.fromkeys(range(6, 15), 20000),
                 **dict.fromkeys(range(15, 19), 30000)}
# DAT_010246ec: rank names, by middle-circle lights lit
RANKS = (84, 85, 86, 87, 88, 89, 90, 91, 92)
# FUN_0100e6d2: mission chosen by rank (middle circle lit count) and target
# (1 = a_targ13, 2 = a_targ14, 3 = a_targ15, 4 = all three lit)
SELECTION = {
    1: {1: 3, 2: 4, 3: 2, 4: 5},
    2: {1: 9, 2: 0xB, 3: 10, 4: 0x10},
    3: {1: 9, 2: 0xB, 3: 10, 4: 0x10},
    4: {1: 6, 2: 8, 3: 7, 4: 0xF},
    5: {1: 6, 2: 8, 3: 7, 4: 0xF},
    6: {1: 0xC, 2: 0xD, 3: 0xE, 4: 0x11},
    7: {1: 0xC, 2: 0xD, 3: 0xE, 4: 0x11},
    8: {1: 0xF, 2: 0x10, 3: 0x11, 4: 0x12},
    9: {1: 0xF, 2: 0x10, 3: 0x11, 4: 0x12},
}

ATTACK_BUMPERS = ("a_bump1", "a_bump2", "a_bump3", "a_bump4")
BANK_TARGETS = ("a_targ1", "a_targ2", "a_targ3", "a_targ6", "a_targ5", "a_targ4", "a_targ9", "a_targ8", "a_targ7")
DROP_TARGETS = tuple(f"a_targ{i}" for i in range(10, 23))
LANE_ROLLOVERS = ("a_roll3", "a_roll2", "a_roll1", "a_roll112", "a_roll111", "a_roll110", "a_roll4", "a_roll8",
                  "a_roll6", "a_roll7", "a_roll5")
REBOUNDS = ("v_rebo1", "v_rebo2", "v_rebo3", "v_rebo4")
FLAGS = ("a_flag1", "a_flag2")
TREKS = ("l_trek_lights", "r_trek_lights")


def _name(obj: object) -> str:
    return getattr(obj, "name", "")


class Missions:
    """Mixin for Game: the mission dispatcher and handlers."""

    # -- helpers --------------------------------------------------------------
    def _mission_text(self: Game, string: int, *args: object, seconds: float = -1.0) -> None:
        self.text("mission", string, seconds, *args)

    def _goal_hint(self: Game, show: str, hide: tuple[str, ...]) -> None:
        for light in hide:
            if self.lit(light):
                self.msg(light, 0x14)
        if not self.lit(show):
            self.msg(show, 7)

    def _rank_progress(self: Game, steps: int) -> int:
        """FUN_0100e50b: light lite16 (bonus), add `steps` outer-circle
        lights; a full outer circle promotes (middle circle +1, "Promotion to
        <rank>") and returns 1."""
        self.msg("lite16", 0x13)
        outer = self.objects["outer_circle"]
        for _ in range(steps):
            outer.message(0x29, 2.0)
        lit, total = outer.message(0x25), outer.message(0x26)
        if lit == total:
            outer.message(0x10, 5.0)
            middle = self.objects["middle_circle"]
            middle.message(0x22)
            rank = middle.message(0x25)
            if rank < 9:
                middle.message(0x29, 5.0)
                self._mission_text(83, STRINGS[RANKS[rank]], seconds=8.0)
                self.play("soundwave10")
            return 1
        if (total * 3) // 4 <= lit:
            self.msg("middle_circle", 0x1B, -1.0)
        return 0

    def _complete(self: Game, lights: tuple[str, ...], done_text: int, award: int, rank: int,
                  done_box: str = "mission") -> None:
        for light in lights:
            self.msg(light, 0x14)
        self.set_data("lite198", 1)
        self._mission(0x42, None)
        self.text(done_box, done_text, 4.0)
        added = self.award(award)
        if self._rank_progress(rank) == 0:
            self._mission_text(78, added, seconds=8.0)
            self.play("soundwave9")

    def _count(self: Game, code: int, obj: object, members: tuple[str, ...], count: int, lights: tuple[str, ...],
               progress: int, finish, setup=None) -> None:
        """The counting-mission shape most handlers share: 0x42 sets the
        count (lite56.data) and flashes the goal lights; each 0x3f from a
        member counts down (redisplaying), and 0 finishes."""
        if code == 0x3F:
            if _name(obj) not in members:
                return
            left = self.data("lite56") - 1
            self.set_data("lite56", left)
            if left == 0:
                finish()
            else:
                self._mission(0x43, obj)
            return
        if code == 0x42:
            self.set_data("lite56", count)
            if setup is not None:
                setup()
            for light in lights:
                self.msg(light, 7)
        elif code != 0x43:
            return
        self._mission_text(progress, self.data("lite56"))

    def _reset_bank_targets(self: Game) -> None:
        for name in BANK_TARGETS:
            self.set_data(name, 0)
            self.msg(name, 0x32)

    def _start_treks(self: Game) -> None:
        for group in TREKS:
            self.msg(group, 0x14)
            self.msg(group, 0x20, 0.2)
            self.msg(group, 0x1A, 0.2)

    # -- dispatcher -----------------------------------------------------------
    def _mission(self: Game, code: int, obj: object) -> None:
        """FUN_01011bb5."""
        state = self.data("lite198")
        if code == 0x2F:
            if obj is self.objects.get("fuel_bargraph") and state > 1:
                for group in TREKS:
                    self.msg(group, 0x22)
                    self.msg(group, 0x14)
                self._mission_text(109, seconds=4.0)
                self.set_data("lite198", 1)
                self._mission(0x42, None)
            # The 0x2f still goes on to the handler of the state it arrived in.
        elif code == 0x3C:
            if obj is self.objects.get("fuel_bargraph") and state != 0:
                if self.msg("fuel_bargraph", 0x25) == 1:
                    self._mission_text(116, seconds=4.0)
            elif _name(obj) == "mission_text_box":
                code = 0x43
        elif code == 0x3F1:
            code = 0x43
        handler = self._mission_handlers().get(state)
        if handler is None:
            self.set_data("lite198", 1)
            self._mission(0x42, None)
            return
        handler(code, obj)

    def _mission_handlers(self: Game) -> dict:
        return {
            0: self._m_none, 1: self._m_select, 2: self._m_target_practice, 3: self._m_launch_training,
            4: self._m_reentry_training, 5: self._m_science, 6: self._m_stray_comet, 7: self._m_black_hole,
            8: self._m_space_radiation, 9: self._m_bug_hunt, 10: self._m_alien_menace, 11: self._m_rescue,
            12: self._m_satellite, 13: self._m_recon, 14: self._m_doomsday, 15: self._m_cosmic_plague,
            16: self._m_secret, 17: self._m_time_warp, 18: self._m_maelstrom, 0x14: self._m_alien_menace_2,
            0x15: self._m_cosmic_plague_2, 0x16: self._m_secret_2, 0x17: self._m_secret_3,
            0x18: self._m_time_warp_2, 0x19: self._m_maelstrom_2, 0x1A: self._m_maelstrom_3,
            0x1B: self._m_maelstrom_4, 0x1C: self._m_maelstrom_5, 0x1D: self._m_maelstrom_6,
            0x1E: self._m_maelstrom_7, 0x1F: self._m_maelstrom_8, 0x20: self._m_game_over,
        }

    # -- 0 / 1 ------------------------------------------------------------------
    def _m_none(self: Game, code: int, obj: object) -> None:
        """FUN_0100e657: the launch (s_onewy4 / s_onewy10) opens mission
        selection."""
        if code == 0x3F:
            if _name(obj) in ("s_onewy4", "s_onewy10"):
                self.set_data("lite198", 1)
                self._mission(0x42, None)
        elif code == 0x42:
            self.clear_text("mission")
        elif code == 0x43:
            self._mission_text(50)

    def _m_select(self: Game, code: int, obj: object) -> None:
        """FUN_0100e6d2: choose with a_targ13..15, accept on the ramp."""
        if code in (0x2D, 0x2F):
            if obj is not self.objects.get("fuel_bargraph"):
                return
        elif code != 0x3F:
            if code == 0x42:
                self.msg("lite198", 0x14)
                self.msg("outer_circle", 0x22)
                self.msg("ramp_tgt_lights", 0x14)
                self.set_data("lite56", 0)
                self.set_data("lite101", 0)
                for group in TREKS:
                    self.msg(group, 0x22)
                    self.msg(group, 0x14)
                self.msg("goal_lights", 0x14)
            elif code != 0x43:
                return
            if self.msg("fuel_bargraph", 0x25) == 0:
                self._mission_text(105)
                self._goal_hint("lite318", ("lite317", "lite319"))
            elif not self.lit("lite56"):
                self._mission_text(104)
                self._goal_hint("lite319", ("lite317", "lite318"))
            else:
                name = STRINGS[MISSION_NAMES.get(self.data("lite56"), 60)]
                self._mission_text(106, name)
                self._goal_hint("lite317", ("lite318", "lite319"))
            return
        else:
            pick = {"a_targ13": 1, "a_targ14": 2, "a_targ15": 3}.get(_name(obj), 0)
            if pick == 0:
                if _name(obj) == "ramp" and self.lit("lite56") and self.msg("fuel_bargraph", 0x25) != 0:
                    self.msg("lite56", 0x14)
                    self.msg("lite198", 0x13)
                    self.msg("outer_circle", 0x1A, -1.0)
                    for light in ("lite317", "lite318", "lite319"):
                        if self.lit(light):
                            self.msg(light, 0x14)
                    mission = self.data("lite56")
                    self.set_data("lite198", mission)
                    self._mission(0x42, None)
                    added = self.award(ACCEPT_POINTS.get(mission, 0))
                    self._mission_text(77, added, seconds=4.0)
                return
            if self.data("lite101") == 7:
                self.set_data("lite101", 0)
                pick = 4
            choices = SELECTION.get(self.msg("middle_circle", 0x25))
            if choices is None:
                return
            self.set_data("lite56", choices[pick])
            self.msg("lite56", 0xF, 2.0)
            self.msg("lite198", 4)
        self._mission(0x43, obj)

    # -- missions ---------------------------------------------------------------
    def _m_target_practice(self: Game, code: int, obj: object) -> None:
        """FUN_0100ebf3: 8 attack-bumper hits."""
        self._count(code, obj, ATTACK_BUMPERS, 8, ("lite308", "lite311"), 107,
                    lambda: self._complete(("lite308", "lite311"), 108, 500000, 6))

    def _m_launch_training(self: Game, code: int, obj: object) -> None:
        """FUN_0100ed83: 3 ramp launches."""
        self._count(code, obj, ("ramp",), 3, ("lite317",), 110,
                    lambda: self._complete(("lite317",), 111, 500000, 6))

    def _m_reentry_training(self: Game, code: int, obj: object) -> None:
        """FUN_0100eed7: 3 passes over a_roll1..3 (the trek lights chase)."""
        self._count(code, obj, ("a_roll3", "a_roll2", "a_roll1"), 3, ("lite307",), 112,
                    lambda: self._complete(("lite307",), 113, 500000, 6), setup=self._start_treks)

    def _m_science(self: Game, code: int, obj: object) -> None:
        """FUN_0100f0b3: 9 hits on the three standup banks."""
        lights = ("lite303", "lite309", "lite315")
        self._count(code, obj, BANK_TARGETS, 9, lights, 114,
                    lambda: self._complete(lights, 115, 750000, 9), setup=self._reset_bank_targets)

    def _m_stray_comet(self: Game, code: int, obj: object) -> None:
        """FUN_0100f381: fill the right hazard bank (a_targ19..21, lite107
        bits = 7), then the hyperspace kickout."""
        name = _name(obj)
        if code == 0x3F:
            if name in ("a_targ19", "a_targ20", "a_targ21"):
                if self.data("lite107") == 7:
                    self.msg("lite306", 0x14)
                    self.msg("lite304", 7)
                    self.set_data("lite107", 0xF)
                    self._mission(0x43, obj)
            elif name == "a_kout2" and self.data("lite107") == 0xF:
                self._complete(("lite304",), 119, 1000000, 8)
            return
        if code == 0x42:
            self.msg("bpr_solotgt_lights", 0x14)
            self.set_data("lite107", 0)
            self.msg("lite306", 7)
        elif code != 0x43:
            return
        self._mission_text(118 if self.data("lite107") == 0xF else 117)

    def _m_black_hole(self: Game, code: int, obj: object) -> None:
        """FUN_0100f6f4: upgrade the launch bumpers, then the black hole
        (a_kout3)."""
        bumper = self.bumpers.get("a_bump5")
        if code == 0xB:
            if _name(obj) == "a_bump5":
                self._mission(0x43, obj)
            return
        if code == 0x3F:
            if _name(obj) == "a_kout3" and bumper is not None and bumper.level != 0:
                for light in ("lite316", "lite314"):
                    if self.lit(light):
                        self.msg(light, 0x14)
                self._complete((), 124, 1000000, 8)
            return
        if code == 0x42:
            self.msg("launch_bumpers", 0xB, 0.0)
        elif code != 0x43:
            return
        if bumper is None or bumper.level == 0:
            self._mission_text(122)
            self._goal_hint("lite316", ("lite314",))
        else:
            self._mission_text(123)
            self._goal_hint("lite314", ("lite316",))

    def _m_space_radiation(self: Game, code: int, obj: object) -> None:
        """FUN_0100f539: fill the left hazard bank (a_targ16..18, lite104
        bits = 7), then a wormhole."""
        name = _name(obj)
        if code == 0x3F:
            if name in ("a_targ16", "a_targ17", "a_targ18"):
                if self.data("lite104") == 7:
                    self.set_data("lite104", 0xF)
                    self.msg("bsink_arrow_lights", 7)
                    self.msg("lite313", 0x14)
                    self._mission(0x43, obj)
                    self._advance_wormhole(1)
            elif name in ("v_sink1", "v_sink2", "v_sink3") and self.data("lite104") == 0xF:
                self._complete((), 121, 1000000, 8)
            return
        if code == 0x42:
            self.msg("lchute_tgt_lights", 0x14)
            self.set_data("lite104", 0)
            self.msg("lite313", 7)
        elif code != 0x43:
            return
        self._mission_text(120 if self.data("lite104") == 0xF else 176)

    def _m_bug_hunt(self: Game, code: int, obj: object) -> None:
        """FUN_0100f900: 15 target hits."""
        lights = ("lite306", "lite308", "lite310", "lite313", "lite319")

        def setup() -> None:
            self._reset_bank_targets()
            for group in ("top_circle_tgt_lights", "ramp_tgt_lights", "lchute_tgt_lights", "bpr_solotgt_lights"):
                self.msg(group, 0x14)

        self._count(code, obj, BANK_TARGETS + DROP_TARGETS, 15, lights, 125,
                    lambda: self._complete(lights, 126, 750000, 7), setup=setup)

    def _m_alien_menace(self: Game, code: int, obj: object) -> None:
        """FUN_0100ff35: upgrade the attack bumpers, then stage 0x14."""
        if code == 0xB:
            bumper = self.bumpers.get("a_bump1")
            if _name(obj) == "a_bump1" and bumper is not None and bumper.level != 0:
                self.msg("lite307", 0x14)
                self.set_data("lite198", 0x14)
                self._mission(0x42, None)
            return
        if code == 0x42:
            self.msg("attack_bumpers", 0xB, 0.0)
            self._start_treks()
            self.msg("lite307", 7)
        elif code != 0x43:
            return
        self._mission_text(175)

    def _m_alien_menace_2(self: Game, code: int, obj: object) -> None:
        """FUN_01010051: then 8 attack-bumper hits."""
        lights = ("lite308", "lite311")

        def setup() -> None:
            for group in TREKS:
                self.msg(group, 0x22)
                self.msg(group, 0x14)

        self._count(code, obj, ATTACK_BUMPERS, 8, lights, 107,
                    lambda: self._complete(lights, 130, 750000, 7), setup=setup)

    def _m_rescue(self: Game, code: int, obj: object) -> None:
        """FUN_0100fcd9: light the flags (a_targ1..3 / lite20), then the
        hyperspace kickout."""
        name = _name(obj)
        if code == 0x3F:
            if name in ("a_targ1", "a_targ2", "a_targ3"):
                self._mission(0x43, obj)
            elif name == "a_kout2" and self.lit("lite20"):
                left = self.data("lite56") - 1
                self.set_data("lite56", left)
                if left == 0:
                    for light in ("lite303", "lite304"):
                        if self.lit(light):
                            self.msg(light, 0x14)
                    self._complete((), 129, 750000, 7)
                else:
                    self._mission(0x43, obj)
            return
        if code == 0x42:
            self.msg("lite20", 0x14)
            self.msg("lite19", 0x14)
            self.set_data("lite56", 1)
        elif code != 0x43:
            return
        if not self.lit("lite20"):
            self._mission_text(127)
            self._goal_hint("lite303", ("lite304",))
        else:
            self._mission_text(128)
            self._goal_hint("lite304", ("lite303",))

    def _m_satellite(self: Game, code: int, obj: object) -> None:
        """FUN_0101022d: 3 hits on a_bump4."""
        self._count(code, obj, ("a_bump4",), 3, ("lite308",), 132,
                    lambda: self._complete(("lite308",), 133, 1250000, 9))

    def _m_recon(self: Game, code: int, obj: object) -> None:
        """FUN_01010385: 15 lane passes."""
        lights = ("lite301", "lite302", "lite307", "lite316", "lite320", "lite321")
        self._count(code, obj, LANE_ROLLOVERS, 15, lights, 134,
                    lambda: self._complete(lights, 136, 1250000, 9))

    def _m_doomsday(self: Game, code: int, obj: object) -> None:
        """FUN_010105e3: 3 outlane passes."""
        lights = ("lite301", "lite320")
        self._count(code, obj, ("a_roll4", "a_roll8"), 3, lights, 137,
                    lambda: self._complete(lights, 138, 1250000, 9))

    def _m_cosmic_plague(self: Game, code: int, obj: object) -> None:
        """FUN_01010767: 75 flag spins (lite19/20 lit), then stage 0x15."""
        lights = ("lite305", "lite312")

        def finish() -> None:
            for light in lights:
                self.msg(light, 0x14)
            self.set_data("lite198", 0x15)
            self._mission(0x42, None)
            self.msg("lite20", 0x14)
            self.msg("lite19", 0x14)

        def setup() -> None:
            self.msg("lite20", 0x13)
            self.msg("lite19", 0x13)

        self._count(code, obj, FLAGS, 75, lights, 139, finish, setup=setup)

    def _m_cosmic_plague_2(self: Game, code: int, obj: object) -> None:
        """FUN_010108bc: then the space-warp rollover (a_roll9)."""
        if code == 0x3F:
            if _name(obj) == "a_roll9":
                self._complete(("lite310",), 141, 1750000, 11)
            return
        if code == 0x42:
            self.msg("lite310", 7)
        elif code != 0x43:
            return
        self._mission_text(140)

    def _m_secret(self: Game, code: int, obj: object) -> None:
        """FUN_010109d5: the yellow wormhole (v_sink3), then 0x16."""
        if code == 0x3F:
            if _name(obj) == "v_sink3":
                self.set_data("lite198", 0x16)
                self._mission(0x42, None)
            return
        if code == 0x42:
            self.msg("worm_hole_lights", 0x14)
            self.msg("bsink_arrow_lights", 0x14)
            self.msg("bsink_arrow_lights", 0x17, 0.0)
            self.msg("lite110", 0x14)
            self.msg("lite7", 0x13)
            self.msg("lite3", 0xB, 0.0)
            self.msg("lite3", 0x13)
            self.msg("lite3", 7)
        elif code != 0x43:
            return
        self._mission_text(142)

    def _m_secret_2(self: Game, code: int, obj: object) -> None:
        """FUN_01010ad3: the red wormhole (v_sink1), then 0x17."""
        if code == 0x3F:
            if _name(obj) == "v_sink1":
                self.set_data("lite198", 0x17)
                self._mission(0x42, None)
            return
        if code == 0x42:
            self.msg("lite5", 0x13)
            self.msg("lite4", 0xB, 2.0)
            self.msg("lite4", 0x13)
            self.msg("lite4", 7)
        elif code != 0x43:
            return
        self._mission_text(143)

    def _m_secret_3(self: Game, code: int, obj: object) -> None:
        """FUN_01010b85: the green wormhole (v_sink2) completes it."""
        if code == 0x3F:
            if _name(obj) == "v_sink2":
                self.set_data("lite198", 1)
                self._mission(0x42, None)
                self._mission_text(145, seconds=4.0)
                added = self.award(1500000)
                if self._rank_progress(10) == 0:
                    self._mission_text(78, added, seconds=8.0)
                    self.play("soundwave9")
            return
        if code == 0x42:
            self.msg("lite6", 0x13)
            self.msg("lite2", 0xB, 1.0)
            self.msg("lite2", 0x13)
            self.msg("lite2", 7)
        elif code != 0x43:
            return
        self._mission_text(144)

    def _m_time_warp(self: Game, code: int, obj: object) -> None:
        """FUN_01010cc2: 25 rebound hits, then stage 0x18."""
        lights = ("lite300", "lite322")

        def finish() -> None:
            for light in lights:
                self.msg(light, 0x14)
            self.set_data("lite198", 0x18)
            self._mission(0x42, None)

        self._count(code, obj, REBOUNDS, 25, lights, 146, finish)

    def _m_time_warp_2(self: Game, code: int, obj: object) -> None:
        """FUN_01010dd3: the hyperspace chute warps back a rank, the ramp
        forward one (2,000,000 either way)."""
        name = _name(obj)
        if code == 0x3F:
            if name == "a_kout2":
                self._mission_text(47, seconds=4.0)
                middle = self.objects["middle_circle"]
                if middle.message(0x25) > 1:
                    middle.message(0x21, 5.0)
                    rank = middle.message(0x25)
                    self._mission_text(174, STRINGS[RANKS[rank - 1]], seconds=8.0)
            elif name == "ramp":
                self._mission_text(46, seconds=4.0)
                middle = self.objects["middle_circle"]
                message = None
                if middle.message(0x25) < 9:
                    rank = middle.message(0x25)
                    middle.message(0x29, 5.0)
                    message = STRINGS[173].replace("%s", STRINGS[RANKS[rank]])
                if self._rank_progress(12) == 0 and message is not None:
                    self._mission_text(message, seconds=8.0)
                    self.play("soundwave10")
            else:
                return
            self.award(2000000)
            for light in ("lite55", "lite26", "lite304", "lite317"):
                self.msg(light, 0x14)
            self.set_data("lite198", 1)
            self._mission(0x42, None)
            return
        if code == 0x42:
            self.msg("lite55", 7, -1.0)
            self.msg("lite26", 7, -1.0)
            self.msg("lite304", 7)
            self.msg("lite317", 7)
        elif code != 0x43:
            return
        self._mission_text(147)

    def _stage(self: Game, code: int, obj: object, members: tuple[str, ...], count: int,
               lights: tuple[str, ...], progress: int, next_state: int) -> None:
        def finish() -> None:
            for light in lights:
                self.msg(light, 0x14)
            self.set_data("lite198", next_state)
            self._mission(0x42, None)

        self._count(code, obj, members, count, lights, progress, finish)

    def _m_maelstrom(self: Game, code: int, obj: object) -> None:
        """FUN_0101106f: Maelstrom stage 1, 3 standup-bank hits."""
        self._stage(code, obj, BANK_TARGETS, 3, ("lite303", "lite309", "lite315"), 148, 0x19)

    def _m_maelstrom_2(self: Game, code: int, obj: object) -> None:
        """FUN_010111d3: 3 drop-target hits."""
        self._stage(code, obj, DROP_TARGETS, 3, ("lite306", "lite308", "lite310", "lite313", "lite319"), 149, 0x1A)

    def _m_maelstrom_3(self: Game, code: int, obj: object) -> None:
        """FUN_010113a1: 5 lane passes."""
        lights = ("lite301", "lite302", "lite307", "lite316", "lite320", "lite321")
        self._stage(code, obj, LANE_ROLLOVERS, 5, lights, 150, 0x1B)

    def _single(self: Game, code: int, obj: object, members: tuple[str, ...], light: str, text: int,
                next_state: int, on_enter=None, on_done=None) -> None:
        if code == 0x3F:
            if _name(obj) in members:
                self.msg(light, 0x14)
                self.set_data("lite198", next_state)
                self._mission(0x42, None)
                if on_done is not None:
                    on_done()
            return
        if code == 0x42:
            if on_enter is not None:
                on_enter()
            self.msg(light, 7)
        elif code != 0x43:
            return
        self._mission_text(text)

    def _m_maelstrom_4(self: Game, code: int, obj: object) -> None:
        """FUN_01011582: the fuel chute (a_roll184)."""
        self._single(code, obj, ("a_roll184",), "lite318", 151, 0x1C,
                     on_enter=lambda: self.set_data("lite56", 0))

    def _m_maelstrom_5(self: Game, code: int, obj: object) -> None:
        """FUN_01011612: the launch ramp."""
        self._single(code, obj, ("ramp",), "lite317", 152, 0x1D)

    def _m_maelstrom_6(self: Game, code: int, obj: object) -> None:
        """FUN_01011699: the flags."""
        if code == 0x3F:
            if _name(obj) in FLAGS:
                for light in ("lite305", "lite312"):
                    self.msg(light, 0x14)
                self.set_data("lite198", 0x1E)
                self._mission(0x42, None)
                self.msg("lite20", 0x14)
                self.msg("lite19", 0x14)
            return
        if code == 0x42:
            self.msg("lite20", 0x13)
            self.msg("lite19", 0x13)
            self.msg("lite305", 7)
            self.msg("lite312", 7)
        elif code != 0x43:
            return
        self._mission_text(153)

    def _m_maelstrom_7(self: Game, code: int, obj: object) -> None:
        """FUN_01011798: a wormhole."""
        if code == 0x3F:
            if _name(obj) in ("v_sink1", "v_sink2", "v_sink3"):
                self.set_data("lite198", 0x1F)
                self._mission(0x42, None)
            return
        if code == 0x42:
            self._advance_wormhole(1)
            for sink in ("v_sink1", "v_sink2", "v_sink3"):
                self.msg(sink, 7)
        elif code != 0x43:
            return
        self._mission_text(154)

    def _m_maelstrom_8(self: Game, code: int, obj: object) -> None:
        """FUN_0101184c: the hyperspace chute ends the Maelstrom (5,000,000,
        rank +18)."""
        if code == 0x3F:
            if _name(obj) == "a_kout2":
                self.msg("lite304", 0x14)
                self.msg("lite130", 0x14)
                self.set_data("lite198", 1)
                self._mission(0x42, None)
                added = self.award(5000000)
                self.text("info", 48, 4.0)
                if self._rank_progress(0x12) == 0:
                    self._mission_text(78, added, seconds=8.0)
                    self.play("soundwave9")
            return
        if code == 0x42:
            self.msg("lite130", 0x13)
            self.msg("lite304", 7)
        elif code != 0x43:
            return
        self._mission_text(155)

    def _m_game_over(self: Game, code: int, obj: object) -> None:
        """FUN_01011985 (state 0x20, entered after the last ball): goal
        lights off, game-over mode (FUN_0101461a(2)), both flippers dropped
        (0x3fe). Then every 0x43 -- the first from FUN_0101748b, the rest
        from the mission box's own messages ending -- shows the next of: the
        title "3D Pinball / Space Cadet" (10 s), each player's score (3 s,
        stopping at a box of -1), each high score above 0 (3 s), round and
        round. The mission box's data holds the place: 0x100 | player,
        0x200 | rank, 0 = title next."""
        box = self.mission_box
        if code == 0x42:
            self.msg("goal_lights", 0x14)
            self.set_mode(2)
            self.flipper_message(0x3FE)
            box.data = 0
            return
        if code != 0x43:
            return
        place = box.data
        if place & 0x100 == 0 and place & 0x200 == 0:
            box.data = 0x100
            self.text("mission", 172, 10.0)
            return
        if place & 0x100:
            player = place & 0xF
            score = self.boxes[player] if player < 4 else -1
            if score >= 0:
                self.text("mission", 180 + player, 3.0, score)
                nxt = player + 1
                box.data = 0x200 if nxt == self.player_count else nxt | 0x100
                return
            box.data = 0x200
            place = player + 1
        rank = place & 0xF
        score = self.high_scores.score(rank) if rank < 5 else 0
        if score < 1:
            box.data = 0x100
            self.text("mission", 172, 10.0)
            return
        self.text("mission", 184 + rank, 3.0, score)
        box.data = 0 if rank + 1 == 5 else (rank + 1) | 0x200
