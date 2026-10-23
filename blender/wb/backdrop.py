"""The village backdrop, seen by the village's own iso camera and registered to the SVG.

The backdrop is the land AROUND the village. It used to be an eye-level landscape (a
perspective valley with a horizon) behind an orthographic 30-degree village, so the two
could never read as one place. Now it is the same projection, the same scale and the same
centre as the scene (see `backdrop_scene()` in the game's gen-artworkflow-manifest.py):

  * a terrace block exactly under the SVG terrace (hidden by it; it is here to cast its real
    shadow on the valley floor and to occlude what is behind it);
  * the valley floor at the terrace FOOT (the SVG terrace's cut faces end exactly on it);
  * a dirt road leaving the village gate, forest massed in the corners, boulders;
  * a forested ridge along the back with sky above it - an orthographic camera has no
    vanishing horizon, so the land ENDS in a ridge and the sky is what lies beyond it.

Nothing that would stand IN FRONT of the village is placed where the village is drawn: the
SVG is always painted over the backdrop, so a tree overlapping the terrace on screen would
be hidden behind it while it should hide the terrace. Those trees are rejected by testing
their projected silhouette against the terrace's screen polygon.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import bpy
from mathutils import Vector

import core
from core import blob, box, cone, cyl, mesh


def _hull(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _inside(poly: list[tuple[float, float]], p: tuple[float, float]) -> bool:
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) < 0:
            return False
    return True


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def run_backdrop(job: dict) -> None:
    sc = job["scene"]
    W, H = job.get("res", [2048, 1024])
    k = sc["px_per_world"]
    T = Vector(sc["target"])
    fz = sc["floor_z"]
    x0, y0, x1, y1 = sc["yard"]
    rng = random.Random(int(job.get("seed", 5)))
    scene = core.reset()
    scene.render.film_transparent = False
    right, up, fwd, rot = core.iso_basis()
    rhat = Vector((1, 1, 0)).normalized()   # screen right, on the ground
    bhat = Vector((-1, 1, 0)).normalized()  # screen up (away from the camera), on the ground

    def px(p: Vector) -> tuple[float, float]:
        d = p - T
        return (W / 2 + d.dot(right) * k, H / 2 - d.dot(up) * k)

    def ground(s: float, d: float, z: float = 0.0) -> Vector:
        return T + rhat * s + bhat * d + Vector((0, 0, fz + z))

    # the village's screen footprint: terrace top raised by the wall, down to its foot
    top = [Vector((x, y, 0.0)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    village = _hull([px(p) for p in top] + [px(p + Vector((0, 0, fz))) for p in top]
                    + [(px(p)[0], px(p)[1] - sc["wall_px"]) for p in top])
    cxy = (sum(p[0] for p in village) / len(village), sum(p[1] for p in village) / len(village))
    village_pad = [(cxy[0] + (p[0] - cxy[0]) * 1.03, cxy[1] + (p[1] - cxy[1]) * 1.03) for p in village]

    def hides_village(points: list[Vector]) -> bool:
        return any(_inside(village_pad, px(p)) for p in points)

    # terrace block: exactly under the SVG terrace
    box((x1 - x0, y1 - y0, -fz), ((x0 + x1) / 2, (y0 + y1) / 2, fz), "earth", bevel=0)

    # the valley floor, built in screen-aligned (s, d) coordinates so the ridge runs level
    # across the frame; flat near the terrace (its foot must meet the floor exactly)
    ridge_d = 22.0
    S0, S1, D0 = -48.0, 48.0, -46.0
    ns, nd = 120, 70
    verts, faces = [], []

    def undulate(s, d):
        p = ground(s, d)
        dist = max(0.0, max(x0 - p.x, p.x - x1, y0 - p.y, p.y - y1))
        return 0.35 * math.sin(s * 0.21) * math.cos(d * 0.17) * _smooth((dist - 4) / 8)

    for j in range(nd + 1):
        d = D0 + (ridge_d - 7 - D0) * j / nd
        for i in range(ns + 1):
            s = S0 + (S1 - S0) * i / ns
            verts.append(tuple(ground(s, d, undulate(s, d))))
    for j in range(nd):
        for i in range(ns):
            a = j * (ns + 1) + i
            faces.append((a, a + 1, a + ns + 2, a + ns + 1))
    mesh(verts, faces, "grass", smooth=True)

    # the ridge: rises over 7 units to a forested crest; nothing lies behind it but sky
    def crest(s: float) -> float:
        return 4.6 + 2.2 * math.sin(s * 0.085 + 1.0) + 1.3 * math.sin(s * 0.23 + 0.4) + 0.6 * math.sin(s * 0.61)

    rv, rf = [], []
    nr = 10
    for j in range(nr + 1):
        t = j / nr
        d = ridge_d - 7 + 7 * t
        for i in range(ns + 1):
            s = S0 + (S1 - S0) * i / ns
            rv.append(tuple(ground(s, d, crest(s) * _smooth(t))))
    for j in range(nr):
        for i in range(ns):
            a = j * (ns + 1) + i
            rf.append((a, a + 1, a + ns + 2, a + ns + 1))
    mesh(rv, rf, "leaf_far", smooth=True)

    # the road out of the gate (game v -> world -Y), with a gentle bend
    gx, gy = sc["gate"]
    road = []
    for i in range(40):
        t = i / 39
        y = gy - 0.5 - t * 40
        x = gx + 2.5 * math.sin(t * 2.2)
        road.append((x, y))
    rv, rf = [], []
    for i, (x, y) in enumerate(road):
        w = 1.1 + 0.25 * math.sin(i * 0.7)
        rv += [(x - w, y, fz + 0.03), (x + w, y, fz + 0.03)]
        if i:
            rf.append((2 * i - 2, 2 * i - 1, 2 * i + 1, 2 * i))
    mesh(rv, rf, "dirt")

    def on_road(p: Vector) -> bool:
        return any(abs(p.x - x) < 2.6 and abs(p.y - y) < 1.2 for x, y in road)

    def near_terrace(p: Vector, margin: float) -> bool:
        return x0 - margin < p.x < x1 + margin and y0 - margin < p.y < y1 + margin

    def pine(p: Vector, s: float, mat: str) -> None:
        cyl(0.22 * s, 1.0 * s, tuple(p), "log", seg=6)
        for lvl in range(3):
            cone((1.5 - lvl * 0.36) * s, (2.0 - lvl * 0.3) * s, (p.x, p.y, p.z + (0.8 + lvl * 1.0) * s), mat, seg=7)

    def forest_density(s: float, d: float) -> float:
        # massed in the corners and toward the back, thin in front of the village
        side = _smooth((abs(s) - 14) / 14)
        back = _smooth((d + 4) / 18)
        clump = 0.5 + 0.5 * math.sin(s * 0.17 + 1.3) * math.cos(d * 0.21 + 0.4)
        return min(1.0, 0.9 * side + 0.55 * back) * (0.55 + 0.45 * clump)

    placed = 0
    tries = 0
    while placed < 1100 and tries < 40000:
        tries += 1
        s, d = rng.uniform(S0 + 2, S1 - 2), rng.uniform(D0 + 2, ridge_d - 7.5)
        if rng.random() > forest_density(s, d):
            continue
        p = ground(s, d, undulate(s, d))
        if near_terrace(p, 3.0) or on_road(p):
            continue
        sz = rng.uniform(0.85, 1.45)
        if hides_village([p, p + Vector((0, 0, 4.0 * sz)), p + rhat * 1.5 * sz, p - rhat * 1.5 * sz]):
            continue
        pine(p, sz, "leaf" if d < 6 else "leaf_far")
        placed += 1
    # the ridge is forest to its crest
    for _ in range(520):
        s = rng.uniform(S0 + 1, S1 - 1)
        t = rng.uniform(0.15, 0.97)
        d = ridge_d - 7 + 7 * t
        p = ground(s, d, crest(s) * _smooth(t) - 0.2)
        sz = rng.uniform(0.9, 1.4)
        if hides_village([p, p + Vector((0, 0, 4.0 * sz))]):
            continue
        pine(p, sz, "leaf_far")
    for _ in range(45):
        s, d = rng.uniform(S0 + 3, S1 - 3), rng.uniform(D0 + 3, ridge_d - 8)
        p = ground(s, d, undulate(s, d))
        r = rng.uniform(0.5, 1.4)
        if near_terrace(p, 1.5) or on_road(p) or hides_village([p, p + Vector((0, 0, r))]):
            continue
        blob(r, tuple(p), "rock", squash=(1.3, 1.0, 0.65), seed=rng.randint(0, 9999), rough=0.22)

    # the village's own camera
    data = bpy.data.cameras.new("Cam")
    data.type = "ORTHO"
    data.ortho_scale = sc["ortho_scale"]
    data.clip_start = 1
    data.clip_end = 1000
    cam = bpy.data.objects.new("Cam", data)
    cam.rotation_euler = rot
    cam.location = T - fwd * 200.0
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    core.lights(scene, sky=(0.62, 0.72, 0.84), sky_k=0.9)
    written = core.render_passes(scene, Path(job["out_dir"]), (W, H), job.get("samples", 64), (120.0, 300.0))
    core.emit({"written": written, "village_px": village, "trees": placed})
