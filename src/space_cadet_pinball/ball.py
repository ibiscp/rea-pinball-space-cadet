from __future__ import annotations

from dataclasses import dataclass

from .vec2 import Vec2


@dataclass(slots=True)
class Ball:
    position: Vec2
    velocity: Vec2 = None  # type: ignore[assignment]
    radius: float = 12.0
    alive: bool = True
    # Collision layer (ball+0x6e, set to 1 by the ball constructor
    # FUN_01019309); ramps and the ramp hole move it between layers.
    mask: int = 1
    # Inside a sink/kickout hole: out of play (the ball's active byte +5 is
    # cleared) until the hole ejects it.
    held: bool = False
    # Height above the table (ball+0x32). The constructor starts it at the
    # ball radius; a ramp triangle sets it from its plane (FUN_01016c24) and
    # the ramp hole drops it back down (FUN_010169c0). It only affects how
    # the ball is drawn and how long the hole's drop takes.
    z: float = 0.0
    z_velocity: float = 0.0  # ball+0x3e
    # The current ramp triangle's own gravity (ball+0x5e/+0x62), read by the
    # ramp's field while the ball is on the ramp's layer.
    ramp_gravity: Vec2 = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.velocity is None:
            self.velocity = Vec2(0.0, 0.0)
        if self.ramp_gravity is None:
            self.ramp_gravity = Vec2(0.0, 0.0)
        if self.z == 0.0:
            self.z = self.radius

    def speed(self) -> float:
        return self.velocity.length()
