"""Composite parts shared by every Warbands building: roofs, halls, towers, yard props.

Surfaces carry real structure (planks, plinth blocks, bargeboards, turf tufts) because the
refine pass paints ALONG the lineart: a plain box comes back as a plain painted box."""

from __future__ import annotations

import math
import random

from core import F, ORIGIN, blob, box, cone, cyl, mesh

_rng = random.Random(4242)


def planks(f: F, w, d, z0, z1, pitch=0.3, mats=("plank", "timber")):
    """Vertical plank strips proud of all four walls of a w x d box (local frame)."""
    h = z1 - z0
    for side in range(4):
        L = w if side % 2 == 0 else d
        n = max(2, int(round(L / pitch)))
        for i in range(n):
            u = -L / 2 + (i + 0.5) * L / n
            m = mats[i % len(mats)]
            sw = L / n * 0.92
            if side == 0:
                box((sw, 0.035, h), (u, -d / 2 - 0.012, z0), m, f, bevel=0.008)
            elif side == 1:
                box((0.035, sw, h), (w / 2 + 0.012, u, z0), m, f, bevel=0.008)
            elif side == 2:
                box((sw, 0.035, h), (u, d / 2 + 0.012, z0), m, f, bevel=0.008)
            else:
                box((0.035, sw, h), (-w / 2 - 0.012, u, z0), m, f, bevel=0.008)


def plinth_blocks(f: F, w, d, h, mats=("stone", "stone_dark"), z0=0.0):
    """A course of rough stone blocks around a plinth of size (w, d, h), base at z0."""
    for side in range(4):
        L = w if side % 2 == 0 else d
        u = -L / 2
        i = 0
        while u < L / 2 - 0.05:
            bw = min(_rng.uniform(0.28, 0.55), L / 2 - u)
            c = u + bw / 2
            bh = h * _rng.uniform(0.82, 0.98)
            m = mats[i % 2] if _rng.random() < 0.35 else mats[0]
            if side == 0:
                box((bw - 0.03, 0.07, bh), (c, -d / 2 - 0.02, z0), m, f, bevel=0.025)
            elif side == 1:
                box((0.07, bw - 0.03, bh), (w / 2 + 0.02, c, z0), m, f, bevel=0.025)
            elif side == 2:
                box((bw - 0.03, 0.07, bh), (c, d / 2 + 0.02, z0), m, f, bevel=0.025)
            else:
                box((0.07, bw - 0.03, bh), (-w / 2 - 0.02, c, z0), m, f, bevel=0.025)
            u += bw
            i += 1


def courses(f: F, w, d, z0, z1, row=0.32):
    """Stone courses up a wall: rows of blocks, each row its own random bond."""
    z = z0
    while z < z1 - 0.05:
        hh = min(row, z1 - z)
        plinth_blocks(f, w, d, hh, z0=z)
        z += hh


def tufts(f: F, pts, mat="turf", r=0.09):
    for (x, y, z) in pts:
        blob(r * _rng.uniform(0.8, 1.3), (x, y, z), mat, f, squash=(1.2, 1.2, 0.7), seed=_rng.randint(0, 9999),
             rough=0.25, sub=1)


