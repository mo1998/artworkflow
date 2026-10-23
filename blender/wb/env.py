"""Environment subjects: wall surfaces, terrain tiles and the village backdrop.

Wall surfaces and terrain tiles are built PERIODIC at the source, so seams are fixed in
Blender rather than painted over afterwards:
  * wall tiles are W x H with W = 2H and every element repeats with period W (and H):
    sheared by 1/2 in the game, column W lands exactly one tile height down, so the
    sheared tile wraps without a seam;
  * terrain shaders sample 4D noise on a flat torus (cos u, sin u, cos v, sin v) - the
    texture is mathematically periodic in both directions.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import bpy
from mathutils import Euler, Vector

import core
from core import blob, box, cone, cyl, mesh

# --------------------------------------------------------------------------- walls

WALL_W, WALL_H = 4.0, 2.0


def _front_camera(scene, w: float, h: float):
    data = bpy.data.cameras.new("Cam")
    data.type = "ORTHO"
    data.ortho_scale = w
    cam = bpy.data.objects.new("Cam", data)
    cam.rotation_euler = Euler((math.radians(90), 0, 0), "XYZ")
    cam.location = (w / 2, -30.0, h / 2)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam


def _wrap_x(fn, x):
    for dx in (-WALL_W, 0.0, WALL_W):
        fn(x + dx)


def wall_palisade_surface(rng: random.Random):
    n = 9
    pitch = WALL_W / n
    box((WALL_W + 4, 0.3, WALL_H + 4), (WALL_W / 2, 0.5, -2), "dark", bevel=0)
    for i in range(n):
        r = pitch * 0.52
        wob = rng.uniform(-0.03, 0.03)
        _wrap_x(lambda x: cyl(r, WALL_H + 4, (x + wob, 0.0, -2), "log", seg=14), (i + 0.5) * pitch)
    for z in (WALL_H * 0.28, WALL_H * 0.78):
        cyl(0.07, WALL_W + 6, (-3, -pitch * 0.55, z), "timber_light", rot=(0, math.pi / 2, 0), seg=10)
        for i in range(n):
            _wrap_x(lambda x: cyl(pitch * 0.56, 0.09, (x, 0.0, z - 0.045), "rope", seg=14), (i + 0.5) * pitch)


def wall_timber_surface(rng: random.Random):
    rows = 5
    rh = WALL_H / rows
    box((WALL_W + 4, 0.3, WALL_H + 4), (WALL_W / 2, 0.45, -2), "dark", bevel=0)
    for j in range(-1, rows + 1):
        z = j * rh
        box((WALL_W + 6, 0.5, rh * 0.9), (WALL_W / 2, 0.0, z + rh * 0.05), "plank", bevel=0.05)
        # each course is butted at a staggered joint, so the logs read as logs, not a slab
        jx = (0.25 + 0.5 * (j % 2)) * WALL_W
        _wrap_x(lambda x: box((0.05, 0.52, rh * 0.9), (x, -0.01, z + rh * 0.05), "dark", bevel=0), jx)
    for bx in (WALL_W / 4, 3 * WALL_W / 4):
        _wrap_x(lambda x: box((0.16, 0.08, WALL_H + 4), (x, -0.29, -2), "iron", bevel=0.01), bx)
        for j in range(rows):
            _wrap_x(lambda x: cyl(0.045, 0.06, (x, -0.33, (j + 0.5) * rh), "iron",
                                  rot=(math.pi / 2, 0, 0), seg=8), bx)


def wall_stone_surface(rng: random.Random):
    rows = 5
    rh = WALL_H / rows
    box((WALL_W + 4, 0.3, WALL_H + 4), (WALL_W / 2, 0.4, -2), "mortar", bevel=0)
    courses = []
    for jm in range(rows):
        # block widths that sum to exactly WALL_W, so every course repeats along the run
        widths: list[float] = []
        while sum(widths) < WALL_W - 0.9:
            widths.append(rng.uniform(0.5, 0.9))
        widths.append(WALL_W - sum(widths))
        blocks = [(w, rng.uniform(0.32, 0.42)) for w in widths]
        courses.append((0.37 * jm % WALL_W, rh * rng.uniform(0.86, 0.93), blocks))
    for j in range(-1, rows + 1):
        start, hj, blocks = courses[j % rows]
        x = start
        for w, depth in blocks:
            _wrap_x(lambda xx: box((w - 0.05, depth, hj), (xx, 0.2 - depth / 2, j * rh + (rh - hj) / 2),
                                   "stone", bevel=0.07), x + w / 2)
            x += w


WALL_BUILDERS = {"palisade": wall_palisade_surface, "timber": wall_timber_surface, "stone": wall_stone_surface}


def run_wall_surface(job: dict):
    scene = core.reset()
    scene.render.film_transparent = False
    WALL_BUILDERS[job["kind"]](random.Random(int(job.get("seed", 7))))
    _front_camera(scene, WALL_W, WALL_H)
    # even light from the upper left and slightly in front: relief without a cast direction
    core.lights(scene, sun_dir=Vector((0.35, 0.85, -0.4)).normalized(), strength=1.7, sky_k=0.55, angle_deg=12)
    res = job.get("res", [512, 256])
    written = core.render_passes(scene, Path(job["out_dir"]), tuple(res), job.get("samples", 64), (28.0, 31.5))
    core.emit({"written": written, "tile": [WALL_W, WALL_H]})


# --------------------------------------------------------------------------- terrain

def _torus(nt, R: float, Ry: float | None = None, rep: float = 3.0):
    """(vector, w) sockets: tile coordinates mapped onto a flat 4D torus - periodic in u and v.

    The plane spans `rep` tiles (one past the frame on every side, so no edge pixel ever
    blends with the world behind it); u, v are tile units, 0..1 across the camera's view."""
    Ry = R if Ry is None else Ry
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])

    def op(kind, a, b=None):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = kind
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                nt.links.new(v, n.inputs[i])
        return n.outputs[0]

    off = (rep - 1.0) / 2.0
    u = op("SUBTRACT", op("MULTIPLY", sep.outputs["X"], rep), off)
    v = op("SUBTRACT", op("MULTIPLY", sep.outputs["Y"], rep), off)
    a = op("MULTIPLY", u, 2 * math.pi)
    b = op("MULTIPLY", v, 2 * math.pi)
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(op("MULTIPLY", op("COSINE", a), R), comb.inputs["X"])
    nt.links.new(op("MULTIPLY", op("SINE", a), R), comb.inputs["Y"])
    nt.links.new(op("MULTIPLY", op("COSINE", b), Ry), comb.inputs["Z"])
    w = op("MULTIPLY", op("SINE", b), Ry)
    return comb.outputs["Vector"], w, (u, v), op


