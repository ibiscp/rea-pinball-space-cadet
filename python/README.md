# Space Cadet Pinball — Python version

The pygame recreation of 3D Pinball for Windows (Space Cadet). See the
[main README](../README.md) for the reverse-engineering notes, controls and
the web version.

Run every command from this folder:

```bash
uv run python -m space_cadet_pinball   # play (needs a real display)
uv run pytest                          # unit tests (headless)
uv run ruff check src tests tools
uv run python tools/convert_original.py path/to/original   # regenerate src/space_cadet_pinball/data/
```
