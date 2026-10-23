"""The Warbands building catalog: every kind, every tier, as explicit geometry.

Tier rules (V2: one look per 10 levels, three looks at most):
  T0  the founding building - small, one structure, bare yard
  T1  rebuilt bigger on the same plot - a second storey or a second structure
  T2  the grand version - towers, stone footings, banners, the yard full of work
A tier keeps the same plate, the same main axis and the same door side, so tier N+1
reads as tier N upgraded rather than a different building.
"""

from __future__ import annotations

import math

from core import F, blob, box, cone, cyl, mesh
from parts import (banner, barrel, brazier, brick_stack, cart, courses, crate, fence, gable, hall, haystack,
                   lean_to, log, log_pile, plate, pyramid, sack, shed, stall, tower)

# plate (ground island) size per kind: constant across a kind's tiers
PLATES = {k: 7.2 for k in ("headquarters", "timber_camp", "clay_pit", "iron_mine", "farm", "warehouse",
                           "market", "barracks", "stable", "academy")}
PLATES.update({"wall_palisade": 4.4, "wall_timber": 4.4, "wall_stone": 4.4})


def shields(f: F, x0, x1, y, z, n, face="front"):
    for i in range(n):
        x = x0 + (x1 - x0) * (i + 0.5) / n
        mat = "banner" if i % 2 == 0 else "cloth_blue"
        if face == "front":
            cyl(0.22, 0.05, (x, y - 0.05, z), mat, f, rot=(math.pi / 2, 0, 0), seg=14)
            cyl(0.06, 0.05, (x, y - 0.1, z), "bronze", f, rot=(math.pi / 2, 0, 0), seg=8)


def headframe(f: F, at, h, w=1.2):
    x, y, z = at
    for sx in (-1, 1):
        for sy in (-1, 1):
            # A-frame legs leaning in to the top
            ang = math.atan2(w * 0.35, h)
            cyl(0.07, h / math.cos(ang), (x + sx * w / 2, y + sy * w / 2, z), "log", f,
                rot=(sy * ang, -sx * ang, 0), seg=8)
    box((w * 0.5, w * 0.5, 0.12), (x, y, z + h - 0.1), "timber", f)
    cyl(w * 0.32, 0.08, (x, y + 0.06, z + h + 0.15), "timber_light", f, rot=(math.pi / 2, 0, 0), seg=16)
    cyl(0.015, h * 0.8, (x, y, z + 0.1), "rope", f, seg=4)
    box((w * 0.7, w * 0.7, 0.04), (x, y, z + 0.005), "dark", f, bevel=0)


def gantry(f: F, at, h=1.8, w=1.2):
    x, y, z = at
    for sx in (-1, 1):
        cyl(0.06, h, (x + sx * w / 2, y, z), "log", f, seg=8)
    box((w + 0.3, 0.12, 0.12), (x, y, z + h), "timber_light", f)
    cyl(0.012, h * 0.45, (x, y, z + h * 0.55), "rope", f, seg=4)
    cyl(0.14, 0.2, (x, y, z + h * 0.45), "plank", f, seg=10, r2=0.17)


def bin_(f: F, at, w=1.6, d=1.1, h=0.45, fill="clay_wet", seed=1):
    x, y, z = at
    for sy in (-1, 1):
        box((w, 0.08, h), (x, y + sy * d / 2, z), "plank", f, bevel=0.01)
    for sx in (-1, 1):
        box((0.08, d, h), (x + sx * w / 2, y, z), "plank", f, bevel=0.01)
    blob(min(w, d) * 0.48, (x, y, z + h * 0.6), fill, f, squash=(w / d * 0.95, 0.95, 0.45), seed=seed, rough=0.12)


def dummy(f: F, at):
    x, y, z = at
    cyl(0.05, 1.3, (x, y, z), "timber", f, seg=6)
    box((0.7, 0.07, 0.07), (x, y, z + 0.95), "timber", f, bevel=0)
    blob(0.2, (x, y, z + 1.45), "hay", f, squash=(1, 1, 1.1), seed=7, rough=0.06)
    blob(0.24, (x, y, z + 0.85), "cloth", f, squash=(1.0, 0.7, 1.3), seed=8, rough=0.05)


def weapon_rack(f: F, at, n=4, rz=0.0):
    g = f.sub(at[0], at[1], at[2], rz)
    for sx in (-1, 1):
        cyl(0.04, 1.2, (sx * 0.5, 0, 0), "timber", g, seg=6)
    box((1.1, 0.06, 0.06), (0, 0, 1.0), "timber", g, bevel=0)
    for i in range(n):
        x = -0.4 + 0.8 * i / max(1, n - 1)
        cyl(0.018, 1.5, (x, 0.05, 0.0), "timber_light", g, seg=5)
        cone(0.05, 0.18, (x, 0.05, 1.5), "iron", g, seg=6)


