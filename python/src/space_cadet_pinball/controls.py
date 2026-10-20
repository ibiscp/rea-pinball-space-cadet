"""Player controls: the six key bindings and the Player Controls dialog's
key list.

- Defaults (FUN_01005f69): strings 159..164 ("90 Left Flipper Key", ...),
  each read with atoi (FUN_010037a6) -> Windows virtual-key codes Z, /,
  Space, X, ., Up.
- Options (FUN_01005f69 reads, FUN_010055f3 writes at exit): "Left Flippper
  key" (sic), "Right Flipper key", "Plunger key", "Left Table Bump key",
  "Right Table Bump key", "Bottom Table Bump key".
- The dialog's key list (FUN_01005850 on WM_INITDIALOG) is the u16 table at
  0x1023508: a value with bit 15 set starts a range (low byte .. next value),
  bit 14 marks a character key (the VK whose MapVirtualKey(vk, 2) is that
  character), anything else is one VK; 0xffff ends it. Names come from
  GetKeyNameTextA (FUN_0100580c, extended bit for VK 0x21..0x2e), character
  keys use the character itself.

Windows key names and the character -> VK mapping depend on the keyboard
layout, not on program data; the US-English layout is assumed (INFERRED).
"""

from __future__ import annotations

import pygame

from .strings import STRINGS

OPTION_NAMES = (
    "Left Flippper key",
    "Right Flipper key",
    "Plunger key",
    "Left Table Bump key",
    "Right Table Bump key",
    "Bottom Table Bump key",
)
LEFT_FLIPPER, RIGHT_FLIPPER, PLUNGER, BUMP_LEFT, BUMP_RIGHT, BUMP_BOTTOM = range(6)


def _atoi(text: str) -> int:
    digits = ""
    for ch in text.strip():
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits else 0


DEFAULT_KEYS = tuple(_atoi(STRINGS[159 + i]) for i in range(6))

# The key-list table at 0x1023508.
KEY_TABLE = (
    0x8041, 0x005A, 0x8030, 0x0039, 0x402E, 0x402F, 0x403B, 0x4027, 0x405B, 0x405D,
    0x0020, 0x000D, 0x0009, 0x0014, 0x0025, 0x0027, 0x0026, 0x0028, 0x002D, 0x002E,
    0x0024, 0x0023, 0x0021, 0x0022, 0x0090, 0x0091, 0x0013, 0xFFFF,
)

# US layout: character -> VK_OEM_* (MapVirtualKey(vk, 2)).
_CHAR_VK = {".": 0xBE, "/": 0xBF, ";": 0xBA, "'": 0xDE, "[": 0xDB, "]": 0xDD, ",": 0xBC, "-": 0xBD, "=": 0xBB, "`": 0xC0, "\\": 0xDC}
_VK_NAMES = {
    0x20: "Space", 0x0D: "Enter", 0x09: "Tab", 0x14: "Caps Lock", 0x25: "Left", 0x27: "Right",
    0x26: "Up", 0x28: "Down", 0x2D: "Insert", 0x2E: "Delete", 0x24: "Home", 0x23: "End",
    0x21: "Page Up", 0x22: "Page Down", 0x90: "Num Lock", 0x91: "Scroll Lock", 0x13: "Pause",
}


def key_list() -> list[tuple[int, str]]:
    """(VK, name) in the dialog's order."""
    out: list[tuple[int, str]] = []
    k = 0
    while KEY_TABLE[k] != 0xFFFF:
        value = KEY_TABLE[k]
        low = value & 0xFF
        if value & 0x4000:
            ch = chr(low)
            if ch in _CHAR_VK:
                out.append((_CHAR_VK[ch], ch))
        else:
            last = low
            if value & 0x8000:
                k += 1
                last = KEY_TABLE[k]
            for vk in range(low, last + 1):
                name = key_name(vk)
                if name:
                    out.append((vk, name))
        k += 1
    return out


def key_name(vk: int) -> str:
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk)
    for ch, code in _CHAR_VK.items():
        if code == vk:
            return ch
    return _VK_NAMES.get(vk, "")


_PYGAME_TO_VK = {
    pygame.K_SPACE: 0x20, pygame.K_RETURN: 0x0D, pygame.K_TAB: 0x09, pygame.K_CAPSLOCK: 0x14,
    pygame.K_LEFT: 0x25, pygame.K_RIGHT: 0x27, pygame.K_UP: 0x26, pygame.K_DOWN: 0x28,
    pygame.K_INSERT: 0x2D, pygame.K_DELETE: 0x2E, pygame.K_HOME: 0x24, pygame.K_END: 0x23,
    pygame.K_PAGEUP: 0x21, pygame.K_PAGEDOWN: 0x22, pygame.K_NUMLOCK: 0x90, pygame.K_SCROLLLOCK: 0x91,
    pygame.K_PAUSE: 0x13, pygame.K_BACKSPACE: 0x08, pygame.K_ESCAPE: 0x1B,
    pygame.K_LSHIFT: 0x10, pygame.K_RSHIFT: 0x10, pygame.K_LCTRL: 0x11, pygame.K_RCTRL: 0x11,
    pygame.K_PERIOD: 0xBE, pygame.K_SLASH: 0xBF, pygame.K_SEMICOLON: 0xBA, pygame.K_QUOTE: 0xDE,
    pygame.K_LEFTBRACKET: 0xDB, pygame.K_RIGHTBRACKET: 0xDD, pygame.K_COMMA: 0xBC, pygame.K_MINUS: 0xBD,
    pygame.K_EQUALS: 0xBB, pygame.K_BACKQUOTE: 0xC0, pygame.K_BACKSLASH: 0xDC,
    pygame.K_F1: 0x70, pygame.K_F2: 0x71, pygame.K_F3: 0x72, pygame.K_F4: 0x73, pygame.K_F8: 0x77,
    pygame.K_F11: 0x7A, pygame.K_F12: 0x7B, pygame.K_F15: 0x7E,
}
# With Num Lock off the keypad sends the navigation keys (the dialog's note).
_KEYPAD_NAV = {
    pygame.K_KP4: 0x25, pygame.K_KP6: 0x27, pygame.K_KP8: 0x26, pygame.K_KP2: 0x28, pygame.K_KP0: 0x2D,
    pygame.K_KP_PERIOD: 0x2E, pygame.K_KP7: 0x24, pygame.K_KP1: 0x23, pygame.K_KP9: 0x21, pygame.K_KP3: 0x22,
}

_KEYPAD_NUM = {
    pygame.K_KP0: 0x60, pygame.K_KP1: 0x61, pygame.K_KP2: 0x62, pygame.K_KP3: 0x63, pygame.K_KP4: 0x64,
    pygame.K_KP6: 0x66, pygame.K_KP7: 0x67, pygame.K_KP8: 0x68, pygame.K_KP9: 0x69, pygame.K_KP_PERIOD: 0x6E,
}


def vk_of(key: int, mods: int = 0) -> int:
    """The Windows virtual-key code a WM_KEYDOWN would carry for this
    pygame key (0 when there's none)."""
    if pygame.K_a <= key <= pygame.K_z:
        return key - pygame.K_a + 0x41
    if pygame.K_0 <= key <= pygame.K_9:
        return key - pygame.K_0 + 0x30
    if key in _KEYPAD_NAV:
        if mods & pygame.KMOD_NUM:
            return _KEYPAD_NUM[key]
        return _KEYPAD_NAV[key]
    if key == pygame.K_KP_ENTER:
        return 0x0D
    return _PYGAME_TO_VK.get(key, 0)