def gable(w, d, h, at, f: F = ORIGIN, mat="turf", ov=0.18, beams=True, beam_mat="timber", ridge=True):
    """Gable roof, ridge along local X, eaves at z=at[2]. Crossed dragon beams at the gables,
    bargeboards up the gable edges, and (turf / thatch) tufts along the eaves and slopes."""
    hw, hd = w / 2.0 + ov, d / 2.0 + ov
    t = 0.14
    v = [(-hw, -hd, 0), (hw, -hd, 0), (hw, hd, 0), (-hw, hd, 0), (-hw, 0, h), (hw, 0, h),
         (-hw, -hd, t), (hw, -hd, t), (hw, hd, t), (-hw, hd, t)]
    faces = [(0, 1, 7, 6), (1, 2, 8, 7), (2, 3, 9, 8), (3, 0, 6, 9),
             (6, 7, 5, 4), (8, 9, 4, 5), (6, 4, 9), (7, 8, 5), (0, 3, 2, 1)]
    mesh(v, faces, mat, f, at)
    ax, ay, az = at
    ang = math.atan2(h - t, hd)
    slope_len = math.hypot(hd, h - t)
    for sx in (-hw - 0.02, hw + 0.02):
        for sgn in (-1, 1):
            # bargeboard: a plank along each gable edge
            cy = ay + sgn * hd / 2
            cz = az + t + (h - t) / 2 - 0.07
            box((0.07, slope_len + 0.05, 0.14), (ax + sx, cy, cz), "timber_light", f, rot=(-sgn * ang, 0, 0),
                bevel=0.01)
    if mat in ("turf", "thatch"):
        pts = []
        n = max(4, int(2 * hw / 0.32))
        for sgn in (-1, 1):
            for i in range(n):
                x = -hw + (i + 0.5) * 2 * hw / n
                pts.append((ax + x, ay + sgn * (hd - 0.02), az + t * 0.6))
            for _ in range(int(hw * 4)):
                x = _rng.uniform(-hw * 0.9, hw * 0.9)
                q = _rng.uniform(0.15, 0.85)
                pts.append((ax + x, ay + sgn * hd * (1 - q), az + t + (h - t) * q))
        tufts(f, pts, "turf" if mat == "turf" else "hay", r=0.08)
    if ridge:
        box((2 * hw + 0.1, 0.16, 0.12), (ax, ay, az + h - 0.03), beam_mat, f)
    if beams:
        L = 0.9
        for sx in (-hw - 0.03, hw + 0.03):
            for sgn in (-1, 1):
                # carved beam ends crossing above the apex, the longhall's silhouette mark
                cy = ay - sgn * 0.12 * math.cos(ang)
                cz = az + h + 0.12 * math.sin(ang) - 0.02
                box((0.09, L, 0.12), (ax + sx, cy, cz - 0.06), beam_mat, f,
                    rot=(-sgn * ang, 0, 0), bevel=0.01)