def target(f: F, at):
    x, y, z = at
    for sx in (-1, 1):
        cyl(0.04, 1.1, (x + sx * 0.3, y + 0.15, z), "timber", f, seg=6)
    cyl(0.42, 0.12, (x, y, z + 0.85), "hay", f, rot=(math.pi / 2, 0, 0), seg=18)
    cyl(0.26, 0.13, (x, y, z + 0.85), "banner", f, rot=(math.pi / 2, 0, 0), seg=18)
    cyl(0.1, 0.14, (x, y, z + 0.85), "bronze", f, rot=(math.pi / 2, 0, 0), seg=12)


def water_wheel(f: F, at, r=0.8):
    x, y, z = at
    cyl(r, 0.25, (x, y - 0.12, z + r), "timber", f, rot=(math.pi / 2, 0, 0), seg=20, smooth=False)
    cyl(r * 0.3, 0.3, (x, y - 0.15, z + r), "timber_light", f, rot=(math.pi / 2, 0, 0), seg=10)
    for i in range(8):
        a = i * math.pi / 4
        box((0.08, 0.32, 0.22), (x + math.cos(a) * r, y, z + r + math.sin(a) * r - 0.11), "plank", f,
            rot=(0, -a, 0), bevel=0)


def stabbur(f: F, w, d, h, roof_h, stilts=0.6, roof="turf"):
    """A storehouse raised on stilts, the norse grain store."""
    for sx in (-1, 1):
        for sy in (-1, 1):
            cyl(0.1, stilts, (sx * (w / 2 - 0.15), sy * (d / 2 - 0.15), 0), "log", f, seg=8)
            box((0.32, 0.32, 0.12), (sx * (w / 2 - 0.15), sy * (d / 2 - 0.15), 0), "stone", f)
    box((w + 0.12, d + 0.12, 0.1), (0, 0, stilts), "timber_light", f)
    box((w, d, h), (0, 0, stilts + 0.1), "timber", f)
    box((0.6, 0.08, h * 0.75), (0, -d / 2 - 0.03, stilts + 0.1), "plank", f)
    for k in range(4):
        box((0.6, 0.3, 0.08), (0, -d / 2 - 0.35 - k * 0.22, stilts - 0.12 - k * stilts / 4), "plank", f, bevel=0)
    gable(w, d, roof_h, (0, 0, stilts + 0.1 + h), f, mat=roof)


def chimney(f: F, at, h=1.2, s=0.38, smoke_glow=False, mat="stone"):
    x, y, z = at
    box((s, s, h), (x, y, z), mat, f, bevel=0.03)
    if smoke_glow:
        box((s * 0.6, s * 0.6, 0.04), (x, y, z + h), "fire", f, bevel=0)


# ---------------------------------------------------------------------------- kinds

def headquarters(t: int):
    plate(PLATES["headquarters"], 11)
    if t == 0:
        hall(F(0, 0.4), 4.0, 2.6, 1.35, 1.5, windows=2)
        banner(F(), (-2.3, -1.3, 0), h=2.0)
        brazier(F(), (1.0, -1.6, 0))
        barrel(F(), (2.3, -0.9, 0))
        crate(F(), (2.6, -0.4, 0), rz=0.3)
    elif t == 1:
        hall(F(0, 0.5), 4.8, 3.0, 2.5, 1.9, storeys=2, plinth=0.4, windows=4)
        box((1.3, 0.6, 0.2), (0, -1.35, 0), "stone", bevel=0.03)
        hall(F(2.5, 1.1, 0, math.pi / 2), 1.8, 1.6, 1.1, 0.9, plinth=0.2, door=False, windows=1)
        for x in (-2.7, 2.2):
            banner(F(), (x, -1.4, 0), h=2.6, l=1.1)
        brazier(F(), (-0.95, -1.55, 0))
        brazier(F(), (0.95, -1.55, 0))
        for i in range(3):
            barrel(F(), (-2.6 + i * 0.45, 1.9, 0))
    else:
        top = hall(F(0, 0.5), 4.4, 3.0, 3.0, 2.0, storeys=3, plinth=0.55, windows=4)
        box((4.8, 0.2, 0.18), (0, 0.5, top - 0.06), "gold", bevel=0.02)
        for x in (-2.75, 2.75):
            tower(F(x, 0.7), 1.25, 3.9, roof="shingle", roof_h=1.6, plinth=0.55)
            cone(0.1, 0.45, (x, 0.7, 0.55 + 3.9 + 0.12 + 1.6), "gold", seg=8)
        box((1.6, 0.9, 0.3), (0, -1.55, 0), "stone", bevel=0.03)
        box((1.6, 0.5, 0.3), (0, -1.35, 0.3), "stone", bevel=0.03)
        shields(F(), -1.9, 1.9, -1.0, 1.5, 5)
        for x in (-1.25, 1.25):
            banner(F(), (x, -2.35, 0), h=3.2, w=0.55, l=1.4)
            brazier(F(), (x * 1.75, -2.0, 0))


