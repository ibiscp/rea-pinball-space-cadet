# Space Cadet Pinball (Python recreation)

A from-scratch Python/pygame recreation of **3D Pinball for Windows** ("Space
Cadet"), the Microsoft/Cinematronics pinball game bundled with Windows 95
Plus! and later Windows 98/Me/XP. Built by reverse engineering the original
`Pinball.exe` and its `PINBALL.DAT` table-data file with
[REA](https://github.com/morluto/rea) (`rea-agents`) driving Ghidra.

The game is self-contained: everything it needs from the original game is
ported into standard formats under `src/space_cadet_pinball/data/` and ships
with the package, so the original game is **not** needed to play. That folder
holds the table data (`PINBALL.DAT` as a JSON manifest, indexed PNGs for every
bitmap and `.npy` depth maps; `partout.load_ported` rebuilds it byte-exact),
the text-box font and the splash bitmap from `Pinball.exe`, and the WAVs and
`PINBALL.MID` theme the table uses. The original art, sounds and table data
are Microsoft's copyrighted content, so keep this repository private.
`Pinball.exe` itself and the `.7z` are never committed.

## Running it

```bash
uv run python -m space_cadet_pinball
```

Nothing else is needed. To regenerate `data/` from an original copy (a
folder with `PINBALL.DAT`, `Pinball.exe`, the WAVs and `PINBALL.MID`, or the
`.7z`), run the dev-only converter; it rebuilds everything through the
game's own loaders and checks it byte-for-byte against the originals:

```bash
uv run python tools/convert_original.py path/to/original
```

As in the original, the game draws a 600×416 screen with the menu bar above
it. Unlike the original (1×, not resizable), the window opens 1.5× bigger
(shrunk to fit the desktop) and can be resized; the image is scaled and
mouse clicks are mapped back (`WINDOW_SCALE` in `app.py`). Full screen is
the original's: the screen unscaled and centred on black, switching the
display to 640×480 first when the "Change Display" option is on (the
default).

This sandbox has no display server, so the game was built and verified
headlessly (`SDL_VIDEODRIVER=dummy`): unit tests on the physics engine, plus
scripted play-throughs that drive the real plunger/flippers/bumpers and
check score, drain and tilt all behave. **Run it on a machine with a screen
to actually play** — `uv run python -m space_cadet_pinball`.

**Controls** (the default key bindings are the original executable's own
key-binding strings and can be changed in Options > Player Controls... /
F8, the original's KEYMAPPER dialog; the other keys and the menu come from
its window procedure and its MENU_1 resource):

| Key     | Action                 |
| ------- | ---------------------- |
| `Z`     | Left flipper           |
| `/`     | Right flipper          |
| `Space` | Plunger (hold/release) |
| `X`     | Nudge left             |
| `.`     | Nudge right            |
| `↑`     | Nudge up/bottom        |
| `F2`    | New game               |
| `F3`    | Pause / resume         |
| `F4`    | Full screen            |
| `F8`    | Player Controls (key bindings) |
| `Esc`   | Minimize (leaves full screen first), as in the original |
| `D`     | Toggle collision-geometry debug overlay (off by default; not in the original) |

The menu bar has the original's Game / Options / Help menus: New Game,
Launch Ball, Pause/Resume, High Scores..., Demo, Exit; Full Screen, Select
Players (1-4), Sounds, Music, Player Controls...; About. Select Table isn't
there: the original deletes it when the Plus! table shell isn't installed
(its "Shell Exe" registry value is empty). Help Topics is greyed out (it
opens pinball.chm in Windows' help viewer). Close the window to quit. The
original's command-line switches work too: `-demo` starts in demo mode,
`-quick` skips the startup wait (and, as in the original, never opens the
MIDI device, so there's no music), `-fullscreen` starts in full screen.

High scores and the options are saved on exit to `pinball_settings.ini` in
the project root (git-ignored), with the value names and the checksum the
original keeps in the registry. The typed codes work while no mission is
running: `1max`, `bmax`, `gmax`, `rmax`, `hidden test` (then `B`, `H`, `R`,
dragging the ball with the mouse, and the window keys `Y` = frames/sec in
the title, `H` = a frame-time strip with `Y` on, `F1` = one 10 ms tick, `F15`
= pause without messages).

Nudging builds up tilt heat (+4.0/sec while a nudge is in, -1.0/sec
otherwise) exactly as the original does; crossing 1.0 triggers **TILT**
(flippers disabled until the ball drains). A nudge is in from its key-down
until its key-up or a 0.4 s timer the three nudges share (a second nudge
cancels the first one's timer, so the first stays in until its key-up).

The original theme (`PINBALL.MID`) plays on startup. MIDI playback goes
through SDL_mixer's software synth, which is built into Windows/macOS but on
Linux needs `timidity` configured with a soundfont (`sudo apt install
timidity fluid-soundfont-gm` works); without it the game just runs silently
without music rather than failing.

## Reverse-engineering methodology

The original `Pinball.exe` (PE32, x86) and its `PARTOUT(4.0)RESOURCE` data
files (`PINBALL.DAT`, `FONT.DAT`) were analyzed with REA's Ghidra provider.
This sandbox is arm64 Linux, which has no official prebuilt Ghidra
decompiler binary, so the native `decompile` binary was **compiled from the
Ghidra distribution's own bundled C++ source** for arm64
(`Ghidra/Features/Decompiler/src/decompile/cpp`, `make ARCH_TYPE=
OSDIR=linux_arm_64 ghidra_opt`) rather than emulated — REA explicitly refuses
to run a decompiler whose ELF architecture doesn't match the host, so this
had to be a genuine native build.

**Confirmed by decompiling the resource loader** (`FUN_010064e2`) and its
generic field accessors (`FUN_010063db` → `FUN_01006369`/`FUN_01006270`):
the on-disk tagged property-bag format `partout.py` implements, which
parses both the real `PINBALL.DAT` (928,700 bytes, 541 entries) and
`FONT.DAT` byte-for-byte with nothing left over.

**Confirmed by decompiling `FUN_01015424`** (the table's load routine) and
tracing it to `CreatePalette`/`RealizePalette`: the table's shared 256-color
palette is itself just another field in `PINBALL.DAT` (on the `background`
entry). `FUN_010043b9` builds the screen palette from it: the records are
Windows RGBQUADs (blue, green, red), only entries 10–245 come from the
file, and the other 20 are system colors (black on a true-color display,
with entry 255 forced to white). The render buffer is a `DIB_PAL_COLORS`
bitmap (`FUN_01004520` → `FUN_01004154`), so pixels show exactly those
colors. Earlier versions of this port read the records as red, green, blue,
which swapped red and blue everywhere (brown table instead of the real dark
blue one) — see `resources.screen_palette`.

**Confirmed by cross-checking sprite placement**: every bumper, flipper,
target, rollover, light, and the plunger carries its *own* embedded sprite
bitmap in `PINBALL.DAT`, and that bitmap's `origin_x`/`origin_y` is its real
on-table pixel position (not a sprite-sheet crop coordinate, as first
assumed) — confirmed because it places things sensibly: the two flipper
sprites end up symmetric about the table's horizontal center right at the
bottom edge, and the plunger ends up in the bottom-right corner, exactly
where they belong. `table_data.py` builds the playable table directly from
these positions, plus the table's outer wall shape, which is *traced*
straight out of the real background art's silhouette rather than guessed.

**Confirmed by decompiling the type-12 field's accessor** (`FUN_0100950a`):
each object's type-12 variant — including the `table` entry's own
345,934-byte one, previously assumed to be a wall/polygon list — is actually
**a per-pixel collision field at that object's own sprite resolution**, not
vector geometry. The original engine's real-time consumer of that field
(presumably sampling it directly each physics tick) lives behind the same
undecompiled vtable as the simulation tick itself, so the field's exact
value formula wasn't recovered — but its *gradient* reliably traces every
real wall (lane guides, the hyperspace tube rail, the gravity-well ring,
bumper banks), confirmed by rendering the extracted edges and visually
matching the real table. `wall_field.py` implements this gradient-edge
extraction from the `table` entry's field and feeds it straight into the
physics world as line segments, on top of the traced outer silhouette.

**A second, deeper RE pass found the live physics tick.** The earlier
belief that it was unreachable (behind an undecompiled vtable) turned out
to be wrong — two of its three "undecompiled" methods simply had no
Ghidra-recognized function boundary (recovered instead via raw x86
disassembly with `capstone`), and the real per-frame driver
(`FUN_01014bf9` → `FUN_01014a68` → `FUN_01014956`) was reachable once that
was worked around. Confirmed from decompiled code: the original integrates
with the **real elapsed frame time** (clamped to 100ms/step), not a fixed
60Hz loop; acceleration is `gravity − friction·velocity` plus a small
random x-axis jitter every tick (gravity tag `0x131`, friction tag `0x2bd`
on the `table` entry — correcting an earlier guess that tag `700` was
gravity: that tag is actually an unrelated 2-float point); and collision
runs through a uniform spatial grid where every registered object
contributes a force via a shared virtual method, rather than the ball
directly sampling the per-pixel field. Per-flipper tags (`0x320`-`0x325` on
`a_flip1`/`a_flip2`) were also found and read directly from the real file —
the flipper's collision shape is almost certainly three circles along its
length (not the single capsule this engine still uses), and two of the
tags are a clean 2:1 ratio read as the powered-stroke vs. passive-return
swing duration — **this asymmetry is now ported** (`Flipper.
return_angular_speed`, defaulting to half `angular_speed`), as is the
acceleration jitter (`constants.BALL_JITTER_ACCEL`). **Still not
recovered**: the resource-unit-to-pixel scale factor (two independent
cross-checks gave inconsistent answers, so it's deliberately not reported
as a conversion factor rather than guessed), which blocks porting the
gravity/friction *magnitudes* and the flipper/bumper/target/gate/kicker's
exact local collision shapes as precise numbers. The plunger lane's
geometry is also still hand-calibrated (its background art doesn't show up
in either the silhouette trace or the type-12 field, for reasons not
pinned down — see `table_data.py`). Individual objects' own type-12
collision fields (bumpers, targets, etc.) follow the identical per-pixel
format but aren't decoded per-object yet — those still use a circle
approximation sized from each sprite's bounding box.

**A third pass corrected the wall-geometry picture above and fully
decompiled the nudge/tilt input path.** Decompiling the rest of the world
constructor (`FUN_0101a5ab`) shows the original builds real line-segment
objects from a polyline at load time, each registering itself into the
same spatial grid a ball uses — i.e. wall collision is genuinely hard,
swept geometric contact, structurally the same approach this port's own
`Segment` class already takes, **not** a per-tick force sampled from the
type-12 field as the second pass proposed. (The polyline's own ultimate
source — plausibly a one-time contour extraction over that same field,
but not confirmed — remains open; `wall_field.py`'s gradient-edge
extraction is still the practical stand-in, now understood to be
approximating a real load-time vectorization step rather than a fictional
runtime field sampler.) Separately, tracing the bump-key handlers forward
(`FUN_01015072`/`FUN_010152e4` → `FUN_01014dcf`/`FUN_01014bf9`) fully
recovered the **exact** tilt and nudge mechanics, now ported byte-for-byte
in spirit: tilt is a continuous heat value that rises at +4.0/sec while a
nudge is "active", decays at -1.0/sec otherwise, warns above 0.5 and tilts
above 1.0 (`constants.TILT_HEAT_*`, `app._update_tilt_heat`, replacing the
old discrete nudge-counter) — these are plain per-second rates with no
unit-scale ambiguity, so they're exact rather than approximated. Nudges
themselves turned out to be brief, self-cancelling impulses (kicked on
key-down, undone on key-up or after a fixed 0.4s, whichever comes first),
with confirmed exact directional ratios — left/right/bottom are
(+1,+0.5)/(-1,+0.5)/(0,+0.5), i.e. every nudge has the same downward
y-kick and the side bumps' x-kick is exactly twice that (`constants.
NUDGE_X_RATIO_*`/`NUDGE_Y_RATIO`/`NUDGE_AUTO_CANCEL_SECONDS`,
`app._nudge`/`_cancel_nudge`); only the absolute impulse magnitude
(`NUDGE_IMPULSE`) is still approximated, same unresolved unit-scale issue
as gravity/friction.

**A fifth pass found and ported the real wall-collision response formula.**
Tracing the hit-dispatch chain all the way through (grid query → the hit
object's own vtable → forwards to the *world* object's own vtable slot 5,
a sibling of the already-confirmed gravity/drag slot) landed on
`FUN_01017883`, the actual bounce math. The original does **not** bounce a
wall hit with one shared restitution scalar the way this port used to —
it decomposes velocity into normal and tangential parts and scales each
**independently**: the reflected normal component by a restitution
coefficient, the preserved tangential component by a separate retention
coefficient. Both are confirmed exact for ordinary walls, straight from
the engine's own hardcoded defaults (`FUN_01008fe0`) — **0.6** normal
restitution, **0.95** tangential retention — and, like the tilt/nudge
rates, these are dimensionless ratios with no unit-scale ambiguity, so
they're the real numbers, not tuned guesses. `constants.WALL_RESTITUTION`
is now `0.6` (was a guessed `0.55`) and a new `constants.
WALL_TANGENT_RETENTION = 0.95` feeds `geometry.Segment.tangent_retention`
and the rewritten `World._collide_segments`. Also found, but not yet
decoded: bumpers/flippers/targets/gates/kickers each construct through
this same shared mechanism but with their *own* PINBALL.DAT entry, meaning
each one almost certainly has its own real collision coefficients rather
than sharing the wall's — a well-scoped lead for a future pass.

**A sixth pass decoded those per-object coefficients, plus the game's real
sound-ID resolution mechanism.** Flippers really do bounce the ball with
their own, livelier coefficients (**0.75** restitution, **0.5** tangential
retention, vs. the wall's 0.6/0.95) — confirmed exact and now used in
`World._collide_flippers`. Bumpers and targets turned out to use the
*same* 0.6/0.95 wall defaults for their passive bounce rather than a
bespoke bouncy value — this port's bumper `Circle` previously hardcoded a
wrong `1.0`, now fixed. Separately, every "sound reference" tag anywhere in
the file (e.g. which sound a bumper or the plunger plays) turned out to be
a *PINBALL.DAT entry index*, not a final sound ID — it has to be resolved
through the game's own sound-registration-slot mechanism
(`FUN_0100901f`) to get the number the engine actually plays. Replicating
that resolver and cross-checking the results against real shipped
`SOUND*.WAV` filenames confirmed five of this port's previously-invented
`sound_id=` placeholders (bumper hit, kicker eject, plunger launch, tilt
warning, tilt trigger) and replaced them with the real values. Also
investigated and *deliberately not changed*: this port's `Kicker` entity is
built from `a_kick1`/`a_kick2` sprites, but full decompilation shows those
are a structurally different, simpler object than `v_sink1/2/3/7` (the
*real* capture-and-relaunch-after-delay mechanism, plausibly the hyperspace
tube/gravity well) — porting the sink's already-decoded exit data onto the
kicker objects would have quietly mixed up two different real features, so
nothing was changed there; the real sink data is documented for whenever a
correctly-scoped entity is added for it. See `PHYSICS_SPEC_2.md`/
`PHYSICS_SPEC_3.md`/`PHYSICS_SPEC_5.md`/`PHYSICS_SPEC_6.md` (kept
alongside the RE evidence files outside this repo, not committed — see
below) for the full writeups with function addresses, and each module's
docstring (`resources.py`, `table_data.py`, `wall_field.py`, `geometry.py`,
`flipper.py`, `world.py`, `constants.py`, `app.py`) for exactly which
numbers here are RE-confirmed versus approximated, and why.

**The eleventh pass found the camera, which supersedes several notes
above.** There never was a single "resource-unit-to-pixel scale factor":
the original simulates in its own world units on the flat table plane and
only converts when drawing, through one perspective projection. Its
parameters are data — the `camera_info` entry's 3x4 matrix and focal term,
re-centred on the `table` entry's tag-700 point (`FUN_01015424`,
`FUN_01008e4b`, `FUN_01008eba`, `FUN_01008f03`) — and every sprite is drawn
relative to the table bitmap's own origin. That's why per-object scale
checks never agreed (roughly 13 px/unit at the top of the table, 21 at the
bottom). Cross-checks: the flippers' tagged pivot/tip circles project
exactly onto their sprites' corners, bumper centres onto their sprites,
and the `table` entry's world rectangle onto the playfield's inner edge.
The physics now runs in those world units (`projection.py`), which made
the long-blocked magnitudes exact: gravity 25·sin(0.5) ≈ 11.99 units/s²,
linear friction 0.2/s with a speed-proportional x jitter, ball radius 0.3,
speed cap radius·200 = 60 units/s, the flippers' real pivot/tip circles and
69.6° swing in 0.04s up / 0.08s down, the bumpers' real circles and
threshold-gated kicks, the table's real outer walls (with their own
threshold-5 / 15-boost kick), the drain line, and the nudge impulses
(±1, 0.5) units/s. The full bounce routine (`FUN_01017883`) turned out to
work on direction and speed separately, now ported as `world.bounce`. Two
more corrections: the type-12 "wall field" is the background's **z-buffer**
used to hide the ball behind raised art (it goes to
`render::create_sprite`/`set_background_zmap`), not collision data — its
depth edges remain this port's stand-in for the internal rails until their
real wall objects are decoded; and every object's point values sit in a
static control table in the executable (`0x1023ef0`), now transcribed in
`scoring.py`.

**The twelfth pass replaced every stand-in wall with the original's own
objects.** The `table_objects` manifest's types 0x3e8/0x3f2 (64 unnamed
entries plus the `v_rebo*` slingshots) are plain walls built by
`FUN_010191ba` → `FUN_010179a9` from their tag-600 shapes: one point plus a
radius makes a circle, two points a one-sided line, more a closed polygon.
Each wall takes its bounce from its tag-300 preset and its kick from its
tag-400 preset, and sits on a collision layer (tag 602). The z-buffer edges
are gone. The same pass ported, from their own constructors and collision
handlers:
- **One-way walls** (`s_onewy*`).
- **Outlane gates** (`v_gate*`): opened for each new ball, closed after their
  kickback fires.
- **Kickbacks** (`a_kick*`): a plate that kicks a ball resting on it 0.7 s
  after first contact. These are not capture holes, which ended pass 11's
  endless capture loop.
- **Solid targets** (`a_targ*`): a hit counts only above the impact
  threshold, and drop targets fall for 0.1 s.
- **Sinks** (`v_sink*`) and **kickout holes** (`a_kout*`): capture, attraction
  field, timed eject with the original's spread and speed jitter.
- **Plunger**: +1 kick unit per 0.025 s up to 100, released through the
  face's own kick and capped at 60 u/s, with the 0.96 s serve delay.
- **Flipper contact response** (`FUN_0101be06`): the leading face's kick
  scales with the contact radius and swing rate, times tag 803.

See `PHYSICS_SPEC_12.md` for addresses.

**Note on `table.bmp`:** the copy of the game used for this pass ships a
`table.bmp` that's actually a *labeled strategy-guide diagram* of the table
(bumpers/targets/lanes numbered 1–55 with a legend) — not original game art.
It turned out not to matter: the real background/sprite art lives embedded
inside `PINBALL.DAT` itself (see above), so this file isn't used at all.

**Thirteenth pass (ramps, lights, missions, ball save, sounds).**
- The ramps are ported. They are triangle meshes on their own collision layer, built from
  trip lines that switch the ball's layer, height and gravity. The ramp hole then drops the
  ball back onto the table. With this the upper deck (bumpers 5–7) can be played.
- The original's whole control layer is ported from the decompiled code:
  - lights, light groups and the fuel bargraph, with their real messages, timers and blinking
    (`logic.py`);
  - the score object (field multiplier, jackpot and bonus);
  - all 57 control-table handlers (`game.py`);
  - the 33-state mission machine with ranks (`missions.py`).
- The Re-Deploy ball save works as in the original. It stays lit for 5 s after the ball
  enters play, then flashes for 5 s.
- Sounds now play the WAV files the data names. Earlier passes used registration-slot numbers
  as file names, which played the wrong files or nothing.
- Text messages come from the executable's string table (`strings.py`).
- Details and addresses are in `PHYSICS_SPEC_13.md`.

**Fourteenth pass (rendering and animations).** The original's renderer is ported in
`render.py`:
- **Window:** a 600×416 buffer sized from `table_size`. The table bitmap sits at the left,
  so its bottom rows below 416 are cut off as in the original. The right-hand info panel is
  the `background` bitmap at its own origin (386, 12); earlier passes took it for a splash
  screen.
- **Score, ball and player boxes:** drawn at the `score1` / `ballcount1` / `player_number1`
  rectangles with the `font1` digit glyphs from PINBALL.DAT. `Pinball.exe` never opens
  FONT.DAT.
- **Text boxes:** at their tag-1500 rectangles, word-wrapped in the PBMSG_FT bitmap font from
  `Pinball.exe` (ported to `data/pbmsg_ft.png` + `.json`). Without it, the original's own
  fallback is used: plain white text.
- **Sprites:** composited through the original's z-buffer, each with its own depth map. Each
  object's sprite follows its handler's draw calls: light frames and blinking, bumper lit
  frames (also on a level change), flag spin frames, drop and standup targets, rollovers
  (hidden while the ball is on them; `a_roll9` lights up instead), slingshot flashes, gates,
  the centre post, kickback frames, plunger pull frames, and the flippers' own timer-driven
  frames.
- **Ball:** drawn with the real sprite sized by its distance from the camera, and hidden
  behind raised art and inside the hidden tunnel by the depth test.
- **Nudge:** shifts the table image by the original's 2×1 px.

Addresses for each effect are in `PHYSICS_SPEC_14.md`.

**Fifteenth pass (game flow).** The rest of the score object and the window
code are ported:
- **Text boxes:** the original's message queue (FUN_010144b7): messages wait
  their turn, a repeated message refreshes its time, an endless one is
  replaced by the next, stale ones are skipped, each shows at least 0.25 s.
- **New game, balls, players:** F2 / the menu reset everything, play the
  start sound (the table's tag 1100) while every light sparkles, then serve.
  With 2-4 players a lost ball passes to the next player, who gets back their
  score, balls, extra balls and jackpot; every light, light group, bumper,
  standup target and sink keeps its own state per player, as in the original.
  "Player N" / "Player N Shoot Again" come from the string table.
- **Game over:** "Game Over" with the table's tag-1101 sound; three seconds
  later the high-score entry for each player that made the table, then the
  mission box cycles the title, the players' scores and the high scores.
  "HIGH SCORE" and every light flashing mark a new high score.
- **High scores:** the original's 5-entry table, rank and insert rules,
  number format and registry checksum.
- **Pause, focus, menus:** the table doesn't tick while paused, while the
  window is in the background or while a menu or dialog is open, as in the
  original's message loop. Pausing stops the music; resuming restarts it.
- **Tilt:** both boxes cleared, every light dimmed until the tilt lifts, and
  the ball forced down the drain if still tilted after 30 s.
- **Demo mode:** the original's demo object, which flips and launches through
  its five sensor lines and restarts 5 s after its game ends.
- **Typed codes:** the original's cheat-code state machine.

Addresses are in `PHYSICS_SPEC_15.md`.

**Sixteenth pass (coverage map + leftovers).** Every function in
`Pinball.exe` (649 found by Ghidra plus 17 it has no boundary for) and every
PINBALL.DAT entry is now classified as ported / not needed (C runtime,
Win32 plumbing, WaveMix, memory helpers...) / unresolved, with the reason --
see `COVERAGE.md` / `COVERAGE.csv` / `COVERAGE_DAT.csv` next to the specs.
Ported in this pass:
- **Time-of-impact physics** (FUN_01014a68 / FUN_01014956): the velocity
  is updated once per tick, then the ball's centre moves along a ray to the
  nearest one-sided line (walls moved one ball radius out), corner circle,
  circle or trip line, up to 10 hits a tick; the table's outer walls aren't
  offset. The flippers are still this port's own (turned in 4 slices a
  tick, overlaps resolved).
- **The main loop** ticks with the real elapsed milliseconds (no frame cap),
  and the timer pool is the original's: 150 timers, whole ms, at most two
  due timers a tick plus any 100 ms late.
- **Sounds:** 8 channels ("Voices"); a new sound takes the channel that
  started longest ago. Sounds stop when the window is deactivated.
- **Startup:** the splash bitmap on a black desktop-sized window while the
  table loads, then 2 s in which input is thrown away before the first game.
- **Player Controls** dialog and key options; window size / full screen as
  above; the serve lifts a standing tilt and resets the nudge heat to -2.0.

Addresses are in `PHYSICS_SPEC_16.md`.

**Seventeenth pass (last unresolved functions).** The coverage map now has
no unresolved functions (447 ported, 219 not needed, 0 unresolved):
- **Flippers** are the original's flipper edge (FUN_0101c2ba,
  FUN_0101bf98, FUN_0101b1f7, FUN_0101b825, FUN_0101b5a8, FUN_0101b43a,
  FUN_0101be06): a swing is a function of the game time from the key
  message, and the time-of-impact loop asks the edge for a swept test over
  the ray's time window. At rest it is a plain nearest-hit test (or a push
  out of the shape); while moving, the shape is posed every few
  milliseconds through the window. As in the original, that moving test
  advances its inside-test point by step x direction and casts sub-rays of
  step x length, independent of the ball's speed, so a very fast ball can
  end a tick inside a swinging flipper and be pushed out on the next.
- **Spatial grid** (`grid.py`, FUN_0100b883 / FUN_0100be21 / FUN_0100b486):
  10 x 15 cells. The flipper's test keeps state, so it only runs when a
  ray's cell walk reaches the flipper's cells, as in the original; the
  ramps' field acts in every cell its box touches, not just inside the box.
- **Debug H strip:** on first use it loads WinMain's gradient palette for
  the whole screen, as the original does.

Addresses are in `PHYSICS_SPEC_17.md`.

## Project layout

```
src/space_cadet_pinball/
  vec2.py        2D vector math
  geometry.py    static collision shapes (segments, circles)
  flipper.py     the flipper edge: swing timing, swept test, collision handler
  grid.py        the original's 10 x 15 spatial grid
  ball.py        ball state
  entities.py    plunger, targets, rollovers, gates, kickbacks, sinks, kickout holes
  world.py       physics tick: integration + time-of-impact collision
  partout.py     the PARTOUT(4.0)RESOURCE format: parser, and the loader for its ported form
  pngio.py       8-bit indexed PNG reader/writer for the ported bitmaps
  resources.py   turns a parsed PINBALL.DAT into palette + positioned sprites
  projection.py  the original's world -> screen perspective camera
  wall_field.py  decodes the table's z-buffer (no longer used for collision)
  table_data.py  builds the real World + entities, in world units, from PINBALL.DAT
  scoring.py     per-object point values from the executable's control table
  logic.py       the original's timers, lights and light groups (message-driven)
  game.py        score object + every control-table handler (listener)
  missions.py    the mission state machine (FUN_01011bb5) and ranks
  demo.py        the demo (attract-mode) player
  highscores.py  the high-score table and the saved options
  menu.py        the window menu, the High Scores and Player Controls dialogs
  controls.py    key bindings: defaults, options, the Player Controls key list
  splash.py      the startup splash bitmap
  strings.py     in-game text from the executable's string table
  render.py      the original renderer: z-buffered sprites, ball, panel, digits, text boxes
  audio.py       original WAV sound effects / MIDI music playback
  assets.py      access to the ported game data in data/
  data/          the ported game data (table, font, splash, sounds)
tools/
  convert_original.py  regenerates data/ from an original copy (dev-only)
  app.py         pygame window, input, game loop, sprite state -> renderer
  constants.py   physics & gameplay constants (see docstring for RE provenance)
tests/           pytest unit tests: vector math, physics, control logic, renderer
```

## Development

```bash
uv run pytest        # unit tests (headless, no display/audio required)
uv run ruff check src tests tools
uv run python -m space_cadet_pinball   # play (needs a real display)
```