def pyramid(w, d, h, at, f: F = ORIGIN, mat="shingle", ov=0.12):
    hw, hd = w / 2 + ov, d / 2 + ov
    v = [(-hw, -hd, 0), (hw, -hd, 0), (hw, hd, 0), (-hw, hd, 0), (0, 0, h)]
    faces = [(0, 1, 2, 3), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    mesh(v, faces, mat, f, at)


def lean_to(w, d, h, at, f: F = ORIGIN, mat="turf"):
    """Single-slope roof: high at +Y, low at -Y."""
    hw, hd, t = w / 2, d / 2, 0.1
    v = [(-hw, -hd, 0), (hw, -hd, 0), (hw, hd, h), (-hw, hd, h),
         (-hw, -hd, t), (hw, -hd, t), (hw, hd, h + t), (-hw, hd, h + t)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh(v, faces, mat, f, at)


def hall(f: F, w, d, wall_h, roof_h, storeys=1, mat="timber", roof="turf", plinth=0.25,
         door=True, windows=2, posts="timber_light", beams=True, door_side="front"):
    """A norse hall: stone plinth, dark timber walls, light corner posts, turf gable roof.

    Ridge runs along local X; local -Y is the front (the camera-left face)."""
    if plinth:
        box((w + 0.3, d + 0.3, plinth), (0, 0, 0), "stone", f, bevel=0.05)
        plinth_blocks(f, w + 0.3, d + 0.3, plinth)
    z0 = plinth
    box((w, d, wall_h), (0, 0, z0), mat, f)
    if mat == "stone":
        courses(f, w, d, z0, z0 + wall_h)
    else:
        planks(f, w, d, z0, z0 + wall_h)
    for sx in (-1, 1):
        for sy in (-1, 1):
            box((0.2, 0.2, wall_h + 0.05), (sx * w / 2, sy * d / 2, z0), posts, f)
    sh = wall_h / storeys
    for s in range(1, storeys):
        zb = z0 + sh * s
        box((w + 0.12, d + 0.12, 0.13), (0, 0, zb - 0.06), posts, f)
        n = max(2, int(w / 1.1))
        for i in range(n):
            x = -w / 2 + (i + 0.5) * w / n
            box((0.28, 0.06, 0.34), (x, -d / 2 - 0.02, zb + sh * 0.35), "window", f, bevel=0)
        box((0.06, 0.28, 0.34), (w / 2 + 0.02, -d * 0.2, zb + sh * 0.35), "window", f, bevel=0)
        box((0.06, 0.28, 0.34), (w / 2 + 0.02, d * 0.2, zb + sh * 0.35), "window", f, bevel=0)
    if door:
        dh = min(1.1, sh * 0.8)
        if door_side == "front":
            box((0.7, 0.1, dh), (0, -d / 2 - 0.03, z0), "plank", f)
            box((0.95, 0.14, 0.13), (0, -d / 2 - 0.04, z0 + dh), posts, f)
            for k in (0.3, 0.7):
                box((0.74, 0.12, 0.05), (0, -d / 2 - 0.06, z0 + dh * k), "iron", f, bevel=0)
        else:
            box((0.1, 0.7, dh), (w / 2 + 0.03, 0, z0), "plank", f)
            box((0.14, 0.95, 0.13), (w / 2 + 0.04, 0, z0 + dh), posts, f)
    zw = z0 + min(sh, 1.4) * 0.45
    for i in range(windows):
        if i % 2 == 0:
            x = (w * 0.3) * (1 if i % 4 == 0 else -1)
            box((0.3, 0.06, 0.32), (x, -d / 2 - 0.02, zw), "window", f, bevel=0)
            box((0.42, 0.05, 0.08), (x, -d / 2 - 0.04, zw + 0.33), posts, f, bevel=0)
        else:
            y = d * 0.25 * (1 if i % 4 == 1 else -1)
            box((0.06, 0.3, 0.32), (w / 2 + 0.02, y, zw), "window", f, bevel=0)
            box((0.05, 0.42, 0.08), (w / 2 + 0.04, y, zw + 0.33), posts, f, bevel=0)
    top = z0 + wall_h
    gable(w, d, roof_h, (0, 0, top), f, mat=roof, beams=beams)
    return top + roof_h


def tower(f: F, s, h, roof="shingle", mat="timber", roof_h=None, plinth=0.2, windows=True,
          posts="timber_light"):
    if plinth:
        box((s + 0.25, s + 0.25, plinth), (0, 0, 0), "stone", f, bevel=0.04)
        plinth_blocks(f, s + 0.25, s + 0.25, plinth)
    box((s, s, h), (0, 0, plinth), mat, f)
    if mat == "stone":
        courses(f, s, s, plinth, plinth + h)
    else:
        planks(f, s, s, plinth, plinth + h, pitch=0.26)
    for sx in (-1, 1):
        for sy in (-1, 1):
            box((0.16, 0.16, h), (sx * s / 2, sy * s / 2, plinth), posts, f)
    box((s + 0.3, s + 0.3, 0.12), (0, 0, plinth + h), posts, f)
    if windows:
        box((0.2, 0.06, 0.34), (0, -s / 2 - 0.02, plinth + h * 0.72), "window", f, bevel=0)
        box((0.06, 0.2, 0.34), (s / 2 + 0.02, 0, plinth + h * 0.72), "window", f, bevel=0)
    rh = roof_h if roof_h is not None else s * 1.1
    pyramid(s + 0.1, s + 0.1, rh, (0, 0, plinth + h + 0.12), f, mat=roof)
    return plinth + h + 0.12 + rh


def shed(f: F, w, d, h, roof_h=0.7, roof="turf", bays=1, back_wall=True):
    """An open shed on log posts: the timber camp / drying shed / market hall."""
    n = bays + 1
    for i in range(n):
        x = -w / 2 + i * w / bays
        for sy in (-1, 1):
            cyl(0.09, h, (x, sy * d / 2, 0), "log", f, seg=8)
    if back_wall:
        box((w, 0.12, h * 0.75), (0, d / 2, 0), "plank", f)
    box((w + 0.2, 0.14, 0.14), (0, -d / 2, h - 0.07), "timber_light", f)
    box((w + 0.2, 0.14, 0.14), (0, d / 2, h - 0.07), "timber_light", f)
    gable(w, d, roof_h, (0, 0, h), f, mat=roof, beams=True)


def banner(f: F, at, h=1.6, w=0.45, l=0.9, mat="banner"):
    x, y, z = at
    cyl(0.04, h, (x, y, z), "timber", f, seg=8)
    box((0.03, w, l), (x - 0.03, y - w / 2 - 0.04, z + h - l - 0.08), mat, f, bevel=0)
    cone(0.06, 0.16, (x, y, z + h), "bronze", f, seg=8)


def brazier(f: F, at):
    x, y, z = at
    cyl(0.05, 0.45, (x, y, z), "iron", f, seg=8)
    cyl(0.22, 0.14, (x, y, z + 0.45), "bronze", f, seg=12, r2=0.28)
    cone(0.18, 0.32, (x, y, z + 0.55), "fire", f, seg=8)


def log(f: F, at, length, r=0.13, axis="x"):
    x, y, z = at
    if axis == "x":
        rot = (0, math.pi / 2, 0)
        cyl(r, length, (x - length / 2, y, z + r), "log", f, rot=rot, seg=10)
        for e in (-1, 1):
            cyl(r * 0.9, 0.02, (x + e * length / 2 - (0.02 if e < 0 else 0.0), y, z + r), "log_end", f,
                rot=rot, seg=10, smooth=False)
    else:
        rot = (math.pi / 2, 0, 0)
        cyl(r, length, (x, y + length / 2, z + r), "log", f, rot=rot, seg=10)
        for e in (-1, 1):
            cyl(r * 0.9, 0.02, (x, y + e * length / 2 + (0.02 if e > 0 else 0.0), z + r), "log_end", f,
                rot=rot, seg=10, smooth=False)


def log_pile(f: F, at, length=1.6, rows=3, r=0.13, axis="x"):
    x, y, z = at
    for row in range(rows):
        n = rows - row
        for i in range(n):
            off = (i - (n - 1) / 2) * 2 * r * 1.02
            zz = z + row * r * 1.75
            if axis == "x":
                log(f, (x, y + off, zz), length, r, "x")
            else:
                log(f, (x + off, y, zz), length, r, "y")


def barrel(f: F, at, r=0.2, h=0.45):
    x, y, z = at
    cyl(r, h, (x, y, z), "plank", f, seg=12)
    for k in (0.15, 0.85):
        cyl(r + 0.012, 0.04, (x, y, z + h * k - 0.02), "iron", f, seg=12)


def crate(f: F, at, s=0.4, rz=0.0):
    box((s, s, s), at, "plank", f, rot=(0, 0, rz), bevel=0.02)


def sack(f: F, at, seed=0):
    blob(0.18, at, "cloth", f, squash=(1.0, 0.8, 0.75), seed=seed, rough=0.08)


def haystack(f: F, at, r=0.55, h=1.0):
    x, y, z = at
    cyl(r, h * 0.55, (x, y, z), "hay", f, seg=14, r2=r * 0.95)
    blob(r * 0.98, (x, y, z + h * 0.55), "hay", f, squash=(1, 1, 0.85), seed=int(r * 100), rough=0.05)


def fence(f: F, a, b, h=0.55, n=None, mat="timber_light"):
    ax, ay = a
    bx, by = b
    L = math.hypot(bx - ax, by - ay)
    n = n or max(2, int(L / 0.55) + 1)
    ang = math.atan2(by - ay, bx - ax)
    for i in range(n):
        t = i / (n - 1)
        cyl(0.045, h, (ax + (bx - ax) * t, ay + (by - ay) * t, 0), mat, f, seg=6)
    for zz in (h * 0.45, h * 0.85):
        box((L, 0.05, 0.06), ((ax + bx) / 2, (ay + by) / 2, zz), mat, f, rot=(0, 0, ang), bevel=0)


def stall(f: F, at, w=1.2, d=0.8, cloth="banner", rz=0.0):
    g = f.sub(at[0], at[1], at[2], rz)
    box((w, d, 0.55), (0, 0, 0), "plank", g)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cyl(0.04, 1.35, (sx * w / 2, sy * d / 2, 0), "timber_light", g, seg=6)
    n = 5
    for i in range(n):
        x = -w / 2 - 0.05 + (i + 0.5) * (w + 0.1) / n
        lean_to((w + 0.1) / n, d + 0.3, 0.3, (x, 0, 1.3), g, mat=cloth if i % 2 == 0 else "cloth")
    for i, m in enumerate(("hay", "clay", "crop_green")):
        blob(0.13, (-w / 3 + i * w / 3, -0.1, 0.62), m, g, squash=(1, 1, 0.6), seed=i)


def cart(f: F, at, rz=0.0, load="log"):
    g = f.sub(at[0], at[1], at[2], rz)
    box((1.2, 0.7, 0.12), (0, 0, 0.32), "plank", g)
    for sy in (-1, 1):
        box((1.2, 0.05, 0.22), (0, sy * 0.33, 0.44), "plank", g, bevel=0)
        cyl(0.3, 0.06, (0.15, sy * 0.4 + (0.03 if sy > 0 else -0.03), 0.3), "timber", g,
            rot=(math.pi / 2, 0, 0), seg=14)
    box((0.9, 0.06, 0.06), (0.95, 0, 0.36), "timber", g, bevel=0)
    if load == "log":
        for i in range(3):
            log(g, (0, -0.2 + i * 0.2, 0.44), 1.1, 0.09, "x")
    elif load == "ore":
        blob(0.35, (0, 0, 0.45), "ore", g, squash=(1.4, 0.8, 0.5), seed=3)
    elif load == "hay":
        blob(0.4, (0, 0, 0.45), "hay", g, squash=(1.4, 0.8, 0.6), seed=4)
    elif load == "brick":
        for i in range(3):
            box((0.9, 0.5, 0.12), (0, 0, 0.44 + i * 0.12), "brick", g, bevel=0.01)
    elif load == "plank":
        for i in range(4):
            box((1.1, 0.5, 0.06), (0, 0, 0.44 + i * 0.065), "timber_light", g, bevel=0.005)


def brick_stack(f: F, at, n=3, mat="brick"):
    x, y, z = at
    for k in range(n):
        box((0.7, 0.45, 0.14), (x, y, z + k * 0.145), mat, f, rot=(0, 0, 0.0 if k % 2 == 0 else 0.08),
            bevel=0.01)


def plate(size: float, seed: int):
    """The building's footprint: one game cell (lane edge to lane edge), as a SHADOW CATCHER.

    The plate is not painted into the sprite any more: a painted grass slab with a cut-earth
    rim read as a platform floating over the village yard. The plane only catches the
    building's own shadows (contact shadows, ambient occlusion, the cast shadow), which the
    pipeline keeps as a soft dark alpha layer - so in the game the building stands on the
    yard's own grass. Its matid ("grass") also tells the pipeline where the footprint is."""
    h = size / 2.0
    obj = mesh([(-h, -h, 0.0), (h, -h, 0.0), (h, h, 0.0), (-h, h, 0.0)], [(0, 1, 2, 3)], "grass")
    obj.is_shadow_catcher = True
    obj["wb_plate"] = True
    return obj