def timber_camp(t: int):
    plate(PLATES["timber_camp"], 12)
    axe = lambda at: (cyl(0.26, 0.38, at, "log", seg=12),
                      cyl(0.02, 0.7, (at[0] + 0.05, at[1], at[2] + 0.38), "timber_light", rot=(0, 0.6, 0), seg=5),
                      box((0.06, 0.22, 0.16), (at[0] + 0.3, at[1], at[2] + 0.88), "iron", bevel=0))
    if t == 0:
        shed(F(-0.6, 1.0), 2.6, 1.7, 1.35, 0.8)
        log_pile(F(-0.6, 1.0), (0, 0, 0), length=2.0, rows=2, r=0.14, axis="x")
        log_pile(F(), (2.0, -0.5, 0), length=1.8, rows=3, axis="y")
        axe((-1.0, -1.6, 0))
    elif t == 1:
        shed(F(-0.3, 1.2), 4.0, 1.9, 1.6, 0.95, bays=2)
        log_pile(F(-0.3, 1.2), (-0.9, 0, 0), length=1.6, rows=3, axis="x")
        log_pile(F(-0.3, 1.2), (1.1, 0, 0), length=1.6, rows=3, axis="x")
        log_pile(F(), (2.4, -1.0, 0), length=2.0, rows=4, axis="y")
        log_pile(F(), (-2.3, -1.3, 0), length=1.6, rows=3, axis="x")
        cart(F(), (0.4, -1.9, 0), rz=0.1, load="plank")
        axe((-0.6, -0.6, 0))
    else:
        shed(F(-0.2, 1.5), 5.2, 2.0, 1.8, 1.05, bays=3)
        for x in (-1.6, 0.1, 1.8):
            log_pile(F(-0.2, 1.5), (x, 0, 0), length=1.5, rows=4, r=0.12, axis="x")
        # sawmill with a water wheel and its own race
        hall(F(-2.2, -1.2, 0, math.pi / 2), 1.8, 1.6, 1.2, 1.0, plinth=0.2, door=False, windows=1)
        mesh([(-2.9, -2.9, 0.008), (-2.9, -0.2, 0.008), (-2.5, -0.2, 0.008), (-2.5, -2.9, 0.008)],
             [(0, 1, 2, 3)], "water")
        water_wheel(F(-2.7, -1.2, 0, math.pi / 2), (0, 0, 0), r=0.7)
        # crane lifting a log
        for sy in (-1, 1):
            cyl(0.08, 2.9, (2.5, -0.3 + sy * 0.4, 0), "log", rot=(sy * 0.13, 0, 0), seg=8)
        cyl(0.07, 2.4, (2.5, -0.3, 2.75), "log", rot=(0, -1.2, 0), seg=8)
        cyl(0.012, 1.1, (0.35, -0.3, 2.05), "rope", seg=4)
        log(F(), (0.35, -0.3, 1.75), 1.4, 0.12, "y")
        log_pile(F(), (2.5, -2.0, 0), length=2.0, rows=4, axis="x")
        cart(F(), (0.2, -2.2, 0), rz=0.15, load="plank")
        axe((-0.8, -0.4, 0))


