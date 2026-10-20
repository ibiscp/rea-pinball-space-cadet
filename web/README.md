# Space Cadet Pinball -- web version

A JavaScript port of the Python game in `python/src/space_cadet_pinball/`, built
into one self-contained page: `dist/space-cadet.html` (game code and all
data inline; works offline and over `file://`). The presentation in
`presentation/` embeds it on its last slide.

## Build

```bash
node web/build.mjs
```

No npm packages. The build reads the Python package's ported data
(`python/src/space_cadet_pinball/data/`: the table manifest, indexed PNGs, depth
`.npy`, the PBMSG_FT font, the splash, the WAVs) and `web/assets/pinball-theme.ogg`,
packs them into its own compact format (a JSON header and one binary blob:
bitmap palette indices, u16 depth maps, the font resource, PNG/WAV/OGG
bytes), gzips and base64s that into the page, and bundles the ES modules in
`web/src/` into one script. The page inflates the data with
`DecompressionStream` and rebuilds every table-data variant byte-exact, as
`partout.load_ported` does.

`pinball-theme.ogg` is `PINBALL.MID` rendered once, since browsers can't
play MIDI:

```bash
timidity -Ov --output-mono -s 22050 -o web/assets/pinball-theme.ogg python/src/space_cadet_pinball/data/sounds/PINBALL.MID
```

## Layout

`web/src/` mirrors the Python modules one to one (`world.js` = `world.py`,
`game.js` = `game.py`, ...), with the same names and structure so they can
be read side by side. The core is DOM-free; `shell.js` is the browser part
(canvas, keys, mouse, Web Audio, the iframe protocol). Extra modules:

- `pymath.js` -- numbers that behave exactly like Python's: fdlibm
  sin/cos/acos, CPython's `math.hypot`, `round()`, and CPython's
  `random` (MT19937, `random()` / `randrange()`), so a seeded run draws the
  same numbers.
- `rng.js` -- the one random stream (the Python port's `random` module).
- `data.js` / `partout.js` -- the bundle and the table data.

Differences from the Python version, all outside the game itself:

- Esc hands the keyboard back to the presentation instead of minimizing.
- Full screen (F4) fills the display with the scaled screen (a browser
  can't switch to the original's 640x480 mode).
- High scores and options live in `localStorage`.
- The debug "H" frame-time strip only switches the palette (the strip
  itself isn't drawn).
- The menu bar and dialogs are drawn with the browser's fonts (the Python
  port also approximates the Windows look).

## Tests

```bash
uv run --project python python web/test/trace_python.py   # traces the Python game (web/test/traces/)
node web/test/parity.mjs                 # replays the same runs in JS and compares
node web/test/page_smoke.mjs             # runs the built page's script under a DOM shim
node web/test/presentation_smoke.mjs     # the presentation's slides and iframe protocol
node web/test/render_png.mjs ramp_shot 900   # a JS frame as PNG (web/test/frames/)
```

`scenarios.json` (from `make_scenarios.mjs`) defines the runs: draining
without flippers, random flipping with a pause, ramp shots, a mission
accepted and completed, tilt, a full game to game over with a high-score
entry, and demo mode. Each tick both sides record the ball (position,
velocity, height, layer, held, alive), score, balls, mode, timer count,
tilt heat, every light's state, both text boxes, both flippers, the
plunger, the mission state and the player; every 30 ticks the composed
600x416 palette-index screen is hashed.

The Python trace routes `math.sin/cos/acos` through `web/test/fdlibm.py`
(the same fdlibm code as `pymath.js`), so the comparison doesn't depend on
the libm behind Python's `math` module, which differs from fdlibm in the
last bit for a few percent of inputs and differs between platforms (glibc
vs Apple); in a chaotic simulation one bit eventually changes the ball's
path. On this sandbox (glibc) the traces come out identical with or without
that routing. `math.hypot` is CPython's own algorithm on every platform, and
`pymath.hypot` reproduces it exactly. For the same reason the Python port
now writes its squares and square roots as `x * x` / `math.sqrt`, as the
original's own code does (e.g. the swept circle test `FUN_01008b34`),
instead of `** 2` / `** 0.5`, which go through the platform's `pow` (on
glibc it disagrees with `sqrt` / `x * x` for about 0.08% of inputs).
