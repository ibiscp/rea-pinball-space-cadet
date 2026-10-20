"""The original's window menu (Pinball.exe RT_MENU "MENU_1") and the modal
"High Scores" (RT_DIALOG "DLG_HIGHSCORES") and "Player Controls" ("KEYMAPPER")
dialogs, drawn with pygame since a pygame window has no native menu bar or
dialogs.

Options > Select Table (405) is deleted from the menu at startup when the
registry's "Shell Exe" value is empty (FUN_01005f69) -- always the case
here, since that value only exists alongside the Plus! table shell.

Item ids, captions, accelerator labels and the dialog's controls (5 rows of
Rank / Name / Score, a 31-character name field on the new entry's row, OK /
Cancel / Clear, "Clear High Scores?" / "Confirm") are the original's
resources. The look (colours, font, sizes) is not in the program's data:
it is the Windows UI of the day, approximated here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pygame

from .highscores import ENTRIES, NAME_LIMIT, HighScores, format_score
from .strings import STRINGS

MENU_HEIGHT = 20
FACE = (192, 192, 192)
SHADOW = (128, 128, 128)
HILITE = (0, 0, 128)
TEXT = (0, 0, 0)
GREY_TEXT = (128, 128, 128)

# Command ids (WM_COMMAND, FUN_01007a3e).
NEW_GAME, ABOUT, HIGH_SCORES, EXIT = 101, 102, 103, 105
SOUNDS, MUSIC, HELP_TOPICS = 201, 202, 301
LAUNCH_BALL, PAUSE, FULL_SCREEN, DEMO, SELECT_TABLE, PLAYER_CONTROLS = 401, 402, 403, 404, 405, 406
PLAYERS_1, PLAYERS_4 = 408, 411


@dataclass
class Item:
    command: int
    caption: str
    accel: str = ""
    submenu: list[Item] | None = None
    enabled: bool = True
    checked: bool = False

    @property
    def separator(self) -> bool:
        return self.command == 0 and self.submenu is None


def _sep() -> Item:
    return Item(0, "")


def build_menu() -> list[tuple[str, list[Item]]]:
    players = [Item(PLAYERS_1 + i, f"{i + 1} Player" + ("s" if i else "")) for i in range(4)]
    return [
        ("Game", [
            Item(NEW_GAME, "New Game", "F2"),
            Item(LAUNCH_BALL, "Launch Ball"),
            Item(PAUSE, "Pause/Resume Game", "F3"),
            _sep(),
            Item(HIGH_SCORES, "High Scores..."),
            Item(DEMO, "Demo"),
            Item(EXIT, "Exit"),
        ]),
        ("Options", [
            Item(FULL_SCREEN, "Full Screen", "F4"),
            Item(-1, "Select Players", submenu=players),
            _sep(),
            Item(SOUNDS, "Sounds"),
            Item(MUSIC, "Music"),
            _sep(),
            Item(PLAYER_CONTROLS, "Player Controls...", "F8"),
        ]),
        ("Help", [
            Item(HELP_TOPICS, "Help Topics", "F1", enabled=False),
            _sep(),
            Item(ABOUT, "About Pinball"),
        ]),
    ]


class MenuBar:
    def __init__(self, on_command: Callable[[int], None]) -> None:
        self.menus = build_menu()
        self.on_command = on_command
        self.font = pygame.font.Font(None, 18)
        self.open_index: int | None = None
        self.sub_open = False
        self._title_rects: list[pygame.Rect] = []
        self._item_rects: list[tuple[pygame.Rect, Item]] = []
        self._sub_rects: list[tuple[pygame.Rect, Item]] = []
        # Maps a window mouse position into the drawing surface (the window
        # shows that surface scaled; see App._to_screen).
        self.to_screen: Callable[[tuple[int, int]], tuple[int, int]] = lambda pos: pos

    @property
    def is_open(self) -> bool:
        return self.open_index is not None

    def item(self, command: int) -> Item | None:
        for _title, items in self.menus:
            for item in items:
                if item.command == command:
                    return item
                for sub in item.submenu or ():
                    if sub.command == command:
                        return sub
        return None

    def set(self, command: int, *, enabled: bool | None = None, checked: bool | None = None) -> None:
        """FUN_010056a9 (enable) / FUN_010056d3 (check)."""
        item = self.item(command)
        if item is None:
            return
        if enabled is not None:
            item.enabled = enabled
        if checked is not None:
            item.checked = checked

    def close(self) -> None:
        self.open_index = None
        self.sub_open = False

    # -- input --------------------------------------------------------------
    def click(self, pos: tuple[int, int]) -> bool:
        """Returns True when the click was the menu's."""
        for i, rect in enumerate(self._title_rects):
            if rect.collidepoint(pos):
                self.open_index = None if self.open_index == i else i
                self.sub_open = False
                return True
        if self.open_index is None:
            return False
        for rect, item in self._sub_rects + self._item_rects:
            if rect.collidepoint(pos):
                if item.submenu is not None:
                    self.sub_open = True
                    return True
                if item.separator or not item.enabled:
                    return True
                self.close()
                self.on_command(item.command)
                return True
        self.close()
        return True

    def hover(self, pos: tuple[int, int]) -> None:
        if self.open_index is None:
            return
        for i, rect in enumerate(self._title_rects):
            if rect.collidepoint(pos) and i != self.open_index:
                self.open_index = i
                self.sub_open = False
        for rect, item in self._item_rects:
            if rect.collidepoint(pos):
                self.sub_open = item.submenu is not None

    # -- drawing -------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        width = surface.get_width()
        pygame.draw.rect(surface, FACE, (0, 0, width, MENU_HEIGHT))
        self._title_rects = []
        x = 6
        for i, (title, _items) in enumerate(self.menus):
            label = self.font.render(title, True, TEXT)
            rect = pygame.Rect(x - 4, 1, label.get_width() + 8, MENU_HEIGHT - 2)
            if i == self.open_index:
                pygame.draw.rect(surface, HILITE, rect)
                label = self.font.render(title, True, (255, 255, 255))
            surface.blit(label, (x, (MENU_HEIGHT - label.get_height()) // 2))
            self._title_rects.append(rect)
            x += label.get_width() + 14
        self._item_rects = []
        self._sub_rects = []
        if self.open_index is None:
            return
        anchor = self._title_rects[self.open_index]
        _title, items = self.menus[self.open_index]
        box = self._draw_list(surface, items, anchor.x, MENU_HEIGHT, self._item_rects)
        if self.sub_open:
            parent = next((r for r, it in self._item_rects if it.submenu is not None), None)
            sub = next((it for _r, it in self._item_rects if it.submenu is not None), None)
            if parent is not None and sub is not None:
                self._draw_list(surface, sub.submenu, box.right - 2, parent.y - 3, self._sub_rects)

    def _draw_list(self, surface, items: list[Item], x: int, y: int, rects: list) -> pygame.Rect:
        row = 18
        widths = [self.font.size(it.caption)[0] + (self.font.size(it.accel)[0] + 30 if it.accel else 0) for it in items]
        width = max(widths) + 50
        height = sum(6 if it.separator else row for it in items) + 6
        box = pygame.Rect(x, y, width, height)
        pygame.draw.rect(surface, FACE, box)
        pygame.draw.rect(surface, SHADOW, box, 1)
        mouse = self.to_screen(pygame.mouse.get_pos())
        cy = y + 3
        for item in items:
            if item.separator:
                pygame.draw.line(surface, SHADOW, (x + 3, cy + 3), (x + width - 4, cy + 3))
                cy += 6
                continue
            rect = pygame.Rect(x + 3, cy, width - 6, row)
            hot = rect.collidepoint(mouse) and item.enabled
            if hot:
                pygame.draw.rect(surface, HILITE, rect)
            colour = (255, 255, 255) if hot else (TEXT if item.enabled else GREY_TEXT)
            if item.checked:
                pygame.draw.lines(surface, colour, False, [(x + 7, cy + 9), (x + 10, cy + 12), (x + 15, cy + 5)], 2)
            surface.blit(self.font.render(item.caption, True, colour), (x + 20, cy + 3))
            if item.accel:
                accel = self.font.render(item.accel, True, colour)
                surface.blit(accel, (x + width - accel.get_width() - 14, cy + 3))
            if item.submenu is not None:
                surface.blit(self.font.render(">", True, colour), (x + width - 14, cy + 3))
            rects.append((rect, item))
            cy += row
        return box


@dataclass
class HighScoreDialog:
    """DLG_HIGHSCORES with FUN_010051b5: shows the table (FUN_01005159);
    for a new entry (FUN_01005452) the rows from `rank` move down one and
    the entry's row is an edit field holding "Player N", 31 characters at
    most. OK stores it (FUN_01004c8d); Cancel doesn't; Clear asks "Clear
    High Scores?" and empties the table (FUN_01004c3c), then -- for an
    entry -- the dialog opens again (FUN_01005452's loop)."""

    table: HighScores
    score: int | None = None  # None = just showing the table (Game > High Scores...)
    rank: int = -1
    name: str = ""
    confirming: bool = False
    done: bool = False
    _buttons: dict[str, pygame.Rect] = field(default_factory=dict)

    @property
    def entering(self) -> bool:
        return self.score is not None and self.rank >= 0

    def rows(self) -> list[tuple[str, str]]:
        rows = []
        inserted = 0
        for i in range(ENTRIES):
            if self.entering and self.rank == i:
                rows.append((self.name, format_score(self.score)))
                inserted = 1
            if i + inserted < ENTRIES:
                entry = self.table.entries[i]
                rows.append((entry.name, format_score(entry.score)))
        return rows[:ENTRIES]

    # -- input -----------------------------------------------------------------
    def key(self, event: pygame.event.Event) -> None:
        if self.confirming:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._clear_confirmed()
            elif event.key == pygame.K_ESCAPE:
                self.confirming = False
            return
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.ok()
        elif event.key == pygame.K_ESCAPE:
            self.done = True
        elif self.entering and event.key == pygame.K_BACKSPACE:
            self.name = self.name[:-1]
        elif self.entering and event.unicode and event.unicode.isprintable() and len(self.name) < NAME_LIMIT:
            self.name += event.unicode

    def click(self, pos: tuple[int, int]) -> None:
        for label, rect in self._buttons.items():
            if rect.collidepoint(pos):
                if label == "OK":
                    if self.confirming:
                        self._clear_confirmed()
                    else:
                        self.ok()
                elif label == "Cancel":
                    if self.confirming:
                        self.confirming = False
                    else:
                        self.done = True
                elif label == "Clear":
                    self.confirming = True
                return

    def ok(self) -> None:
        if self.entering:
            self.table.insert(self.score, self.name, self.rank)
        self.done = True

    def _clear_confirmed(self) -> None:
        self.confirming = False
        self.table.clear()
        if not self.entering:
            self.done = True

    # -- drawing -----------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        font = pygame.font.Font(None, 20)
        w, h = 420, 230
        x = (surface.get_width() - w) // 2
        y = (surface.get_height() - h) // 2
        pygame.draw.rect(surface, FACE, (x, y, w, h))
        pygame.draw.rect(surface, SHADOW, (x, y, w, h), 1)
        pygame.draw.rect(surface, HILITE, (x + 2, y + 2, w - 4, 20))
        surface.blit(font.render("High Scores", True, (255, 255, 255)), (x + 8, y + 5))
        top = y + 30
        surface.blit(font.render("Rank", True, TEXT), (x + 18, top))
        surface.blit(font.render("Name", True, TEXT), (x + 70, top))
        surface.blit(font.render("Score", True, TEXT), (x + 300, top))
        for i, (name, score) in enumerate(self.rows()):
            ry = top + 26 + i * 24
            surface.blit(font.render(str(i + 1), True, TEXT), (x + 26, ry))
            if self.entering and i == self.rank:
                pygame.draw.rect(surface, (255, 255, 255), (x + 66, ry - 3, 190, 20))
                pygame.draw.rect(surface, SHADOW, (x + 66, ry - 3, 190, 20), 1)
                surface.blit(font.render(name + "|", True, TEXT), (x + 70, ry))
            else:
                surface.blit(font.render(name, True, TEXT), (x + 70, ry))
            label = font.render(score, True, TEXT)
            surface.blit(label, (x + 390 - label.get_width(), ry))
        self._buttons = {}
        for j, label in enumerate(("OK", "Cancel", "Clear")):
            rect = pygame.Rect(x + 150 + j * 90, y + h - 34, 80, 24)
            pygame.draw.rect(surface, FACE, rect)
            pygame.draw.rect(surface, SHADOW, rect, 1)
            text = font.render(label, True, TEXT)
            surface.blit(text, (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))
            self._buttons[label] = rect
        if self.confirming:
            cw, ch = 220, 90
            cx, cy = (surface.get_width() - cw) // 2, (surface.get_height() - ch) // 2
            pygame.draw.rect(surface, FACE, (cx, cy, cw, ch))
            pygame.draw.rect(surface, SHADOW, (cx, cy, cw, ch), 1)
            pygame.draw.rect(surface, HILITE, (cx + 2, cy + 2, cw - 4, 20))
            surface.blit(font.render(STRINGS[41], True, (255, 255, 255)), (cx + 8, cy + 5))
            surface.blit(font.render(STRINGS[40], True, TEXT), (cx + 20, cy + 34))
            self._buttons = {}
            for j, label in enumerate(("OK", "Cancel")):
                rect = pygame.Rect(cx + 30 + j * 90, cy + ch - 30, 70, 22)
                pygame.draw.rect(surface, FACE, rect)
                pygame.draw.rect(surface, SHADOW, rect, 1)
                text = font.render(label, True, TEXT)
                surface.blit(text, (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))
                self._buttons[label] = rect


# DIALOG "KEYMAPPER" in dialog units (x, y, w, h); MS Sans Serif 8 makes a
# dialog unit 1.5 px wide and 1.625 px high (INFERRED: the font's metrics,
# not program data).
DLU_X, DLU_Y = 1.5, 1.625
KEYMAPPER_SIZE = (284, 183)
KEYMAPPER_STATICS = (
    ("Instructions", (7, 5, 269, 61), "group"),
    (
        ("To change game controls, choose the control options you want, click the Arrow buttons to change "
        "specific keys, and then choose OK."),
        (14, 17, 249, 18),
        "text",
    ),
    (
        ("To restore 3D Pinball to its original settings, choose Default, and then choose OK. To use the Arrow "
        "keys on the numeric keypad, make sure NUMLOCK is off."),
        (14, 38, 256, 25),
        "text",
    ),
    ("Control Options", (7, 71, 269, 87), "group"),
    ("Left Flipper", (20, 87, 39, 10), "text"),
    ("Right Flipper", (146, 87, 44, 10), "text"),
    ("Left Table Bump", (20, 107, 34, 17), "text"),
    ("Right Table Bump", (146, 107, 38, 19), "text"),
    ("BottomTable Bump", (20, 131, 41, 18), "text"),
    ("Plunger", (146, 136, 39, 8), "text"),
)
# Combo boxes 401..406, in the binding order (controls.LEFT_FLIPPER ...).
KEYMAPPER_COMBOS = (
    (66, 85, 53, 70),   # 401 left flipper
    (192, 85, 53, 70),  # 402 right flipper
    (192, 133, 53, 70),  # 403 plunger
    (66, 108, 53, 70),  # 404 left table bump
    (192, 108, 53, 70),  # 405 right table bump
    (66, 133, 53, 70),  # 406 bottom table bump
)
KEYMAPPER_BUTTONS = (("OK", (119, 163, 50, 14)), ("Cancel", (173, 163, 50, 14)), ("Default", (227, 163, 50, 14)))


@dataclass
class KeyMapperDialog:
    """DIALOG "KEYMAPPER" with FUN_01005850 (Options > Player Controls...,
    F8): six drop-down lists of the keys in controls.key_list(), each
    showing its current binding. OK refuses duplicate keys with "Warning:"
    / string 39 and stays open; otherwise it stores the six keys. Cancel
    keeps the old ones. Default selects the defaults (strings 159..164) in
    the lists without storing them. The keys are written to the options at
    exit (FUN_010055f3)."""

    keys: list[int]
    on_ok: Callable[[list[int]], None]
    done: bool = False
    warning: bool = False
    open_combo: int | None = None
    scroll: int = 0
    _choices: list[tuple[int, str]] = field(default_factory=list)
    _selected: list[int] = field(default_factory=list)
    _rects: dict[str, pygame.Rect] = field(default_factory=dict)
    _list_rects: list[tuple[pygame.Rect, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        from .controls import key_list

        self._choices = key_list()
        self._selected = [self._index_of(vk) for vk in self.keys]

    def _index_of(self, vk: int) -> int:
        """CB_SETCURSEL on the item with this VK; none selected (-1) if the
        key isn't in the list."""
        for i, (code, _name) in enumerate(self._choices):
            if code == vk:
                return i
        return -1

    # -- input -----------------------------------------------------------------
    def key(self, event: pygame.event.Event) -> None:
        if self.warning:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_SPACE):
                self.warning = False
            return
        if self.open_combo is not None:
            sel = self._selected[self.open_combo]
            if event.key == pygame.K_UP:
                self._selected[self.open_combo] = max(0, sel - 1)
            elif event.key == pygame.K_DOWN:
                self._selected[self.open_combo] = min(len(self._choices) - 1, sel + 1)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE):
                self.open_combo = None
            return
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.ok()
        elif event.key == pygame.K_ESCAPE:
            self.done = True

    def wheel(self, dy: int) -> None:
        if self.open_combo is not None:
            self.scroll = max(0, min(len(self._choices) - 7, self.scroll - dy))

    def click(self, pos: tuple[int, int]) -> None:
        if self.warning:
            rect = self._rects.get("warning_ok")
            if rect is not None and rect.collidepoint(pos):
                self.warning = False
            return
        if self.open_combo is not None:
            for rect, index in self._list_rects:
                if rect.collidepoint(pos):
                    self._selected[self.open_combo] = index
                    break
            self.open_combo = None
            return
        for name, rect in self._rects.items():
            if not rect.collidepoint(pos):
                continue
            if name.startswith("combo"):
                self.open_combo = int(name[5:])
                sel = max(0, self._selected[self.open_combo])
                self.scroll = max(0, min(len(self._choices) - 7, sel - 3))
            elif name == "OK":
                self.ok()
            elif name == "Cancel":
                self.done = True
            elif name == "Default":
                from .controls import DEFAULT_KEYS

                self._selected = [self._index_of(vk) for vk in DEFAULT_KEYS]
            return

    def ok(self) -> None:
        chosen = [self._choices[i][0] if i >= 0 else 0 for i in self._selected]
        if len(set(chosen)) < len(chosen):
            self.warning = True
            return
        self.on_ok(chosen)
        self.done = True

    # -- drawing -----------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        font = pygame.font.Font(None, 17)
        w, h = int(KEYMAPPER_SIZE[0] * DLU_X), int(KEYMAPPER_SIZE[1] * DLU_Y) + 20
        x0 = (surface.get_width() - w) // 2
        y0 = (surface.get_height() - h) // 2
        pygame.draw.rect(surface, FACE, (x0, y0, w, h))
        pygame.draw.rect(surface, SHADOW, (x0, y0, w, h), 1)
        pygame.draw.rect(surface, HILITE, (x0 + 2, y0 + 2, w - 4, 18))
        surface.blit(font.render("3D Pinball: Player Controls", True, (255, 255, 255)), (x0 + 6, y0 + 5))
        top = y0 + 20

        def rect(box: tuple[int, int, int, int]) -> pygame.Rect:
            bx, by, bw, bh = box
            return pygame.Rect(x0 + round(bx * DLU_X), top + round(by * DLU_Y), round(bw * DLU_X), round(bh * DLU_Y))

        for caption, box, kind in KEYMAPPER_STATICS:
            r = rect(box)
            if kind == "group":
                pygame.draw.rect(surface, SHADOW, r, 1)
                label = font.render(caption, True, TEXT)
                pygame.draw.rect(surface, FACE, (r.x + 6, r.y - 6, label.get_width() + 4, 12))
                surface.blit(label, (r.x + 8, r.y - 6))
            else:
                self._wrap(surface, font, caption, r)
        self._rects = {}
        for i, box in enumerate(KEYMAPPER_COMBOS):
            r = rect((box[0], box[1], box[2], 12))
            pygame.draw.rect(surface, (255, 255, 255), r)
            pygame.draw.rect(surface, SHADOW, r, 1)
            sel = self._selected[i]
            if sel >= 0:
                surface.blit(font.render(self._choices[sel][1], True, TEXT), (r.x + 3, r.y + 3))
            arrow = pygame.Rect(r.right - 16, r.y + 1, 15, r.height - 2)
            pygame.draw.rect(surface, FACE, arrow)
            pygame.draw.polygon(surface, TEXT, [(arrow.x + 4, arrow.y + 7), (arrow.x + 11, arrow.y + 7), (arrow.x + 7, arrow.y + 11)])
            self._rects[f"combo{i}"] = r
        for label, box in KEYMAPPER_BUTTONS:
            r = rect(box)
            pygame.draw.rect(surface, FACE, r)
            pygame.draw.rect(surface, SHADOW, r, 1)
            text = font.render(label, True, TEXT)
            surface.blit(text, (r.centerx - text.get_width() // 2, r.centery - text.get_height() // 2))
            self._rects[label] = r
        self._list_rects = []
        if self.open_combo is not None:
            anchor = self._rects[f"combo{self.open_combo}"]
            rows = min(7, len(self._choices))
            row_h = anchor.height
            box = pygame.Rect(anchor.x, anchor.bottom, anchor.width, rows * row_h + 2)
            pygame.draw.rect(surface, (255, 255, 255), box)
            pygame.draw.rect(surface, TEXT, box, 1)
            for k in range(rows):
                index = self.scroll + k
                if index >= len(self._choices):
                    break
                r = pygame.Rect(box.x + 1, box.y + 1 + k * row_h, box.width - 2, row_h)
                hot = index == self._selected[self.open_combo]
                if hot:
                    pygame.draw.rect(surface, HILITE, r)
                surface.blit(font.render(self._choices[index][1], True, (255, 255, 255) if hot else TEXT), (r.x + 2, r.y + 3))
                self._list_rects.append((r, index))
        if self.warning:
            self._draw_warning(surface, font)

    def _wrap(self, surface, font, text: str, r: pygame.Rect) -> None:
        words, line, y = text.split(), "", r.y
        for word in words:
            trial = f"{line} {word}".strip()
            if font.size(trial)[0] > r.width and line:
                surface.blit(font.render(line, True, TEXT), (r.x, y))
                y += font.get_linesize()
                line = word
            else:
                line = trial
        if line:
            surface.blit(font.render(line, True, TEXT), (r.x, y))

    def _draw_warning(self, surface, font) -> None:
        lines = STRINGS[39].split("\n")
        cw = max(font.size(t)[0] for t in lines) + 40
        ch = 30 + 18 * len(lines) + 40
        cx, cy = (surface.get_width() - cw) // 2, (surface.get_height() - ch) // 2
        pygame.draw.rect(surface, FACE, (cx, cy, cw, ch))
        pygame.draw.rect(surface, SHADOW, (cx, cy, cw, ch), 1)
        pygame.draw.rect(surface, HILITE, (cx + 2, cy + 2, cw - 4, 18))
        surface.blit(font.render(STRINGS[43], True, (255, 255, 255)), (cx + 6, cy + 5))
        for i, t in enumerate(lines):
            surface.blit(font.render(t, True, TEXT), (cx + 20, cy + 30 + 18 * i))
        r = pygame.Rect(cx + cw // 2 - 35, cy + ch - 30, 70, 22)
        pygame.draw.rect(surface, FACE, r)
        pygame.draw.rect(surface, SHADOW, r, 1)
        text = font.render("OK", True, TEXT)
        surface.blit(text, (r.centerx - text.get_width() // 2, r.centery - text.get_height() // 2))
        self._rects["warning_ok"] = r