def clay_pit(t: int):
    plate(PLATES["clay_pit"], 13)
    if t == 0:
        bin_(F(), (-0.9, 0.3, 0), seed=2)
        shed(F(1.3, 1.4), 1.8, 1.2, 1.15, 0.7, roof="thatch")
        brick_stack(F(1.3, 1.4), (0, 0, 0), n=4)
        brick_stack(F(), (1.6, -1.0, 0), n=3)
        barrel(F(), (-2.2, -1.0, 0))
        cyl(0.02, 1.0, (-0.6, -1.4, 0), "timber_light", rot=(0.4, 0, 0), seg=5)
    elif t == 1:
        bin_(F(), (-1.3, 0.2, 0), w=1.8, seed=2)
        bin_(F(), (0.5, 0.2, 0), w=1.4, seed=3)
        gantry(F(), (-1.3, 0.2, 0), h=2.0, w=2.1)
        shed(F(0.6, 2.0), 3.6, 1.3, 1.3, 0.8, roof="thatch", bays=2)
        for x in (-0.6, 0.6, 1.6):
            brick_stack(F(0.6, 2.0), (x, 0, 0), n=4)
        brick_stack(F(), (2.3, -0.6, 0), n=5)
        cart(F(), (0.6, -1.9, 0), rz=-0.1, load="brick")
    else:
        for i, (x, w) in enumerate(((-1.6, 1.6), (0.2, 1.6), (2.0, 1.3))):
            bin_(F(), (x, 0.0, 0), w=w, seed=4 + i)
        gantry(F(), (-1.6, 0.0, 0), h=2.3, w=1.9)
        gantry(F(), (0.2, 0.0, 0), h=2.3, w=1.9)
        shed(F(-0.2, 2.1), 4.4, 1.3, 1.4, 0.8, roof="thatch", bays=3)
        for x in (-1.7, -0.5, 0.7, 1.8):
            brick_stack(F(-0.2, 2.1), (x, 0, 0), n=5)
        # the kiln: a brick dome with a glowing mouth and a chimney
        blob(1.0, (2.3, 1.9, 0), "brick", squash=(1, 1, 0.85), seed=21, rough=0.03, sub=3)
        box((0.5, 0.1, 0.4), (2.3, 0.95, 0.05), "fire", bevel=0)
        chimney(F(), (2.6, 2.2, 0.6), h=1.4, s=0.36, smoke_glow=True)
        brick_stack(F(), (-2.3, -1.6, 0), n=6)
        brick_stack(F(), (-1.4, -2.0, 0), n=4)
        cart(F(), (0.9, -2.1, 0), rz=-0.1, load="brick")


def iron_mine(t: int):
    plate(PLATES["iron_mine"], 14)
    big = [1.5, 1.65, 1.8][t]
    # the outcrop stays inside the cell: it grows taller and deeper with the tier, not wider
    blob(big, (-1.0, 1.9, -0.2), "rock", squash=(1.05, 0.8, 0.85 + 0.12 * t), seed=31, rough=0.2)
    blob(big * 0.7, (0.9, 2.0, -0.2), "rock", squash=(1.1, 0.8, 0.9 + 0.1 * t), seed=32, rough=0.2)
    # the adit: a timber-framed mouth in the rock face
    box((0.9, 0.3, 1.2), (-1.0, 1.9 - big * 0.8 * 0.85, 0), "dark", bevel=0)
    for sx in (-1, 1):
        box((0.16, 0.18, 1.3), (-1.0 + sx * 0.52, 1.85 - big * 0.8 * 0.85, 0), "log")
    box((1.3, 0.2, 0.18), (-1.0, 1.85 - big * 0.8 * 0.85, 1.3), "log")
    blob(0.55, (1.6, -0.5, 0), "ore", squash=(1.2, 1, 0.6), seed=33)
    # forge: stone hearth, fire, anvil
    box((0.9, 0.7, 0.55), (-2.0, -1.0, 0), "stone", bevel=0.04)
    box((0.6, 0.45, 0.06), (-2.0, -1.0, 0.55), "fire", bevel=0)
    box((0.35, 0.18, 0.28), (-1.2, -1.6, 0.25), "iron", bevel=0.02)
    cyl(0.18, 0.25, (-1.2, -1.6, 0), "log", seg=10)
    if t >= 1:
        headframe(F(), (1.4, 0.6, 0), h=3.1 if t == 1 else 3.4, w=1.5 if t == 1 else 1.6)
        # the winch house: a real building beside the shaft (the T1 upgrade has to read)
        hall(F(2.3, -1.4, 0, math.pi / 2), 2.0, 1.5, 1.25, 1.0, plinth=0.2, door=False, windows=2)
        chimney(F(), (-2.2, -0.75, 0.55), h=1.3, s=0.32, mat="stone_dark")
        for k in range(2):
            box((0.05, 2.4, 0.05), (0.3 + k * 0.45, -1.2, 0.02), "iron", bevel=0)
        cart(F(), (0.5, -1.4, 0), rz=math.pi / 2, load="ore")
        blob(0.5, (2.4, 0.2, 0), "ore", squash=(1.2, 1, 0.6), seed=34)
        log_pile(F(), (-1.0, -2.5, 0), length=1.3, rows=3, r=0.11, axis="x")
    if t == 2:
        headframe(F(), (-0.2, 0.2, 0), h=2.8, w=1.3)
        # smelting hall with a tall glowing stack
        hall(F(-1.9, -1.0, 0, 0), 2.0, 1.5, 1.4, 1.0, mat="stone", plinth=0.2, windows=2, door=False)
        cyl(0.3, 2.6, (-2.6, -0.6, 0.2), "stone_dark", seg=12)
        cyl(0.22, 0.06, (-2.6, -0.6, 2.8), "fire", seg=12)
        blob(0.6, (2.6, 1.6, 0), "slag", squash=(1.2, 1, 0.55), seed=35)
        for k in range(3):
            for i in range(3 - k):
                box((0.35, 0.14, 0.1), (1.0 + i * 0.36 + k * 0.18, -2.4, k * 0.1), "iron", bevel=0.01)