def _noise4(nt, vec, w, scale, detail=6.0, rough=0.55):
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.noise_dimensions = "4D"
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    nt.links.new(vec, n.inputs["Vector"])
    nt.links.new(w, n.inputs["W"])
    return n


def _voronoi4(nt, vec, w, scale, feature="F1"):
    v = nt.nodes.new("ShaderNodeTexVoronoi")
    v.voronoi_dimensions = "4D"
    v.feature = feature
    v.inputs["Scale"].default_value = scale
    nt.links.new(vec, v.inputs["Vector"])
    nt.links.new(w, v.inputs["W"])
    return v


def _ramp(nt, fac, stops):
    r = nt.nodes.new("ShaderNodeValToRGB")
    els = r.color_ramp.elements
    els[0].position, els[0].color = stops[0][0], (*stops[0][1], 1)
    els[1].position, els[1].color = stops[-1][0], (*stops[-1][1], 1)
    for pos, col in stops[1:-1]:
        e = els.new(pos)
        e.color = (*col, 1)
    nt.links.new(fac, r.inputs["Fac"])
    return r.outputs["Color"]


def _mix(nt, fac, a, b, blend="MIX"):
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = "RGBA"
    m.blend_type = blend
    for sock, v in (("Factor", fac), ("A", a), ("B", b)):
        if isinstance(v, (tuple, list)):
            m.inputs[sock].default_value = (*v, 1) if len(v) == 3 else v
        elif isinstance(v, (int, float)):
            m.inputs[sock].default_value = v
        else:
            nt.links.new(v, m.inputs[sock])
    return m.outputs["Result"]


