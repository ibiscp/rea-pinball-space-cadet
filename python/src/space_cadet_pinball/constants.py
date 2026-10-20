"""Game-wide constants.

Units: since the 11th RE pass (PHYSICS_SPEC_11.md, kept with the other specs
outside this repo) the physics runs in the original's own **world units**
on the table plane, and only rendering converts to pixels, through the
original's real perspective camera (see projection.py). That pass found the
camera; every earlier pass's "unresolved resource-unit-to-pixel scale" was
really a perspective projection (roughly 13 px/unit at the top of the table,
21 px/unit at the bottom), which is why no single scale factor ever fitted.
World +x is screen-left, world +y is toward the drain.

Most values below are now the original's literal data rather than tuned
guesses. Each is labelled with its source; the PHYSICS_SPEC_2..11 files
hold the decompiled evidence. Anything still approximated says so.
"""

from __future__ import annotations

import math

# Table render size in "table pixels" -- the real `table_size` field read
# straight out of PINBALL.DAT (CONFIRMED: entry "table_size", type-10 point
# [600, 416]). Only used to size the fallback layout; physics is in world units.
TABLE_WIDTH = 600
TABLE_HEIGHT = 416

# --- Ball (CONFIRMED) ---
# "ball" entry tag 500, read by the ball constructor FUN_01019309 into
# ball+0x9a; also copied into ball+0x32, the ball's height above the table
# plane (so it is drawn at z = its own radius).
BALL_RADIUS = 0.3
# FUN_01015424: ball_speed_limit = ball radius * 200.0; FUN_01014956 clamps
# the ball's speed to it before every collision sub-step.
MAX_BALL_SPEED = BALL_RADIUS * 200.0

# --- Acceleration (CONFIRMED, FUN_0101a5ab + FUN_010173e7 + FUN_01014a68) ---
# Defaults used only when PINBALL.DAT lacks the tags; table_data.py reads the
# real ones. Gravity is built from the "table" entry's tag 305 triple
# (magnitude, a1, a2) as (cos(a2)*sin(a1)*m, sin(a2)*sin(a1)*m); the shipped
# triple is (25.0, 0.5, pi/2), i.e. 25*sin(0.5) ~= 11.99 units/s^2 toward the
# drain. Each tick: a = gravity - FRICTION * velocity, plus an x-only jitter
# of FRICTION * speed * U(-0.5, 0.5) (rand()/32767 in the original).
GRAVITY_TRIPLE = (25.0, 0.5, math.pi / 2)
FRICTION = 0.2  # "table" tag 701, default 0x3e4ccccd

# --- Collision response (CONFIRMED, FUN_01017883) ---
# The real bounce works on the ball's unit direction d and speed s:
#   p = -(n . d)                       (closing component, only if > 0)
#   d' = normalize(e_t * (d + p n) + e_n * p n)
#   s' = s - (1 - e_n) * p * s
#   if p * s >= threshold: v' = kick * n + s' d'   else v' = s' d'
# Generic collision objects default to e_n=0.6, e_t=0.95 and a dead
# threshold of 1e9 (FUN_010190b3 with no entry, FUN_01008fe0).
WALL_RESTITUTION = 0.6
WALL_TANGENT_RETENTION = 0.95
NO_KICK_THRESHOLD = 1.0e9
# The table's own outer walls (FUN_0101a5ab builds one line wall per pair of
# points in the "table" entry's tag-600 polyline) bounce through
# FUN_01017e85 with the table's threshold (tag 400 -> preset tag 401, 5.0 in
# the shipped file) and a literal 15.0 boost (0x41700000 at 0x101a73d). The
# boost is disabled while tilted.
TABLE_WALL_KICK = 15.0

# --- Flippers (CONFIRMED, FUN_0101c59d/FUN_0101c2ba, see flipper.py) ---
# Geometry, timing, kick factor and e_n / e_t (a_flip1/a_flip2 tag 300 ->
# preset 354: e_t=0.5, e_n=0.75) are all read from the data. These defaults
# only matter for the hand-authored fallback layout.
FLIPPER_REST_ANGLE_DEG = 32.0
FLIPPER_ACTIVE_ANGLE_DEG = -32.0
FLIPPER_LENGTH = 52.0

# --- Still approximated (no decoded source yet) ---
# Re-trigger lockout on bumpers' extra kick. The bumper's real kick
# threshold/strength are data (tag 400 presets, read in table_data.py); this
# lockout is a port safeguard, not original behavior.
BUMPER_COOLDOWN = 0.1

# Tilt: a continuous heat value, CONFIRMED exact from FUN_01014bf9.
TILT_HEAT_RISE_RATE = 4.0  # heat/sec while any nudge is in
TILT_HEAT_DECAY_RATE = 1.0  # heat/sec while no nudge is in
TILT_HEAT_WARN_THRESHOLD = 0.5
TILT_HEAT_TRIGGER_THRESHOLD = 1.0

# Nudge (CONFIRMED, FUN_01014dcf and its three callers): each bump key calls
# FUN_01014dcf(x, y), which adds (x, y) * 0.5 world units/s to every free
# ball's velocity and moves the table image, with (x, y) = (2, 1) for
# bump-left, (-2, 1) for bump-right and (0, 1) for bump-bottom; key-up or a
# shared 0.4 s timer calls it again with (-x, -y).
NUDGE_AUTO_CANCEL_SECONDS = 0.4
NUDGE_CALL_LEFT = (2.0, 1.0)
NUDGE_CALL_RIGHT = (-2.0, 1.0)
NUDGE_CALL_BOTTOM = (0.0, 1.0)

# Default key bindings, confirmed from the original Pinball.exe's embedded
# virtual-key-code option strings ("90 Left Flipper Key", "191 Right Flipper
# Key", "32 Plunger Key", "88 Bump Left Key", "190 Bump Right Key",
# "38 Bump Bottom Key" -- VK_Z, VK_OEM_2 '/', VK_SPACE, VK_X, VK_OEM_PERIOD
# '.', VK_UP) found via `rea search` over the shipped executable.
KEY_LEFT_FLIPPER = "z"
KEY_RIGHT_FLIPPER = "/"
KEY_PLUNGER = "space"
KEY_BUMP_LEFT = "x"
KEY_BUMP_RIGHT = "."
KEY_BUMP_BOTTOM = "up"