def farm(t: int):
    plate(PLATES["farm"], 15)

    def field(x, y, w, d, rows, mat):
        for i in range(rows):
            yy = y - d / 2 + (i + 0.5) * d / rows
            box((w, d / rows * 0.6, 0.12), (x, yy, 0), mat, bevel=0.03)
            box((w, d / rows * 0.4, 0.02), (x, yy + d / rows * 0.5, 0), "dirt", bevel=0)

    def scarecrow(x, y):
        cyl(0.04, 1.4, (x, y, 0), "timber", seg=6)
        box((0.8, 0.05, 0.05), (x, y, 1.05), "timber", bevel=0)
        blob(0.15, (x, y, 1.45), "hay", seed=9, rough=0.05)
        cone(0.2, 0.18, (x, y, 1.53), "hay", seg=10)
        blob(0.2, (x, y, 0.95), "cloth_blue", squash=(1, 0.6, 1.3), seed=10, rough=0.05)

    if t == 0:
        hall(F(-0.9, 1.3), 3.0, 2.0, 1.05, 1.25, roof="thatch", windows=1, plinth=0.15)
        chimney(F(), (-1.6, 1.6, 1.6), h=0.6, s=0.3)
        field(1.9, -0.8, 2.0, 2.2, 5, "crop")
        haystack(F(), (-2.4, -1.4, 0))
        scarecrow(1.9, -0.6)
        fence(F(), (0.75, -2.0), (0.75, 0.4))
    elif t == 1:
        hall(F(-0.8, 1.4), 3.6, 2.2, 1.2, 1.4, roof="thatch", windows=2, plinth=0.2)
        chimney(F(), (-1.7, 1.7, 1.8), h=0.7, s=0.32)
        hall(F(2.05, 1.5, 0, math.pi / 2), 2.2, 1.7, 1.5, 1.2, roof="thatch", door_side="side", windows=0,
             plinth=0.1, mat="plank")
        field(1.6, -1.2, 2.4, 1.6, 4, "crop")
        field(-1.6, -1.5, 1.8, 1.4, 4, "crop_green")
        haystack(F(), (0.1, -0.2, 0), r=0.45, h=0.9)
        haystack(F(), (-3.0, 0.1, 0), r=0.4, h=0.8)
        cart(F(), (0.2, -2.4, 0), rz=0.2, load="hay")
    else:
        hall(F(-0.8, 1.5), 4.0, 2.4, 2.1, 1.5, roof="thatch", storeys=2, windows=3, plinth=0.3)
        chimney(F(), (-2.0, 1.8, 2.8), h=0.8, s=0.34)
        hall(F(2.25, 1.4, 0, math.pi / 2), 2.6, 1.8, 1.8, 1.3, roof="thatch", door_side="side", windows=0,
             plinth=0.2, mat="plank")
        stabbur(F(2.25, -1.75), 1.3, 1.1, 0.9, 0.75, stilts=0.55)
        field(0.4, -1.3, 2.2, 1.8, 5, "crop")
        field(-2.2, -1.2, 1.5, 1.8, 4, "crop_green")
        fence(F(), (-3.1, -2.3), (1.6, -2.3))
        haystack(F(), (1.0, 0.0, 0), r=0.45, h=0.9)
        haystack(F(), (-3.0, 0.4, 0), r=0.45, h=0.9)
        scarecrow(0.4, -1.1)
        banner(F(), (-3.0, 1.4, 0), h=2.6)


