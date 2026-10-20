"""Point values from the original's control table.

Pinball.exe keeps a static table at 0x1023ef0 (88 entries of 16 bytes:
object name, control handler, score count, score list). At load time
FUN_0100c01d links each named object to its handler (`object+0x12`, the
listener FUN_01011ec9 forwards hit messages to) and hands it the score list
through the object's vtable slot 3. The handlers then add one of those
scores when the object reports a hit (message 0x3f).

Which entry a handler picks depends on mission/light state. Only the
bumpers' choice is decoded: FUN_0100c4f5 uses the bumper's level
(`bumper+0x4e`), which the bumper constructor FUN_0101944a starts at 0, so
the first entry is the real base score. For the other objects this port
uses the first entry as an approximation of their (undecoded) selection
logic. The executable isn't shipped with the game data this port loads, so
the table is transcribed here.
"""

from __future__ import annotations

SCORES: dict[str, tuple[int, ...]] = {
    **{f"a_bump{i}": (500, 1000, 1500, 2000) for i in (1, 2, 3, 4)},
    **{f"a_bump{i}": (1500, 2500, 3500, 4500) for i in (5, 6, 7)},
    **{f"a_roll{i}": (2000,) for i in (1, 2, 3)},
    **{f"a_roll{i}": (500,) for i in (110, 111, 112)},
    **{f"a_roll{i}": (20000,) for i in (4, 8)},
    **{f"a_roll{i}": (5000, 25000) for i in (6, 7)},
    "a_roll5": (10000,),
    "a_roll9": (10000,),
    **{f"a_roll{i}": (500,) for i in range(179, 185)},
    **{f"v_rebo{i}": (500,) for i in (1, 2, 3, 4)},
    "ramp": (5000,),
    "s_onewy4": (15000, 30000, 75000, 30000, 15000, 7500),
    "a_flag1": (500, 2500),
    "a_flag2": (500, 2500),
    "a_kout1": (50000,),
    "a_kout2": (10000, 0, 20000, 50000, 150000),
    "a_kout3": (20000,),
    **{f"v_sink{i}": (2500, 5000, 7500) for i in (1, 2, 3)},
    **{f"a_targ{i}": (500, 5000) for i in (1, 2, 3)},
    **{f"a_targ{i}": (1500, 10000, 50000) for i in (4, 5, 6)},
    **{f"a_targ{i}": (500, 1500) for i in (7, 8, 9)},
    **{f"a_targ{i}": (750,) for i in (10, 11, 12)},
    **{f"a_targ{i}": (1000,) for i in (13, 14, 15)},
    **{f"a_targ{i}": (750,) for i in range(16, 23)},
}


def base_points(name: str) -> int:
    """The first entry of `name`'s score list, or 0 if the control table
    gives it no points (e.g. the outlane kickers)."""
    scores = SCORES.get(name)
    return scores[0] if scores else 0