def terrain_material(kind: str) -> bpy.types.Material:
    mat = bpy.data.materials.new(f"terrain_{kind}")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.92
    vec, w, (tu, tv), op = _torus(nt, 1.0)
    bump = nt.nodes.new("ShaderNodeBump")
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if kind == "grass":
        big = _noise4(nt, vec, w, 1.6, 4)
        fine = _noise4(nt, vec, w, 38.0, 8, 0.7)
        col = _ramp(nt, big.outputs["Fac"], [(0.3, (0.09, 0.19, 0.04)), (0.5, (0.15, 0.28, 0.06)),
                                             (0.7, (0.22, 0.34, 0.08))])
        shade = _ramp(nt, fine.outputs["Fac"], [(0.35, (0.55, 0.6, 0.5)), (0.65, (1.0, 1.0, 1.0))])
        nt.links.new(_mix(nt, 0.6, col, shade, "MULTIPLY"), bsdf.inputs["Base Color"])
        nt.links.new(fine.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.6
    elif kind in ("dirt", "sand"):
        big = _noise4(nt, vec, w, 2.0, 4)
        fine = _noise4(nt, vec, w, 30.0 if kind == "dirt" else 60.0, 8, 0.6)
        peb = _voronoi4(nt, vec, w, 14.0 if kind == "dirt" else 30.0)
        if kind == "dirt":
            stops = [(0.3, (0.22, 0.14, 0.08)), (0.55, (0.33, 0.23, 0.13)), (0.75, (0.42, 0.31, 0.19))]
        else:
            stops = [(0.3, (0.42, 0.34, 0.21)), (0.55, (0.55, 0.45, 0.29)), (0.75, (0.63, 0.53, 0.36))]
        fac = op("ADD", op("MULTIPLY", big.outputs["Fac"], 0.6), op("MULTIPLY", fine.outputs["Fac"], 0.4))
        nt.links.new(_ramp(nt, fac, stops), bsdf.inputs["Base Color"])
        pebbles = op("MULTIPLY", op("LESS_THAN", peb.outputs["Distance"], 0.12), 0.6 if kind == "dirt" else 0.15)
        nt.links.new(op("ADD", fine.outputs["Fac"], pebbles), bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.5 if kind == "dirt" else 0.3
    elif kind == "rock":
        big = _noise4(nt, vec, w, 2.5, 6)
        cracks = _voronoi4(nt, vec, w, 0.7, "DISTANCE_TO_EDGE")
        col = _ramp(nt, big.outputs["Fac"], [(0.3, (0.24, 0.24, 0.23)), (0.55, (0.36, 0.35, 0.33)),
                                             (0.75, (0.45, 0.44, 0.41))])
        edge = op("MINIMUM", op("MULTIPLY", cracks.outputs["Distance"], 12.0), 1.0)
        nt.links.new(_mix(nt, edge, (0.08, 0.08, 0.08), col), bsdf.inputs["Base Color"])
        nt.links.new(op("ADD", edge, op("MULTIPLY", big.outputs["Fac"], 0.5)), bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.8
    elif kind == "cobble":
        cells = _voronoi4(nt, vec, w, 1.5, "DISTANCE_TO_EDGE")
        ids = _voronoi4(nt, vec, w, 1.5, "F1")
        tone = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(ids.outputs["Color"], tone.inputs[0])
        stone = _ramp(nt, tone.outputs[0], [(0.0, (0.26, 0.26, 0.25)), (0.5, (0.38, 0.37, 0.34)),
                                            (1.0, (0.48, 0.46, 0.42))])
        edge = op("MINIMUM", op("MULTIPLY", cells.outputs["Distance"], 14.0), 1.0)
        nt.links.new(_mix(nt, edge, (0.09, 0.08, 0.06), stone), bsdf.inputs["Base Color"])
        nt.links.new(op("POWER", edge, 0.5), bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 1.0
    elif kind == "wood":
        # 6 plank rows across v; two planks per row with staggered butt joints
        rows = 6.0
        # rows and joints are offset off the tile edge AND the half-tile line: the refine
        # crops the centre of a 2x2 tiling, so a joint on either line lands on the wrap
        vr = op("ADD", op("MULTIPLY", tv, rows), 0.27)
        frac_v = op("FRACT", vr)
        row = op("FLOORED_MODULO", op("FLOOR", vr), rows)
        u_off = op("FRACT", op("ADD", op("ADD", op("MULTIPLY", tu, 2.0), 0.13),
                               op("MULTIPLY", row, 0.37)))
        seam = op("MAXIMUM", op("LESS_THAN", frac_v, 0.035), op("LESS_THAN", u_off, 0.012))
        vec2, w2, _, _ = _torus(nt, 0.6, 9.0)
        grain = _noise4(nt, vec2, w2, 3.0, 8, 0.6)
        tone = op("ADD", op("MULTIPLY", op("FRACT", op("MULTIPLY", row, 0.618)), 0.25), grain.outputs["Fac"])
        col = _ramp(nt, op("MULTIPLY", tone, 0.8), [(0.25, (0.20, 0.12, 0.06)), (0.5, (0.32, 0.21, 0.11)),
                                                     (0.8, (0.42, 0.29, 0.16))])
        nt.links.new(_mix(nt, seam, col, (0.04, 0.025, 0.015)), bsdf.inputs["Base Color"])
        nt.links.new(op("SUBTRACT", grain.outputs["Fac"], seam), bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.5
    return mat


def run_terrain(job: dict):
    scene = core.reset()
    scene.render.film_transparent = False
    T = 4.0
    # one tile of margin on every side (the shader is periodic in T, see _torus)
    obj = mesh([(-T, -T, 0), (2 * T, -T, 0), (2 * T, 2 * T, 0), (-T, 2 * T, 0)], [(0, 1, 2, 3)], "dirt")
    obj.data.materials.clear()
    obj.data.materials.append(terrain_material(job["kind"]))
    obj["wb_mat"] = job["kind"]
    data = bpy.data.cameras.new("Cam")
    data.type = "ORTHO"
    data.ortho_scale = T
    cam = bpy.data.objects.new("Cam", data)
    cam.location = (T / 2, T / 2, 20)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    # light from almost straight above, a little from the upper left: relief, no shadow direction
    core.lights(scene, sun_dir=Vector((0.25, -0.25, -1.0)).normalized(), strength=3.2, sky_k=0.9, angle_deg=20)
    res = job.get("res", [512, 512])
    written = core.render_passes(scene, Path(job["out_dir"]), tuple(res), job.get("samples", 64), (19.5, 20.5))
    core.emit({"written": written})