def warehouse(t: int):
    plate(PLATES["warehouse"], 16)
    if t == 0:
        stabbur(F(0, 0.6), 2.2, 1.7, 1.25, 1.1, stilts=0.65)
        for i, (x, y) in enumerate(((-1.8, -0.9), (-1.4, -1.4), (1.6, -0.8))):
            crate(F(), (x, y, 0), rz=0.2 * i)
        sack(F(), (1.9, -1.3, 0.12), seed=1)
        sack(F(), (2.2, -1.0, 0.12), seed=2)
        barrel(F(), (-2.3, 0.3, 0))
    elif t == 1:
        for sx in (-1, 1):
            for sy in (-1, 1):
                box((0.5, 0.5, 0.5), (sx * 1.5, 0.8 + sy * 1.0, 0), "stone", bevel=0.04)
        g = F(0, 0.8, 0.5)
        hall(g, 3.4, 2.4, 2.2, 1.6, storeys=2, plinth=0, windows=2)
        for k in range(4):
            box((0.7, 0.3, 0.08), (0, -0.55 - k * 0.25, 0.42 - k * 0.12), "plank", bevel=0)
        lean_to(1.3, 2.2, 0.5, (2.55, 0.8, 1.2), F(0, 0, 0, 0), mat="turf")
        for y in (0.0, 0.6, 1.2):
            barrel(F(), (2.6, y, 0))
        for i, (x, y) in enumerate(((-2.0, -1.0), (-1.5, -1.4), (-2.3, -1.6), (1.4, -1.5))):
            crate(F(), (x, y, 0), rz=0.15 * i)
        crate(F(), (-2.0, -1.0, 0.4), s=0.35, rz=0.5)
        for i in range(3):
            sack(F(), (0.9 + i * 0.3, -1.9, 0.12), seed=i)
    else:
        top = hall(F(-0.3, 0.9), 4.4, 2.6, 2.7, 1.8, storeys=2, mat="timber", plinth=0.7, windows=3)
        # hoist beam out of the gable with a crate on the rope
        box((1.2, 0.18, 0.18), (2.3, 0.9, 3.1), "timber_light")
        cyl(0.012, 1.4, (2.75, 0.9, 1.7), "rope", seg=4)
        crate(F(), (2.75, 0.9, 1.3), s=0.38)
        stabbur(F(1.95, -1.85), 1.4, 1.2, 1.0, 0.8, stilts=0.5)
        for x in (-2.7, -2.25, -1.8):
            for y in (-1.2, -1.65):
                barrel(F(), (x, y, 0))
        for i, (x, y, z) in enumerate(((-0.8, -1.4, 0), (-0.35, -1.6, 0), (-0.6, -1.5, 0.4), (0.4, -1.9, 0))):
            crate(F(), (x, y, z), rz=0.2 * i)
        for i in range(4):
            sack(F(), (0.35 + i * 0.26, -2.3, 0.12), seed=10 + i)
        banner(F(), (-2.6, 0.0, 0), h=2.4)


def market(t: int):
    plate(PLATES["market"], 17)
    if t == 0:
        stall(F(), (-1.1, 0.6, 0), cloth="banner")
        stall(F(), (1.3, 1.0, 0), cloth="cloth_blue", rz=-0.25)
        for i, (x, y) in enumerate(((-2.2, -0.7), (0.2, -1.4), (2.3, -0.6))):
            crate(F(), (x, y, 0), rz=0.3 * i)
        barrel(F(), (-0.4, -0.6, 0))
        barrel(F(), (2.0, -1.2, 0))
        sack(F(), (0.5, -0.8, 0.12), seed=4)
        banner(F(), (-2.6, 1.6, 0), h=2.2)
    else:
        shed(F(0, 1.6), 4.6, 2.0, 1.9, 1.1, roof="shingle", bays=3, back_wall=True)
        for i, (x, c) in enumerate(((-1.5, "banner"), (0.0, "cloth_blue"), (1.5, "banner"))):
            stall(F(0, 1.6), (x, 0.1, 0), w=1.1, d=0.8, cloth=c)
        stall(F(), (-1.9, -1.2, 0), w=1.1, d=0.8, cloth="cloth_blue", rz=0.3)
        stall(F(), (1.9, -1.3, 0), w=1.1, d=0.8, cloth="banner", rz=-0.3)
        cart(F(), (0.0, -1.6, 0), rz=0.05, load="hay")
        for x in (-3.0, 3.0):
            banner(F(), (x, 0.6, 0), h=2.8, l=1.2)
        for i, (x, y) in enumerate(((-2.9, -0.5), (2.8, -0.4), (0.9, -0.4))):
            barrel(F(), (x, y, 0))


