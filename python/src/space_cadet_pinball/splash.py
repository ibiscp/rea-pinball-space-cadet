"""The startup splash (WinMain FUN_0100833a -> FUN_01007308).

Before the main window is created, the original opens a borderless window
covering the whole desktop ("3DPB_SPLASH_CLASS"), paints it black
(BitBlt BLACKNESS) and draws the RT_BITMAP resource "splash_bitmap" from
Pinball.exe centred on it (FUN_01007264 / FUN_01007103). It stays up while
the main window loads the table, and is destroyed (FUN_010071a5 /
FUN_010071ed) right after the main window is shown. If the bitmap can't be
loaded there is no splash (FUN_01006fcb). The bitmap ships ported as
data/splash.png.
"""

from __future__ import annotations

import pygame

from .assets import SPLASH_PATH


def splash_image() -> pygame.Surface | None:
    if not SPLASH_PATH.exists():
        return None
    try:
        return pygame.image.load(str(SPLASH_PATH))
    except pygame.error:
        return None


def show_splash() -> bool:
    """Open the desktop-sized black splash with the bitmap centred; returns
    whether one is up."""
    image = splash_image()
    if image is None:
        return False
    desktop = pygame.display.Info()
    size = (max(1, desktop.current_w), max(1, desktop.current_h))
    try:
        screen = pygame.display.set_mode(size, pygame.NOFRAME)
    except pygame.error:
        return False
    screen.fill((0, 0, 0))
    screen.blit(image, ((size[0] - image.get_width()) // 2, (size[1] - image.get_height()) // 2))
    pygame.display.flip()
    pygame.event.pump()
    return True