def barracks(t: int):
    plate(PLATES["barracks"], 18)
    if t == 0:
        hall(F(-0.4, 1.1), 3.6, 2.2, 1.25, 1.4, windows=2)
        shields(F(), -1.9, 1.1, 0.0, 0.95, 3)
        weapon_rack(F(), (1.9, -1.0, 0))
        dummy(F(), (-1.4, -1.5, 0))
    elif t == 1:
        hall(F(-0.3, 1.2), 4.6, 2.6, 2.4, 1.8, storeys=2, plinth=0.35, windows=3)
        shields(F(), -2.4, 1.8, -0.1, 1.15, 5)
        fence(F(), (-3.0, -2.4), (3.0, -2.4))
        fence(F(), (3.0, -2.4), (3.0, -0.3))
        dummy(F(), (-1.6, -1.4, 0))
        dummy(F(), (-0.4, -1.7, 0))
        target(F(), (1.8, -1.2, 0))
        weapon_rack(F(), (2.6, 0.4, 0), rz=math.pi / 2)
        banner(F(), (-2.9, 0.2, 0), h=2.6)
    else:
        hall(F(-0.6, 1.3), 4.6, 2.6, 2.6, 1.9, storeys=2, plinth=0.5, windows=3)
        shields(F(), -2.7, 1.5, -0.0, 1.3, 6)
        tower(F(2.5, 1.6), 1.4, 3.9, roof="shingle", roof_h=1.7, plinth=0.4)
        # a stretch of palisade behind the yard
        for i in range(12):
            x = -3.2 + i * 0.29
            cyl(0.14, 2.0 - (i % 3) * 0.12, (x, 3.05, 0), "log", seg=8)
            cone(0.14, 0.3, (x, 3.05, 2.0 - (i % 3) * 0.12), "log", seg=8)
        fence(F(), (-3.2, -2.5), (3.2, -2.5))
        dummy(F(), (-2.2, -1.4, 0))
        dummy(F(), (-1.1, -1.8, 0))
        target(F(), (0.6, -1.5, 0))
        target(F(), (1.6, -1.8, 0))
        weapon_rack(F(), (2.9, -0.5, 0), rz=math.pi / 2)
        for x in (-3.1, 3.1):
            banner(F(), (x, 0.4, 0), h=3.0, l=1.3)
        brazier(F(), (-0.2, -0.6, 0))


def stable(t: int):
    plate(PLATES["stable"], 19)

    def stalls(f, w, d, n, z0):
        for i in range(n):
            x = -w / 2 + (i + 0.5) * w / n
            box((0.55, 0.08, 0.55), (x, -d / 2 - 0.03, z0), "plank", f)
            box((0.55, 0.06, 0.4), (x, -d / 2 - 0.02, z0 + 0.58), "dark", f, bevel=0)

    def trough(x, y):
        box((1.0, 0.4, 0.32), (x, y, 0), "plank", bevel=0.02)
        box((0.9, 0.3, 0.02), (x, y, 0.3), "water", bevel=0)

    if t == 0:
        g = F(-0.7, 1.0)
        hall(g, 3.8, 2.0, 1.15, 1.1, roof="thatch", door=False, windows=0, plinth=0.15)
        stalls(g, 3.8, 2.0, 4, 0.15)
        fence(F(), (0.4, -2.6), (3.0, -2.6))
        fence(F(), (3.0, -2.6), (3.0, 0.3))
        trough(1.7, -1.2)
        haystack(F(), (-2.5, -1.3, 0), r=0.45, h=0.8)
    else:
        g = F(-0.7, 1.4)
        hall(g, 4.4, 2.2, 1.9, 1.5, roof="thatch", storeys=2, door=False, windows=0, plinth=0.25)
        stalls(g, 4.4, 2.2, 5, 0.25)
        box((0.6, 0.08, 0.6), (-0.7, 1.4 - 1.13, 1.35), "plank")
        g2 = F(2.3, 0.6, 0, math.pi / 2)
        hall(g2, 2.6, 1.7, 1.2, 1.1, roof="thatch", door=False, windows=0, plinth=0.2)
        fence(F(), (-0.6, -2.7), (3.1, -2.7))
        fence(F(), (3.1, -2.7), (3.1, -0.9))
        fence(F(), (-0.6, -2.7), (-0.6, -0.6))
        trough(1.3, -1.4)
        trough(1.3, -2.1)
        cart(F(), (-2.4, -1.6, 0), rz=1.2, load="hay")
        haystack(F(), (-2.6, -0.2, 0), r=0.4, h=0.8)
        banner(F(), (-3.1, 1.6, 0), h=2.6)


def academy(t: int):
    plate(PLATES["academy"], 20)
    # the rune tower: round stone, conical turf roof with a carved finial
    cyl(1.0, 3.2, (-1.0, 1.0, 0), "stone", seg=24)
    cyl(1.08, 0.18, (-1.0, 1.0, 3.2), "timber_light", seg=24)
    cyl(1.25, 1.7, (-1.0, 1.0, 3.38), "turf", seg=24, r2=0.0, smooth=False)
    cone(0.08, 0.5, (-1.0, 1.0, 5.0), "gold", seg=8)
    for a in (-0.3, 0.6):
        box((0.22, 0.08, 0.4), (-1.0 + math.sin(a) * 1.0, 1.0 - math.cos(a) * 1.0, 2.0), "window",
            rot=(0, 0, a), bevel=0)
    hall(F(1.1, 0.9), 2.4, 1.8, 1.2, 1.2, windows=2)
    # a ring of rune stones around the fire
    for i in range(5):
        a = math.pi * (0.15 + 0.7 * i / 4) + math.pi
        x, y = 0.2 + math.cos(a) * 1.5, -1.0 + math.sin(a) * 0.9
        box((0.32, 0.2, 0.9 + 0.15 * (i % 2)), (x, y, 0), "stone_dark", rot=(0, 0, a), bevel=0.05)
    brazier(F(), (0.2, -1.0, 0))
    banner(F(), (2.6, -0.6, 0), h=2.4, mat="cloth_blue")


def wall_palisade(t: int = 0):
    plate(PLATES["wall_palisade"], 21)
    s, n = 1.7, 7
    for side in range(4):
        for i in range(n):
            u = -s / 2 + s * i / n
            x, y = [(u, -s / 2), (s / 2, u), (-u, s / 2), (-s / 2, -u)][side]
            hgt = 3.1 + (0.12 if (i + side) % 2 else 0.0)
            cyl(0.13, hgt, (x, y, 0), "log", seg=8)
            cone(0.13, 0.35, (x, y, hgt), "log", seg=8)
    box((s + 0.5, s + 0.5, 0.1), (0, 0, 2.6), "plank", bevel=0.01)
    for k in (0.9, 1.9):
        box((s + 0.3, s + 0.3, 0.07), (0, 0, k), "rope", bevel=0)
    blob(0.16, (0, -s / 2 - 0.15, 2.1), "bone", squash=(0.9, 0.8, 1.0), seed=5, rough=0.06)
    cyl(0.03, 0.5, (0.55, -s / 2 - 0.15, 1.6), "timber", seg=5)
    cone(0.07, 0.18, (0.55, -s / 2 - 0.15, 2.1), "fire", seg=6)


def wall_timber(t: int = 1):
    plate(PLATES["wall_timber"], 22)
    tower(F(), 1.8, 3.2, roof="shingle", roof_h=1.5, plinth=0.25, mat="timber")
    for z in (0.9, 1.9, 2.9):
        box((1.86, 1.86, 0.08), (0, 0, z), "iron", bevel=0)
    for i in range(6):
        box((0.06, 0.3, 0.05), (1.0, -0.6 + i * 0.0, 0.4 + i * 0.4), "timber_light", bevel=0)
    banner(F(), (-0.6, -1.15, 0), h=4.3, l=1.2)
    cyl(0.03, 0.5, (0.55, -1.0, 1.4), "timber", seg=5)
    cone(0.07, 0.18, (0.55, -1.0, 1.9), "fire", seg=6)


def wall_stone(t: int = 2):
    plate(PLATES["wall_stone"], 23)
    s = 2.0
    box((s + 0.3, s + 0.3, 0.4), (0, 0, 0), "stone_dark", bevel=0.05)
    box((s, s, 3.1), (0, 0, 0.4), "stone", bevel=0.04)
    courses(F(), s, s, 0.4, 3.5)
    for i in range(3):
        box((0.1, 0.06, 0.55), (-0.5 + i * 0.5, -s / 2 - 0.02, 1.4), "dark", bevel=0)
        box((0.06, 0.1, 0.55), (s / 2 + 0.02, -0.5 + i * 0.5, 1.4), "dark", bevel=0)
    # timber hoarding gallery and the shingled cap above the battlements
    box((s + 0.5, s + 0.5, 0.7), (0, 0, 3.5), "plank", bevel=0.02)
    for k in range(5):
        u = -s / 2 + 0.2 + k * (s - 0.4) / 4
        box((0.12, 0.08, 0.32), (u, -s / 2 - 0.27, 3.75), "dark", bevel=0)
    pyramid(s + 0.5, s + 0.5, 1.4, (0, 0, 4.2), mat="shingle")
    banner(F(), (-0.7, -1.45, 0), h=4.6, l=1.3)
    cyl(0.03, 0.5, (0.6, -1.08, 1.0), "timber", seg=5)
    cone(0.07, 0.18, (0.6, -1.08, 1.5), "fire", seg=6)


KINDS = {
    "headquarters": headquarters, "timber_camp": timber_camp, "clay_pit": clay_pit,
    "iron_mine": iron_mine, "farm": farm, "warehouse": warehouse, "market": market,
    "barracks": barracks, "stable": stable, "academy": academy,
    "wall_palisade": wall_palisade, "wall_timber": wall_timber, "wall_stone": wall_stone,
}
